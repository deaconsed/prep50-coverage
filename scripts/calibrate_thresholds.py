"""calibrate_thresholds.py — empirically determine REPEAT / NEAR cosine cutoffs.

Method:
    1. Sample N random questions that already have embeddings (the "queries").
    2. Re-embed each with task_type=RETRIEVAL_QUERY (mirrors check_duplicates).
    3. Run the same top-K ANN lookup the detector uses (same subject, W/JW).
    4. Categorize every (query, returned_match) pair by relationship:
         SELF      -> returned question_id == query question_id
         FP_MATCH  -> different id, same search_fingerprint (corpus duplicate)
         OTHER     -> different id, different fingerprint (a genuinely different question)
    5. Report cosine distributions per category and recommend thresholds.

Read-only. No DB writes. ~ N + (N*K) Vertex calls; with defaults (N=100, K=5)
that's a few hundred embed calls and ~ N database round-trips for lookups.

Usage:
    python scripts/calibrate_thresholds.py
    python scripts/calibrate_thresholds.py --n 200 --top-k 10
    python scripts/calibrate_thresholds.py --subject 10   # Physics only
"""
import argparse
import json
import os
import statistics
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

EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"
MODEL_NAME = "text-embedding-005"
MODEL_VERSION = "vertex-v1"
EMBED_BATCH = 50

OUT_DIR = ROOT / "test_data"


def connect_pg():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "15433")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "prep50"),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )


def init_client():
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return genai.Client(vertexai=True, project=project, location=location, credentials=creds)


def vector_to_pg(vec):
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


SAMPLE_SQL = """
    SELECT q.id, q.subject_id, s.name AS subject_name, q.question,
           qe.search_fingerprint AS stored_fp
    FROM questions q
    JOIN question_embeddings qe
      ON qe.question_id = q.id
     AND qe.model_name = %s AND qe.model_version = %s
    JOIN subjects s ON s.id = q.subject_id
    WHERE q.tag IN ('W','JW')
      AND q.question IS NOT NULL AND q.question <> ''
      {subj_clause}
    ORDER BY random()
    LIMIT %s
"""

ANN_SQL = """
    SELECT qe.question_id, qe.search_fingerprint,
           1 - (qe.embedding <=> %s::vector) AS cosine
    FROM question_embeddings qe
    WHERE qe.subject_id = %s
      AND qe.tag IN ('W','JW')
      AND qe.model_name = %s AND qe.model_version = %s
    ORDER BY qe.embedding <=> %s::vector
    LIMIT %s
"""


def fetch_sample(conn, n, subject_id=None):
    subj_clause = "AND q.subject_id = %s" if subject_id else ""
    sql = SAMPLE_SQL.format(subj_clause=subj_clause)
    params = [MODEL_NAME, MODEL_VERSION]
    if subject_id:
        params.append(subject_id)
    params.append(n)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def embed_queries(client, texts):
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=list(texts),
        config=types.EmbedContentConfig(
            task_type=TASK_TYPE_QUERY,
            output_dimensionality=EMBED_DIMS,
        ),
    )
    return [e.values for e in resp.embeddings]


def percentiles(xs, qs=(0, 5, 10, 25, 50, 75, 90, 95, 100)):
    if not xs:
        return {q: None for q in qs}
    xs_sorted = sorted(xs)
    n = len(xs_sorted)
    out = {}
    for q in qs:
        if q == 0:
            out[q] = xs_sorted[0]
        elif q == 100:
            out[q] = xs_sorted[-1]
        else:
            idx = int(round((q / 100) * (n - 1)))
            out[q] = xs_sorted[idx]
    return out


def fmt_dist(label, values):
    if not values:
        print(f"  {label:<10} n=0")
        return
    p = percentiles(values)
    print(f"  {label:<10} n={len(values):>4}  min={p[0]:.4f}  p10={p[10]:.4f}  p25={p[25]:.4f}  "
          f"median={p[50]:.4f}  p75={p[75]:.4f}  p90={p[90]:.4f}  max={p[100]:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100, help="Sample size (default 100).")
    ap.add_argument("--top-k", type=int, default=5, help="Top-K per query (default 5).")
    ap.add_argument("--subject", type=int, help="Restrict to one subject.")
    ap.add_argument("--output", type=Path, help="JSON output path.")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    output_path = args.output or (OUT_DIR / f"calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    print("Connecting to database...")
    conn = connect_pg()
    print(f"  host={os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}  db={os.getenv('DB_NAME')}")

    print(f"Sampling {args.n} embedded questions{' (subject ' + str(args.subject) + ')' if args.subject else ''}...")
    sample = fetch_sample(conn, args.n, args.subject)
    print(f"  got {len(sample)} questions.")

    # Re-embed as queries (these get the QUERY task_type, mirroring real dup-check).
    print(f"Embedding {len(sample)} queries via Vertex AI (task={TASK_TYPE_QUERY})...")
    client = init_client()
    texts = [to_clean(s["question"]) for s in sample]
    t0 = time.time()
    query_vecs = []
    for batch_texts in chunked(texts, EMBED_BATCH):
        query_vecs.extend(embed_queries(client, batch_texts))
    print(f"  embed time: {time.time() - t0:.1f}s")

    # For each query: run top-K, classify each match.
    print(f"Running top-{args.top_k} lookups for each query...")
    self_cos, fp_match_cos, other_cos = [], [], []
    top1_self_cos, top1_fp_cos, top1_other_cos = [], [], []
    per_query = []
    t0 = time.time()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for s, q_vec in zip(sample, query_vecs):
            emb_pg = vector_to_pg(q_vec)
            cur.execute(ANN_SQL, (emb_pg, s["subject_id"], MODEL_NAME, MODEL_VERSION, emb_pg, args.top_k))
            matches = cur.fetchall()
            classified = []
            for m in matches:
                if m["question_id"] == s["id"]:
                    cat = "SELF"
                elif m["search_fingerprint"] and m["search_fingerprint"] == s["stored_fp"]:
                    cat = "FP_MATCH"
                else:
                    cat = "OTHER"
                cos = float(m["cosine"])
                classified.append({"question_id": m["question_id"], "category": cat, "cosine": cos})
                if cat == "SELF":
                    self_cos.append(cos)
                elif cat == "FP_MATCH":
                    fp_match_cos.append(cos)
                else:
                    other_cos.append(cos)
            if classified:
                top = classified[0]
                if top["category"] == "SELF":
                    top1_self_cos.append(top["cosine"])
                elif top["category"] == "FP_MATCH":
                    top1_fp_cos.append(top["cosine"])
                else:
                    top1_other_cos.append(top["cosine"])
            per_query.append({
                "query_id": s["id"],
                "subject_id": s["subject_id"],
                "subject_name": s["subject_name"],
                "matches": classified,
            })
    print(f"  lookup time: {time.time() - t0:.1f}s")

    # --- Report -----------------------------------------------------------
    print()
    print("=== Cosine distributions across ALL top-K results ===")
    fmt_dist("SELF", self_cos)
    fmt_dist("FP_MATCH", fp_match_cos)
    fmt_dist("OTHER", other_cos)

    print()
    print("=== Cosine distributions for TOP-1 only (most operationally relevant) ===")
    fmt_dist("SELF", top1_self_cos)
    fmt_dist("FP_MATCH", top1_fp_cos)
    fmt_dist("OTHER", top1_other_cos)

    # --- Recommend thresholds --------------------------------------------
    # We want HARD to capture nearly all SELF/FP_MATCH (true repeats) while
    # excluding nearly all OTHER. SOFT widens the net for human review.
    repeat_cos = self_cos + fp_match_cos
    if repeat_cos and other_cos:
        repeat_p = percentiles(repeat_cos, qs=(5, 10, 25, 50))
        other_p = percentiles(other_cos, qs=(50, 75, 90, 95, 99, 100))
        # HARD: just below the 5th percentile of repeats so we catch ~95% of true repeats.
        # SOFT: just above the 95th percentile of OTHER so we don't drown reviewers in noise.
        hard_recommended = round(repeat_p[5] - 0.005, 3)
        soft_recommended = round(max(other_p[95], hard_recommended - 0.10), 3)

        print()
        print("=== Threshold recommendation (data-driven) ===")
        print(f"  REPEAT cosines: 5th percentile = {repeat_p[5]:.4f}  median = {repeat_p[50]:.4f}")
        print(f"  OTHER  cosines: 95th percentile = {other_p[95]:.4f}  99th = {other_p[99]:.4f}  max = {other_p[100]:.4f}")
        print(f"  -> THRESHOLD_HARD = {hard_recommended:.3f}  (catches ~95% of true repeats)")
        print(f"  -> THRESHOLD_SOFT = {soft_recommended:.3f}  (above 95% of OTHER noise)")

        gap = repeat_p[5] - other_p[95]
        print(f"  margin between distributions (repeat_p5 - other_p95) = {gap:+.4f}")
        if gap < 0:
            print("  !!  WARNING: REPEAT and OTHER cosine ranges OVERLAP — no clean threshold can")
            print("      separate them perfectly. Manual review of NEAR-range candidates is essential.")
    else:
        hard_recommended = soft_recommended = None
        print("\nNot enough data to recommend thresholds.")

    # --- Persist ---------------------------------------------------------
    report = {
        "meta": {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "n_queries": len(sample),
            "top_k": args.top_k,
            "subject_filter": args.subject,
            "task_type_query": TASK_TYPE_QUERY,
        },
        "stats": {
            "all_topk": {
                "SELF": percentiles(self_cos),
                "FP_MATCH": percentiles(fp_match_cos),
                "OTHER": percentiles(other_cos),
            },
            "top1": {
                "SELF": percentiles(top1_self_cos),
                "FP_MATCH": percentiles(top1_fp_cos),
                "OTHER": percentiles(top1_other_cos),
            },
        },
        "recommended_thresholds": {
            "hard": hard_recommended,
            "soft": soft_recommended,
        },
        "per_query": per_query,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nReport: {output_path}")

    conn.close()


if __name__ == "__main__":
    main()
