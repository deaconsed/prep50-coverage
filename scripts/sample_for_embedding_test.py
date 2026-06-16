"""Sample N classified W/JW questions per subject from the local Docker
Postgres mirror, normalize them, generate Gemini text-embedding-005 vectors,
and dump to disk.

Used as a dry-run sanity check before backfilling the full corpus.

Output:
    test_data/embedding_sample.jsonl   - one JSON line per question, embedding as list
    test_data/embedding_sample.csv     - same data, embedding as JSON-encoded string

Usage:
    python scripts/sample_for_embedding_test.py                # 20 per subject
    python scripts/sample_for_embedding_test.py --per 10
    python scripts/sample_for_embedding_test.py --subject 10   # only Physics (prod id)
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2 import service_account
from tqdm import tqdm

# Make normalize.py importable when running from scripts/ subdir.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from normalize import to_clean, to_fingerprint  # noqa: E402

load_dotenv()

OUT_DIR = ROOT / "test_data"
JSONL_PATH = OUT_DIR / "embedding_sample.jsonl"
CSV_PATH = OUT_DIR / "embedding_sample.csv"

EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
EMBED_BATCH = 50   # Vertex allows up to 250 inputs; 50 is a safe middle ground.
TASK_TYPE = "RETRIEVAL_DOCUMENT"


def connect_pg():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "prep50"),
    )


def init_embedding_client():
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


def fetch_wjw_subjects(conn, only_subject_id=None):
    sql = """
        SELECT id, name, tag
        FROM subjects
        WHERE tag IN ('W', 'JW')
    """
    params = []
    if only_subject_id is not None:
        sql += " AND id = %s"
        params.append(only_subject_id)
    sql += " ORDER BY name"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_sample(conn, subject_id, n):
    """Random sample of classified W/JW questions in a subject.

    "Classified" = has at least one row in objective_questions.
    """
    sql = """
        SELECT q.id, q.subject_id, q.tag, q.question_year, q.question_year_number,
               q.question, q.option_1, q.option_2, q.option_3, q.option_4,
               q.short_answer,
               (SELECT oq.objective_id FROM objective_questions oq
                WHERE oq.question_id = q.id LIMIT 1) AS objective_id
        FROM questions q
        WHERE q.subject_id = %s
          AND q.tag IN ('W', 'JW')
          AND q.question IS NOT NULL AND q.question <> ''
          AND EXISTS (SELECT 1 FROM objective_questions oq WHERE oq.question_id = q.id)
        ORDER BY random()
        LIMIT %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (subject_id, n))
        return cur.fetchall()


def embed_texts(client, texts):
    """Embed up to EMBED_BATCH texts in one Vertex call. Returns list of float lists."""
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=list(texts),
        config=types.EmbedContentConfig(
            task_type=TASK_TYPE,
            output_dimensionality=EMBED_DIMS,
        ),
    )
    return [e.values for e in resp.embeddings]


def chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=20, help="Questions per subject (default 20).")
    ap.add_argument("--subject", type=int, help="Only this Postgres subject_id.")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    conn = connect_pg()
    rows = []
    try:
        subjects = fetch_wjw_subjects(conn, only_subject_id=args.subject)
        if not subjects:
            sys.exit("No W/JW subjects matched. Check --subject value.")
        print(f"Sampling up to {args.per} questions per subject from {len(subjects)} subjects...")
        for s in subjects:
            subset = fetch_sample(conn, s["id"], args.per)
            for r in subset:
                r["subject_name"] = s["name"]
            rows.extend(subset)
            print(f"  {s['name']:<28} -> {len(subset)} sampled")
    finally:
        conn.close()

    if not rows:
        sys.exit("No questions sampled. Check that classification has run for selected subjects.")

    print(f"\nNormalizing {len(rows)} questions...")
    for r in rows:
        r["text_clean"] = to_clean(r["question"])
        r["search_fingerprint"] = to_fingerprint(r["text_clean"])

    print(f"Embedding {len(rows)} questions via Vertex AI ({EMBED_MODEL})...")
    client = init_embedding_client()
    t0 = time.time()
    for batch in tqdm(list(chunked(rows, EMBED_BATCH)), desc="embedding"):
        vectors = embed_texts(client, [r["text_clean"] for r in batch])
        for r, v in zip(batch, vectors):
            r["embedding"] = v
    print(f"  embed time: {time.time() - t0:.1f}s for {len(rows)} questions")

    # JSONL output (preferred)
    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            out = {
                "question_id": r["id"],
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"],
                "tag": r["tag"],
                "objective_id": r.get("objective_id"),
                "question_year": r.get("question_year"),
                "question_year_number": r.get("question_year_number"),
                "question_raw": r["question"],
                "text_clean": r["text_clean"],
                "search_fingerprint": r["search_fingerprint"],
                "options": [r.get("option_1"), r.get("option_2"), r.get("option_3"), r.get("option_4")],
                "short_answer": r.get("short_answer"),
                "embedding": r["embedding"],
            }
            f.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")

    # CSV output (embedding as JSON-encoded string column)
    csv_cols = [
        "question_id", "subject_id", "subject_name", "tag", "objective_id",
        "question_year", "question_year_number",
        "text_clean", "search_fingerprint", "embedding",
    ]
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({
                "question_id": r["id"],
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"],
                "tag": str(r["tag"]),
                "objective_id": r.get("objective_id") or "",
                "question_year": r.get("question_year") or "",
                "question_year_number": r.get("question_year_number") or "",
                "text_clean": r["text_clean"],
                "search_fingerprint": r["search_fingerprint"],
                "embedding": json.dumps(r["embedding"]),
            })

    print(f"\nWrote {len(rows)} rows to:")
    print(f"  {JSONL_PATH}  (~{JSONL_PATH.stat().st_size // 1024} KB)")
    print(f"  {CSV_PATH}    (~{CSV_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
