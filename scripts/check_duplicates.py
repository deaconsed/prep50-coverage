"""check_duplicates.py — check new exam questions against the historical corpus.

For each input question:
    1. Normalize -> text_clean + search_fingerprint (same rules as enrich).
    2. Embed via Vertex text-embedding-005 with task_type=RETRIEVAL_QUERY.
    3. Look up exact fingerprint matches within the same subject (W/JW only).
    4. ANN top-K via pgvector cosine distance, scoped to subject + W/JW.

Verdict per question (thresholds tunable below or via CLI):
    REPEAT     -> exact fingerprint match in corpus (only high-precision signal)
    NEAR_HIGH  -> no fingerprint match, but top-1 cosine >= THRESHOLD_HARD (0.85)
    NEAR       -> top-1 cosine >= THRESHOLD_SOFT (0.75)
    NEW        -> nothing within THRESHOLD_SOFT

Cosine-only matches above HARD are NEAR_HIGH (priority review), not REPEAT, because
the DOC/QUERY asymmetry + cosine-distribution overlap (see [[calibration-findings]])
make cosine-only auto-REPEAT decisions unsafe. A human confirms NEAR_HIGH cases.

Output: a single JSON report with run metadata, summary counts, and per-question
results including the top-K matched historical questions. Console prints a
human summary at the end.

Read-only: no writes to question_embeddings.

Usage:
    # Self-test: sample N random rows already in the DB, expect cosine ~1.0
    # for each one finding itself.
    python scripts/check_duplicates.py --self-test --subject 10 --n 20

    # Real check against a CSV.
    # CSV must have at least a `question` column. Subject can be either a
    # `subject_id` column per row, OR --subject for the whole file.
    python scripts/check_duplicates.py --input new_paper.csv --subject 10

    # Override thresholds for tuning.
    python scripts/check_duplicates.py --input paper.csv --threshold-hard 0.90 --threshold-soft 0.75
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
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

# --- TUNABLE: keep thresholds in one place. See [[decisions-core]] memory. ---
# Calibrated 2026-06-04 from a 100-query / top-5 study against the prod corpus.
# DOC vs QUERY task-type asymmetry means same-text cosines top out at ~0.92,
# and true-repeat / different-question distributions OVERLAP in the 0.75-0.89 range.
# So: cosine-only is NEVER auto-REPEAT; fingerprint exact match is the only high-
# precision REPEAT signal. See verdict_for() and [[calibration-findings]] memory.
THRESHOLD_HARD = 0.80    # >= this cosine -> NEAR_HIGH (priority review)
THRESHOLD_SOFT = 0.75    # >= this cosine -> NEAR (review queue)

DEFAULT_TOP_K = 5

# Model config — must match enrich_questions.py so we query our own rows.
EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"
MODEL_NAME = "text-embedding-005"
MODEL_VERSION = "vertex-v1"

EMBED_BATCH = 50  # Vertex batch size for embedding the input questions.

OUT_DIR = ROOT / "test_data"


# --- Connection / client init ---------------------------------------------

def connect_pg():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "15433")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "prep50"),
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

def load_csv(path: Path, default_subject_id=None):
    """Load CSV. Must have a `question` column. subject_id per row OR via --subject."""
    if not path.exists():
        sys.exit(f"Input file not found: {path}")
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Normalize column names case-insensitively.
        fieldnames_lower = {fn.lower(): fn for fn in (reader.fieldnames or [])}
        if "question" not in fieldnames_lower:
            sys.exit("CSV must have a 'question' column.")
        q_col = fieldnames_lower["question"]
        sid_col = fieldnames_lower.get("subject_id")
        year_col = fieldnames_lower.get("question_year") or fieldnames_lower.get("year")
        id_col = fieldnames_lower.get("id") or fieldnames_lower.get("question_id")

        for i, r in enumerate(reader):
            if not (r.get(q_col) or "").strip():
                continue
            try:
                sid = int(r[sid_col]) if sid_col and r.get(sid_col) else default_subject_id
            except ValueError:
                sys.exit(f"Row {i}: subject_id is not an integer: {r.get(sid_col)!r}")
            if sid is None:
                sys.exit(f"Row {i}: no subject_id (CSV has no subject_id column and --subject not set).")
            rows.append({
                "input_index": i,
                "input_id": r.get(id_col) if id_col else None,
                "subject_id": sid,
                "question_year": int(r[year_col]) if year_col and (r.get(year_col) or "").isdigit() else None,
                "question_raw": r[q_col],
            })
    if not rows:
        sys.exit("No usable rows in input CSV.")
    return rows


def load_self_test(conn, subject_id, n):
    """Pull N random W/JW questions that ALREADY have embeddings; each should
    find itself as top-1 with cosine ~1.0."""
    sql = """
        SELECT q.id, q.subject_id, q.question_year, q.question
        FROM questions q
        JOIN question_embeddings qe
          ON qe.question_id = q.id
         AND qe.model_name = %s AND qe.model_version = %s
        WHERE q.tag IN ('W','JW')
          AND q.question IS NOT NULL AND q.question <> ''
          {subject_clause}
        ORDER BY random()
        LIMIT %s
    """.format(subject_clause="AND q.subject_id = %s" if subject_id else "")
    params = [MODEL_NAME, MODEL_VERSION]
    if subject_id:
        params.append(subject_id)
    params.append(n)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "input_index": i,
            "input_id": r["id"],
            "subject_id": r["subject_id"],
            "question_year": r["question_year"],
            "question_raw": r["question"],
        }
        for i, r in enumerate(rows)
    ]


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
           qe.text_clean, qe.search_fingerprint,
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


def lookup_one(conn, subject_id, text_clean, search_fingerprint, embedding, top_k):
    emb_pg = vector_to_pg(embedding)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Fingerprint exact match (only meaningful when fingerprint is non-empty).
        fp_hits = []
        if search_fingerprint:
            cur.execute(FP_MATCH_SQL, (subject_id, MODEL_NAME, MODEL_VERSION, search_fingerprint))
            fp_hits = cur.fetchall()
        # ANN top-K.
        cur.execute(ANN_SQL, (emb_pg, subject_id, MODEL_NAME, MODEL_VERSION, emb_pg, top_k))
        ann = cur.fetchall()
    return fp_hits, ann


# --- Verdict --------------------------------------------------------------

def verdict_for(fp_hits, ann, threshold_hard, threshold_soft):
    """Verdict policy:
        REPEAT     -> fingerprint exact match (the only precise auto-decision)
        NEAR_HIGH  -> no fingerprint, but cosine >= HARD (priority human review)
        NEAR       -> cosine >= SOFT (regular human review)
        NEW        -> otherwise

    We do NOT auto-REPEAT on cosine alone because true-repeat and unrelated-
    question cosine distributions overlap in the 0.75-0.89 band — calibration
    on 100 prod queries (2026-06-04) showed no clean cosine separator.
    """
    top = ann[0] if ann else None
    top_cos = float(top["cosine"]) if top else None

    if fp_hits:
        return "REPEAT", "exact fingerprint match"
    if top_cos is not None and top_cos >= threshold_hard:
        return "NEAR_HIGH", f"semantic cosine {top_cos:.3f} >= {threshold_hard} (no fingerprint match — review)"
    if top_cos is not None and top_cos >= threshold_soft:
        return "NEAR", f"semantic cosine {top_cos:.3f} >= {threshold_soft}"
    return "NEW", f"no match above {threshold_soft}"


# --- Main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Check new exam questions for duplicates.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="CSV with a 'question' column.")
    src.add_argument("--self-test", action="store_true",
                     help="Pull N random already-embedded questions; expect cosine ~1.0.")
    ap.add_argument("--subject", type=int,
                    help="Postgres subject_id. Required for --self-test; optional for --input (per-row column overrides).")
    ap.add_argument("--n", type=int, default=20, help="--self-test sample size (default 20).")
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                    help=f"Top-K neighbors per question (default {DEFAULT_TOP_K}).")
    ap.add_argument("--threshold-hard", type=float, default=THRESHOLD_HARD,
                    help=f"Cosine cutoff for REPEAT (default {THRESHOLD_HARD}).")
    ap.add_argument("--threshold-soft", type=float, default=THRESHOLD_SOFT,
                    help=f"Cosine cutoff for NEAR (default {THRESHOLD_SOFT}).")
    ap.add_argument("--output", type=Path,
                    help="JSON report path (default test_data/dup_check_<timestamp>.json).")
    args = ap.parse_args()

    if args.self_test and not args.subject:
        sys.exit("--self-test requires --subject <id>.")
    if not (0 < args.threshold_soft <= args.threshold_hard <= 1.0):
        sys.exit("Thresholds must satisfy 0 < soft <= hard <= 1.")

    OUT_DIR.mkdir(exist_ok=True)
    output_path = args.output or (OUT_DIR / f"dup_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    print("Connecting to database...")
    conn = connect_pg()
    print(f"  host={os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}  db={os.getenv('DB_NAME')}")

    if args.self_test:
        print(f"Loading {args.n} random embedded questions from subject {args.subject}...")
        inputs = load_self_test(conn, args.subject, args.n)
    else:
        print(f"Loading CSV: {args.input}")
        inputs = load_csv(args.input, default_subject_id=args.subject)
    print(f"  {len(inputs)} questions to check.")

    # Subject names for the report.
    subj_names = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM subjects WHERE tag IN ('W','JW');")
        for sid, name in cur.fetchall():
            subj_names[sid] = name

    print("Normalizing...")
    for r in inputs:
        r["text_clean"] = to_clean(r["question_raw"])
        r["search_fingerprint"] = to_fingerprint(r["text_clean"])

    print(f"Embedding {len(inputs)} queries via Vertex AI ({EMBED_MODEL}, task={TASK_TYPE_QUERY})...")
    client = init_genai_client()
    t0 = time.time()
    for batch in chunked(inputs, EMBED_BATCH):
        # Embed only non-empty text. Empty text -> mark as NEW with no neighbors.
        embed_items = [r for r in batch if r["text_clean"].strip()]
        if embed_items:
            vectors = embed_query_texts(client, [r["text_clean"] for r in embed_items])
            for r, v in zip(embed_items, vectors):
                r["embedding"] = v
    print(f"  embed time: {time.time() - t0:.1f}s")

    print("Looking up matches...")
    t0 = time.time()
    results = []
    for r in inputs:
        if "embedding" not in r:
            verdict, reason = "NEW", "empty text after normalization"
            results.append({
                "input_index": r["input_index"],
                "input_id": r.get("input_id"),
                "input": {
                    "subject_id": r["subject_id"],
                    "subject_name": subj_names.get(r["subject_id"]),
                    "question_year": r.get("question_year"),
                    "question_raw": r["question_raw"],
                    "text_clean": r["text_clean"],
                    "search_fingerprint": r["search_fingerprint"],
                },
                "verdict": verdict,
                "reason": reason,
                "fingerprint_matches": [],
                "top_k": [],
            })
            continue

        fp_hits, ann = lookup_one(
            conn, r["subject_id"], r["text_clean"], r["search_fingerprint"],
            r["embedding"], args.top_k,
        )
        verdict, reason = verdict_for(fp_hits, ann, args.threshold_hard, args.threshold_soft)

        fp_match_ids = {h["question_id"] for h in fp_hits}
        results.append({
            "input_index": r["input_index"],
            "input_id": r.get("input_id"),
            "input": {
                "subject_id": r["subject_id"],
                "subject_name": subj_names.get(r["subject_id"]),
                "question_year": r.get("question_year"),
                "question_raw": r["question_raw"],
                "text_clean": r["text_clean"],
                "search_fingerprint": r["search_fingerprint"],
            },
            "verdict": verdict,
            "reason": reason,
            "fingerprint_matches": [
                {
                    "question_id": h["question_id"],
                    "question_year": h["question_year"],
                    "question_year_number": h.get("question_year_number"),
                    "text_clean": h["text_clean"],
                    "option_1": h.get("option_1"),
                    "option_2": h.get("option_2"),
                    "option_3": h.get("option_3"),
                    "option_4": h.get("option_4"),
                }
                for h in fp_hits
            ],
            "top_k": [
                {
                    "question_id": a["question_id"],
                    "cosine": float(a["cosine"]),
                    "question_year": a["question_year"],
                    "question_year_number": a.get("question_year_number"),
                    "text_clean": a["text_clean"],
                    "fingerprint_match": a["question_id"] in fp_match_ids,
                    "option_1": a.get("option_1"),
                    "option_2": a.get("option_2"),
                    "option_3": a.get("option_3"),
                    "option_4": a.get("option_4"),
                }
                for a in ann
            ],
        })
    print(f"  lookup time: {time.time() - t0:.1f}s")

    # Build summary.
    verdict_keys = ("REPEAT", "NEAR_HIGH", "NEAR", "NEW")
    summary = {"total": len(results), **{k: 0 for k in verdict_keys}, "by_subject": {}}
    for res in results:
        v = res["verdict"]
        summary[v] += 1
        sid = res["input"]["subject_id"]
        sname = res["input"].get("subject_name") or f"subject_{sid}"
        bucket = summary["by_subject"].setdefault(sname, {"total": 0, **{k: 0 for k in verdict_keys}})
        bucket["total"] += 1
        bucket[v] += 1

    report = {
        "meta": {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "embed_dims": EMBED_DIMS,
            "task_type": TASK_TYPE_QUERY,
            "thresholds": {"hard": args.threshold_hard, "soft": args.threshold_soft},
            "top_k": args.top_k,
            "source": "self-test" if args.self_test else str(args.input),
        },
        "summary": summary,
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # Console summary.
    print()
    print(f"Total: {summary['total']}   |  REPEAT: {summary['REPEAT']}  "
          f"NEAR_HIGH: {summary['NEAR_HIGH']}  NEAR: {summary['NEAR']}  NEW: {summary['NEW']}")
    if summary["by_subject"]:
        print("By subject:")
        for sname, b in sorted(summary["by_subject"].items()):
            print(f"  {sname:<28} total={b['total']:>3}  REPEAT={b['REPEAT']:>3}  "
                  f"NEAR_HIGH={b['NEAR_HIGH']:>3}  NEAR={b['NEAR']:>3}  NEW={b['NEW']:>3}")
    print(f"\nReport: {output_path}")

    # Self-test sanity: top-1 should be SELF or a fingerprint twin (corpus
    # duplicate). DOC/QUERY task-type asymmetry caps same-text cosines at
    # ~0.92, so don't flag cosine < 0.95. See [[calibration-findings]].
    if args.self_test:
        not_self_or_fp = 0
        for res in results:
            if not res["top_k"]:
                continue
            top1 = res["top_k"][0]
            if res["input_id"] is None:
                continue
            is_self = top1["question_id"] == res["input_id"]
            is_fp_twin = any(fm["question_id"] == top1["question_id"] for fm in res["fingerprint_matches"])
            if not (is_self or is_fp_twin):
                not_self_or_fp += 1
        print(f"\nSelf-test sanity:")
        print(f"  top-1 is neither SELF nor a fingerprint twin: {not_self_or_fp} of {len(results)}  (a few are expected — adjacent / topically-similar questions)")

    conn.close()


if __name__ == "__main__":
    main()
