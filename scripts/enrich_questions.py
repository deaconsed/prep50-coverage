"""Backfill question_embeddings for all W/JW questions.

For every classified WAEC question that doesn't yet have a row in
question_embeddings (for this model_name/model_version), this script:
    1. Normalizes question text -> text_clean + search_fingerprint
    2. Sends a batch to Vertex AI text-embedding-005 (768d, RETRIEVAL_DOCUMENT)
    3. Inserts into question_embeddings with denormalized subject_id/tag/year

Resume safety: each insert uses ON CONFLICT DO NOTHING on the
uq_qe_question_model unique constraint, so re-running picks up exactly
where it left off without duplicating rows.

Threading: a ThreadedConnectionPool gives each worker its own DB connection;
psycopg2 connections are not safe to share across threads.

Failure isolation: a Vertex error on one batch is logged and the batch is
written to a retry file; the job continues.

Usage:
    # Dry-run: show counts, no embedding calls, no writes.
    python scripts/enrich_questions.py --dry-run

    # Small test (50 questions, single batch, ~5s):
    python scripts/enrich_questions.py --limit 50

    # One subject (Physics is prod subject_id=10):
    python scripts/enrich_questions.py --subject 10

    # Full backfill against whatever DB the .env points at:
    python scripts/enrich_questions.py

    # Bypass the confirmation prompt (CI / scheduled runs):
    python scripts/enrich_questions.py --yes

Production note: switch targets by editing DB_HOST/DB_PORT/DB_USER/DB_PASSWORD
in .env. The script warns and demands extra confirmation when DB_HOST does
not look like a local target.
"""
import argparse
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2 import service_account
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from normalize import to_clean, to_fingerprint  # noqa: E402

load_dotenv()

# Model + indexing config — must stay aligned with the migration and
# any downstream dup-check code. If you ever change EMBED_MODEL or
# MODEL_VERSION, that's a NEW row per question (the unique constraint
# is on the triple) — old rows stay; new rows are added.
EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
TASK_TYPE = "RETRIEVAL_DOCUMENT"
MODEL_NAME = "text-embedding-005"
MODEL_VERSION = "vertex-v1"

# Vertex limits: 250 inputs per call documented; 50 is conservative and
# gives readable per-batch progress.
EMBED_BATCH = 50

DEFAULT_WORKERS = 16

# Hosts considered "local enough" to not require extra confirmation.
LOCAL_HOST_TOKENS = ("localhost", "127.0.0.1", "::1")

RETRY_LOG = ROOT / "test_data" / "enrich_failed_batches.jsonl"


def is_local_db_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return any(tok in h for tok in LOCAL_HOST_TOKENS)


def make_conn_pool(workers: int):
    """Create a thread-safe pool sized to the worker count + 1 (for main thread)."""
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "15433"))
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    dbname = os.getenv("DB_NAME", "prep50")
    sslmode = os.getenv("DB_SSLMODE", "prefer")  # DO managed PG: 'require'
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=workers + 1,
        host=host, port=port, user=user, password=password,
        dbname=dbname, sslmode=sslmode,
    ), {"host": host, "port": port, "user": user, "dbname": dbname, "sslmode": sslmode}


def init_genai_client():
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not (project and creds_path and Path(creds_path).exists()):
        sys.exit("Missing Vertex AI config (GOOGLE_CLOUD_PROJECT, GOOGLE_APPLICATION_CREDENTIALS).")
    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return genai.Client(vertexai=True, project=project, location=location, credentials=creds)


PENDING_SQL = """
    SELECT q.id, q.subject_id, q.tag, q.question_year, q.question
    FROM questions q
    LEFT JOIN question_embeddings qe
      ON qe.question_id = q.id
     AND qe.model_name = %(model_name)s
     AND qe.model_version = %(model_version)s
    WHERE q.tag IN ('W', 'JW')
      AND q.question IS NOT NULL AND q.question <> ''
      AND qe.id IS NULL
      {extra}
    ORDER BY q.id
    {limit}
"""

COUNT_SQL = """
    SELECT
      (SELECT COUNT(*) FROM questions q WHERE q.tag IN ('W','JW')
         AND q.question IS NOT NULL AND q.question <> '') AS total_wjw,
      (SELECT COUNT(*) FROM question_embeddings
         WHERE model_name = %(model_name)s AND model_version = %(model_version)s) AS already_embedded
"""


def fetch_pending(pool, subject_id=None, limit=None):
    extra = "AND q.subject_id = %(subject_id)s" if subject_id else ""
    lim = "LIMIT %(limit)s" if limit else ""
    sql = PENDING_SQL.format(extra=extra, limit=lim)
    params = {"model_name": MODEL_NAME, "model_version": MODEL_VERSION}
    if subject_id:
        params["subject_id"] = subject_id
    if limit:
        params["limit"] = limit
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        pool.putconn(conn)


def fetch_counts(pool):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(COUNT_SQL, {"model_name": MODEL_NAME, "model_version": MODEL_VERSION})
            row = cur.fetchone()
            return {"total_wjw": row[0], "already_embedded": row[1]}
    finally:
        pool.putconn(conn)


def chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def vector_to_pg(vec):
    """pgvector accepts text like '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def embed_and_insert(batch, client, pool, retry_lock):
    """Embed one batch and write to question_embeddings.

    Returns: (success_count, error_or_None)
    """
    texts_clean = [to_clean(r["question"]) for r in batch]
    texts_fp = [to_fingerprint(c) for c in texts_clean]

    # Some questions may normalize to empty (image-only stems, junk html).
    # text_clean is NOT NULL in the schema; we skip those rather than insert empty rows.
    embed_indices = [i for i, t in enumerate(texts_clean) if t.strip()]
    if not embed_indices:
        return 0, None

    embed_inputs = [texts_clean[i] for i in embed_indices]

    try:
        resp = client.models.embed_content(
            model=EMBED_MODEL,
            contents=embed_inputs,
            config=types.EmbedContentConfig(
                task_type=TASK_TYPE,
                output_dimensionality=EMBED_DIMS,
            ),
        )
        vectors = [e.values for e in resp.embeddings]
    except Exception as exc:
        # Log failed batch IDs to retry file.
        ids = [batch[i]["id"] for i in embed_indices]
        with retry_lock:
            with open(RETRY_LOG, "a", encoding="utf-8") as f:
                import json
                f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "ids": ids, "error": str(exc)}) + "\n")
        return 0, exc

    if len(vectors) != len(embed_indices):
        return 0, RuntimeError(f"Vertex returned {len(vectors)} vectors for {len(embed_indices)} inputs")

    rows = []
    for vec, idx in zip(vectors, embed_indices):
        if len(vec) != EMBED_DIMS:
            return 0, RuntimeError(f"Embedding dim {len(vec)} != {EMBED_DIMS} (question_id={batch[idx]['id']})")
        rows.append((
            batch[idx]["id"],
            batch[idx]["subject_id"],
            str(batch[idx]["tag"]),
            batch[idx]["question_year"],
            texts_clean[idx],
            texts_fp[idx],
            vector_to_pg(vec),
            MODEL_NAME,
            MODEL_VERSION,
        ))

    insert_sql = """
        INSERT INTO question_embeddings
          (question_id, subject_id, tag, question_year, text_clean,
           search_fingerprint, embedding, model_name, model_version)
        VALUES %s
        ON CONFLICT (question_id, model_name, model_version) DO NOTHING
    """
    # Explicit ::vector cast keeps us robust if implicit text->vector ever changes.
    insert_template = "(%s, %s, %s::tag, %s, %s, %s, %s::vector, %s, %s)"
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, insert_sql, rows,
                template=insert_template,
                page_size=len(rows),
            )
            inserted = cur.rowcount
        conn.commit()
        return inserted, None
    except Exception as exc:
        conn.rollback()
        ids = [r[0] for r in rows]
        with retry_lock:
            with open(RETRY_LOG, "a", encoding="utf-8") as f:
                import json
                f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "ids": ids, "error": f"insert: {exc}"}) + "\n")
        return 0, exc
    finally:
        pool.putconn(conn)


def human_int(n):
    return f"{n:,}"


def confirm(prompt, default_no=True):
    sfx = "[y/N]" if default_no else "[Y/n]"
    ans = input(f"{prompt} {sfx}: ").strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def main():
    ap = argparse.ArgumentParser(description="Embed W/JW questions into question_embeddings.")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"Concurrent worker threads (default {DEFAULT_WORKERS}).")
    ap.add_argument("--batch", type=int, default=EMBED_BATCH,
                    help=f"Embedding batch size (default {EMBED_BATCH}, Vertex max 250).")
    ap.add_argument("--limit", type=int, help="Only process N pending questions (test runs).")
    ap.add_argument("--subject", type=int, help="Only this Postgres subject_id.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show counts and exit. No embedding, no writes.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip confirmation prompts (use for unattended runs).")
    args = ap.parse_args()

    if args.batch > 250:
        sys.exit("--batch cannot exceed Vertex's 250-input limit.")
    if args.workers < 1:
        sys.exit("--workers must be >= 1.")

    RETRY_LOG.parent.mkdir(exist_ok=True)

    print("Connecting to database...")
    pool, db_info = make_conn_pool(args.workers)
    print(f"  host={db_info['host']}:{db_info['port']}  db={db_info['dbname']}  user={db_info['user']}  sslmode={db_info['sslmode']}")

    counts = fetch_counts(pool)
    pending_rows = fetch_pending(pool, subject_id=args.subject, limit=args.limit)

    pending = len(pending_rows)
    remaining_no_limit = counts["total_wjw"] - counts["already_embedded"]
    print()
    print(f"Model:           {MODEL_NAME} / {MODEL_VERSION}  ({EMBED_DIMS}d, task={TASK_TYPE})")
    print(f"Total W/JW:      {human_int(counts['total_wjw'])}")
    print(f"Already embedded:{human_int(counts['already_embedded'])}")
    print(f"Remaining:       {human_int(remaining_no_limit)}")
    if args.subject:
        print(f"Subject filter:  subject_id={args.subject}")
    if args.limit:
        print(f"This run:        up to {human_int(args.limit)}")
    print(f"Will process:    {human_int(pending)} questions")
    print(f"Workers:         {args.workers}  |  Batch size: {args.batch}  |  Batches: {math.ceil(pending / args.batch) if pending else 0}")

    if args.dry_run:
        print("\n[--dry-run] No embedding calls made. Exiting.")
        return

    if pending == 0:
        print("\nNothing to do — all W/JW questions already embedded for this model/version.")
        return

    # Production guard: warn if host doesn't look local.
    if not is_local_db_host(db_info["host"]):
        print()
        print(f"  !!  Target DB host '{db_info['host']}' is NOT local.")
        print(f"  !!  This will insert {human_int(pending)} rows into the remote database.")
        if not args.yes:
            if not confirm("  Proceed against this remote DB?", default_no=True):
                print("Aborted.")
                return

    if not args.yes:
        print()
        if not confirm("Start embedding now?", default_no=False):
            print("Aborted.")
            return

    print(f"\nStarting embedding at {datetime.now().isoformat(timespec='seconds')}...")
    client = init_genai_client()
    retry_lock = Lock()

    batches = list(chunked(pending_rows, args.batch))
    t0 = time.time()
    total_inserted = 0
    total_errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(embed_and_insert, b, client, pool, retry_lock): i for i, b in enumerate(batches)}
        with tqdm(total=pending, desc="embedding", unit="q") as pbar:
            for fut in as_completed(futures):
                inserted, err = fut.result()
                batch_size = len(batches[futures[fut]])
                if err is not None:
                    total_errors += 1
                    pbar.write(f"  [batch {futures[fut]}] FAILED ({batch_size} questions): {err}")
                total_inserted += inserted
                pbar.update(batch_size)

    elapsed = time.time() - t0
    print()
    print(f"Done in {elapsed:.1f}s.")
    print(f"Inserted:        {human_int(total_inserted)}")
    print(f"Failed batches:  {total_errors}")
    if total_errors:
        print(f"See retry log:   {RETRY_LOG}")

    # Final count check.
    after = fetch_counts(pool)
    print(f"DB row count for {MODEL_NAME}/{MODEL_VERSION}: {human_int(after['already_embedded'])}")

    pool.closeall()


if __name__ == "__main__":
    main()
