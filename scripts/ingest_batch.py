"""ingest_batch.py — operational intake for a new exam paper.

Takes a CSV of new questions (one paper = one batch), runs the duplicate
detector, and writes a self-contained JSON report to ingestion_batches/.

What it does that check_duplicates.py doesn't:
    - Generates a batch_id; report lives in ingestion_batches/<batch_id>.json
    - Validates the CSV more strictly (required cols, subject sanity)
    - Performs an intra-batch duplicate check (catches if the parser emitted
      the same question twice in one paper)
    - Persists each item's query embedding in the report, so the detector
      can be re-run with different thresholds later without paying Vertex again
    - Includes reviewer-decision placeholders in each item so the dashboard
      can attach state to specific items

What it does NOT do (deliberately):
    - Does not insert into questions table (reviewer-approval downstream)
    - Does not insert into question_embeddings (that's historical corpus only)
    - Does not classify NEW questions (out of scope; bounce to parent project)

CSV input — required columns:
    question                   the question text (HTML or markdown; we normalize)
    subject_id                 Postgres subject_id (or pass --subject for whole batch)

CSV input — optional columns:
    id                         caller's reference id for the row
    question_year              integer year
    option_1, option_2, option_3, option_4
    short_answer               option_1..option_4

Usage:
    python scripts/ingest_batch.py --input new_paper.csv
    python scripts/ingest_batch.py --input new_paper.csv --subject 10 --top-k 7
"""
import argparse
import csv
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2 import service_account

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from normalize import to_clean, to_fingerprint  # noqa: E402

load_dotenv()

# These must match check_duplicates.py / enrich_questions.py.
EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"
MODEL_NAME = "text-embedding-005"
MODEL_VERSION = "vertex-v1"
EMBED_BATCH = 50
THRESHOLD_HARD = 0.80
THRESHOLD_SOFT = 0.75
DEFAULT_TOP_K = 5

INGEST_DIR = ROOT / "ingestion_batches"


# --- Connection / client init ---------------------------------------------

def connect_pg():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )


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


# --- Input loading --------------------------------------------------------

def load_csv(path: Path, default_subject_id):
    if not path.exists():
        sys.exit(f"Input file not found: {path}")

    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fn_lower = {fn.lower(): fn for fn in (reader.fieldnames or [])}
        if "question" not in fn_lower:
            sys.exit("CSV must have a 'question' column.")
        q_col = fn_lower["question"]
        sid_col = fn_lower.get("subject_id")
        id_col = fn_lower.get("id") or fn_lower.get("question_id")
        year_col = fn_lower.get("question_year") or fn_lower.get("year")
        opt_cols = [fn_lower.get(f"option_{i}") for i in range(1, 5)]
        sa_col = fn_lower.get("short_answer")

        for i, r in enumerate(reader):
            qtext = (r.get(q_col) or "").strip()
            if not qtext:
                continue
            try:
                sid = int(r[sid_col]) if sid_col and r.get(sid_col) else default_subject_id
            except ValueError:
                sys.exit(f"Row {i}: subject_id is not an integer: {r.get(sid_col)!r}")
            if sid is None:
                sys.exit(f"Row {i}: no subject_id (CSV has no subject_id column and --subject not set).")
            year_val = None
            if year_col and (r.get(year_col) or "").strip():
                try:
                    year_val = int(r[year_col])
                except ValueError:
                    year_val = None
            rows.append({
                "input_index": i,
                "input_id": (r.get(id_col).strip() if id_col and r.get(id_col) else None),
                "subject_id": sid,
                "question_year": year_val,
                "question_raw": qtext,
                "options": [r.get(c) for c in opt_cols if c],
                "short_answer": r.get(sa_col) if sa_col else None,
            })
    if not rows:
        sys.exit("No usable rows in input CSV.")
    return rows


def validate_inputs(rows, conn):
    """Sanity-check subject_ids exist + are W/JW (warn on J-only, fail on unknown)."""
    needed = {r["subject_id"] for r in rows}
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, tag FROM subjects WHERE id = ANY(%s);", (list(needed),))
        found = {sid: (name, str(tag)) for sid, name, tag in cur.fetchall()}
    missing = needed - found.keys()
    if missing:
        sys.exit(f"Unknown subject_id(s) in input: {sorted(missing)}")
    non_wjw = [sid for sid, (n, tag) in found.items() if tag not in ("W", "JW")]
    if non_wjw:
        print(f"  WARNING: subject_id(s) {non_wjw} are not tagged W or JW; their dup-check pool may be empty.")
    return {sid: name for sid, (name, _) in found.items()}


# --- Embedding ------------------------------------------------------------

def embed_query_texts(client, texts):
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=list(texts),
        config=types.EmbedContentConfig(
            task_type=TASK_TYPE_QUERY,
            output_dimensionality=EMBED_DIMS,
        ),
    )
    return [e.values for e in resp.embeddings]


def vector_to_pg(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


# --- Per-question lookups -------------------------------------------------

FP_MATCH_SQL = """
    SELECT qe.question_id, q.question_year, q.question_year_number,
           qe.text_clean,
           q.option_1, q.option_2, q.option_3, q.option_4
    FROM question_embeddings qe
    JOIN questions q ON q.id = qe.question_id
    WHERE qe.subject_id = %s
      AND qe.tag IN ('W','JW')
      AND qe.model_name = %s AND qe.model_version = %s
      AND qe.search_fingerprint = %s
    LIMIT 5
"""

ANN_SQL = """
    SELECT qe.question_id, qe.question_year, q.question_year_number,
           qe.text_clean, qe.search_fingerprint,
           q.option_1, q.option_2, q.option_3, q.option_4,
           1 - (qe.embedding <=> %s::vector) AS cosine
    FROM question_embeddings qe
    JOIN questions q ON q.id = qe.question_id
    WHERE qe.subject_id = %s
      AND qe.tag IN ('W','JW')
      AND qe.model_name = %s AND qe.model_version = %s
    ORDER BY qe.embedding <=> %s::vector
    LIMIT %s
"""


def lookup_one(conn, subject_id, search_fingerprint, embedding, top_k):
    emb_pg = vector_to_pg(embedding)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        fp_hits = []
        if search_fingerprint:
            cur.execute(FP_MATCH_SQL, (subject_id, MODEL_NAME, MODEL_VERSION, search_fingerprint))
            fp_hits = cur.fetchall()
        cur.execute(ANN_SQL, (emb_pg, subject_id, MODEL_NAME, MODEL_VERSION, emb_pg, top_k))
        ann = cur.fetchall()
    return fp_hits, ann


def verdict_for(fp_hits, ann, threshold_hard, threshold_soft):
    top = ann[0] if ann else None
    top_cos = float(top["cosine"]) if top else None
    if fp_hits:
        return "REPEAT", "exact fingerprint match"
    if top_cos is not None and top_cos >= threshold_hard:
        return "NEAR_HIGH", f"semantic cosine {top_cos:.3f} >= {threshold_hard} (no fingerprint match — review)"
    if top_cos is not None and top_cos >= threshold_soft:
        return "NEAR", f"semantic cosine {top_cos:.3f} >= {threshold_soft}"
    return "NEW", f"no match above {threshold_soft}"


# --- Intra-batch duplicate check ------------------------------------------

def find_intra_batch_duplicates(rows):
    """Return groups of input_indices that share a non-empty search_fingerprint."""
    by_fp = defaultdict(list)
    for r in rows:
        fp = r.get("search_fingerprint") or ""
        if not fp:
            continue
        by_fp[fp].append(r["input_index"])
    return [
        {"search_fingerprint": fp, "input_indices": idxs}
        for fp, idxs in by_fp.items() if len(idxs) > 1
    ]


# --- Main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Ingest a new exam paper and run dup-check.")
    ap.add_argument("--input", type=Path, required=True, help="CSV of new questions.")
    ap.add_argument("--subject", type=int,
                    help="Default subject_id if CSV has no subject_id column.")
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                    help=f"Top-K neighbors per question (default {DEFAULT_TOP_K}).")
    ap.add_argument("--threshold-hard", type=float, default=THRESHOLD_HARD,
                    help=f"Cosine cutoff for NEAR_HIGH (default {THRESHOLD_HARD}).")
    ap.add_argument("--threshold-soft", type=float, default=THRESHOLD_SOFT,
                    help=f"Cosine cutoff for NEAR (default {THRESHOLD_SOFT}).")
    ap.add_argument("--batch-id", type=str,
                    help="Optional explicit batch id (default: ingest_<UTC timestamp>_<short uuid>).")
    args = ap.parse_args()

    if not (0 < args.threshold_soft <= args.threshold_hard <= 1.0):
        sys.exit("Thresholds must satisfy 0 < soft <= hard <= 1.")

    batch_id = args.batch_id or f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    INGEST_DIR.mkdir(exist_ok=True)
    output_path = INGEST_DIR / f"{batch_id}.json"
    if output_path.exists():
        sys.exit(f"Output already exists (refusing to overwrite): {output_path}")

    print(f"Batch id: {batch_id}")
    print(f"Output:   {output_path}")
    print()
    print("Connecting to database...")
    conn = connect_pg()
    print(f"  host={os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}  db={os.getenv('DB_NAME')}")

    print(f"Loading {args.input}...")
    rows = load_csv(args.input, default_subject_id=args.subject)
    print(f"  {len(rows)} rows loaded.")

    subj_names = validate_inputs(rows, conn)

    print("Normalizing...")
    for r in rows:
        r["text_clean"] = to_clean(r["question_raw"])
        r["search_fingerprint"] = to_fingerprint(r["text_clean"])

    intra_dups = find_intra_batch_duplicates(rows)
    if intra_dups:
        print(f"  Intra-batch fingerprint matches: {len(intra_dups)} group(s)")
        for g in intra_dups[:5]:
            print(f"    indices {g['input_indices']}")
        if len(intra_dups) > 5:
            print(f"    (+ {len(intra_dups) - 5} more — see report)")

    print(f"Embedding {len(rows)} queries via Vertex AI (task={TASK_TYPE_QUERY})...")
    client = init_genai_client()
    t0 = time.time()
    for batch in chunked(rows, EMBED_BATCH):
        embed_items = [r for r in batch if r["text_clean"].strip()]
        if not embed_items:
            continue
        vectors = embed_query_texts(client, [r["text_clean"] for r in embed_items])
        for r, v in zip(embed_items, vectors):
            r["embedding"] = v
    print(f"  embed time: {time.time() - t0:.1f}s")

    print("Looking up matches...")
    t0 = time.time()
    items = []
    for r in rows:
        if "embedding" not in r:
            v, reason = "NEW", "empty text after normalization"
            items.append(_make_item(r, subj_names, v, reason, [], [], None))
            continue
        fp_hits, ann = lookup_one(
            conn, r["subject_id"], r["search_fingerprint"], r["embedding"], args.top_k
        )
        v, reason = verdict_for(fp_hits, ann, args.threshold_hard, args.threshold_soft)
        items.append(_make_item(r, subj_names, v, reason, fp_hits, ann, r["embedding"]))
    print(f"  lookup time: {time.time() - t0:.1f}s")
    conn.close()

    # Summaries.
    verdict_keys = ("REPEAT", "NEAR_HIGH", "NEAR", "NEW")
    summary = {"total": len(items), **{k: 0 for k in verdict_keys}, "by_subject": {}}
    for it in items:
        v = it["verdict"]
        summary[v] += 1
        sname = it["input"]["subject_name"] or f"subject_{it['input']['subject_id']}"
        bucket = summary["by_subject"].setdefault(sname, {"total": 0, **{k: 0 for k in verdict_keys}})
        bucket["total"] += 1
        bucket[v] += 1
    summary["intra_batch_duplicate_groups"] = len(intra_dups)

    report = {
        "meta": {
            "batch_id": batch_id,
            "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_file": str(args.input),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "embed_dims": EMBED_DIMS,
            "task_type_query": TASK_TYPE_QUERY,
            "thresholds": {"hard": args.threshold_hard, "soft": args.threshold_soft},
            "top_k": args.top_k,
            "status": "pending_review",
        },
        "summary": summary,
        "intra_batch_duplicates": intra_dups,
        "items": items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # Console summary.
    print()
    print(f"Total: {summary['total']}   |  REPEAT: {summary['REPEAT']}  "
          f"NEAR_HIGH: {summary['NEAR_HIGH']}  NEAR: {summary['NEAR']}  NEW: {summary['NEW']}")
    if summary["intra_batch_duplicate_groups"]:
        print(f"Intra-batch duplicate groups: {summary['intra_batch_duplicate_groups']}")
    if summary["by_subject"]:
        print("By subject:")
        for sname, b in sorted(summary["by_subject"].items()):
            print(f"  {sname:<28} total={b['total']:>3}  REPEAT={b['REPEAT']:>3}  "
                  f"NEAR_HIGH={b['NEAR_HIGH']:>3}  NEAR={b['NEAR']:>3}  NEW={b['NEW']:>3}")
    print(f"\nReport: {output_path}")


def _make_item(r, subj_names, verdict, reason, fp_hits, ann, embedding):
    """Build one items[] entry, including reviewer-decision placeholders."""
    fp_match_ids = {h["question_id"] for h in fp_hits}
    return {
        "input_index": r["input_index"],
        "input_id": r.get("input_id"),
        "input": {
            "subject_id": r["subject_id"],
            "subject_name": subj_names.get(r["subject_id"]),
            "question_year": r.get("question_year"),
            "question_raw": r["question_raw"],
            "text_clean": r["text_clean"],
            "search_fingerprint": r["search_fingerprint"],
            "options": r.get("options"),
            "short_answer": r.get("short_answer"),
        },
        "verdict": verdict,
        "reason": reason,
        "fingerprint_matches": [
            {
                "question_id": h["question_id"],
                "question_year": h["question_year"],
                "text_clean": h["text_clean"],
            }
            for h in fp_hits
        ],
        "top_k": [
            {
                "question_id": a["question_id"],
                "cosine": float(a["cosine"]),
                "question_year": a["question_year"],
                "text_clean": a["text_clean"],
                "fingerprint_match": a["question_id"] in fp_match_ids,
            }
            for a in ann
        ],
        "query_embedding": embedding,   # 768 floats; persisted so re-analysis doesn't re-call Vertex
        # Reviewer state — populated later by the dashboard.
        "reviewer_decision": None,      # accept | reject | escalate | classify
        "reviewer_notes": None,
        "reviewed_at": None,
        "reviewed_by": None,
    }


if __name__ == "__main__":
    main()
