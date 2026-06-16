"""make_synthetic_test_csv.py — build a stress-test fixture for check_duplicates.

For each of N source questions sampled from the embedded corpus, emit several
deterministic perturbations plus a cross-subject "should be NEW" control.
Output CSV is consumable by check_duplicates.py (has subject_id + question
columns), with extra metadata columns the scorer reads later:
    expected_verdict, perturbation, source_question_id

Reproducible: --seed pins the RNG so re-running gives the same fixture.

Why deterministic perturbations instead of LLM paraphrases:
    - LLM paraphrases are non-reproducible (results vary across calls).
    - We want to know *exactly* what we mutated to interpret detector
      outputs. "stem_swap broke the fingerprint" is more diagnostic than
      "the paraphrase scored 0.83 for unknown reasons."

Perturbation -> expected_verdict (rationale):
    identical              REPEAT     same text, fingerprint matches
    case_change            REPEAT     to_fingerprint lowercases
    whitespace             REPEAT     to_clean collapses whitespace
    html_wrap              REPEAT     to_clean strips HTML
    punctuation_strip      REPEAT     fingerprint also strips punctuation
    stem_swap              REPEAT     [STEM_VALUE_OF] absorbs Find/Calculate/Determine
    typo_swap              NEAR_HIGH  fp breaks; cosine should remain very high
    typo_delete            NEAR_HIGH
    prefix_filler          NEAR_HIGH  prepended noise breaks fp; cosine high
    suffix_filler          NEAR_HIGH
    truncate_first_half    NEAR       substantive content removed
    cross_subject          NEW        different content, labeled with original's subject

Usage:
    python scripts/make_synthetic_test_csv.py --n 10
    python scripts/make_synthetic_test_csv.py --n 5 --subject 10 --seed 7
"""
import argparse
import csv
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from normalize import to_clean  # noqa: E402

load_dotenv()

OUT_DIR = ROOT / "test_data"

PERTURBATIONS = [
    "identical", "case_change", "whitespace", "html_wrap", "punctuation_strip",
    "stem_swap", "typo_swap", "typo_delete", "prefix_filler", "suffix_filler",
    "truncate_first_half",
]

EXPECTED = {
    "identical": "REPEAT",
    "case_change": "REPEAT",
    "whitespace": "REPEAT",
    "html_wrap": "REPEAT",
    "punctuation_strip": "REPEAT",
    "stem_swap": "REPEAT",
    "typo_swap": "NEAR_HIGH",
    "typo_delete": "NEAR_HIGH",
    "prefix_filler": "NEAR_HIGH",
    "suffix_filler": "NEAR_HIGH",
    "truncate_first_half": "NEAR",
    "cross_subject": "NEW",
}


def connect_pg():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME"),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )


def fetch_sources(conn, n, subject_id=None):
    """Sample N embedded W/JW questions with reasonably substantive text."""
    sql = """
        SELECT q.id, q.subject_id, q.question
        FROM questions q
        JOIN question_embeddings qe
          ON qe.question_id = q.id
         AND qe.model_name = 'text-embedding-005' AND qe.model_version = 'vertex-v1'
        WHERE q.tag IN ('W','JW')
          AND q.question IS NOT NULL
          AND length(q.question) BETWEEN 60 AND 500
          {subj}
        ORDER BY random()
        LIMIT %s
    """.format(subj="AND q.subject_id = %s" if subject_id else "")
    params = [subject_id, n] if subject_id else [n]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_cross_subject_questions(conn, exclude_subject_ids, n):
    """For the NEW control: pick questions from a different subject."""
    sql = """
        SELECT q.id, q.subject_id, q.question
        FROM questions q
        JOIN question_embeddings qe
          ON qe.question_id = q.id
         AND qe.model_name = 'text-embedding-005' AND qe.model_version = 'vertex-v1'
        WHERE q.tag IN ('W','JW')
          AND q.question IS NOT NULL
          AND length(q.question) BETWEEN 60 AND 500
          AND NOT q.subject_id = ANY(%s)
        ORDER BY random()
        LIMIT %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (list(exclude_subject_ids), n))
        return cur.fetchall()


# ---- perturbations -------------------------------------------------------

def p_identical(text, rng):
    return text


def p_case_change(text, rng):
    return text.upper()


def p_whitespace(text, rng):
    return re.sub(r"\s", "    ", text)  # quadruple every whitespace


def p_html_wrap(text, rng):
    # Already HTML-source, but add nested redundant tags.
    return f"<div><p><strong>{text}</strong></p></div>"


def p_punctuation_strip(text, rng):
    return re.sub(r"[^\w\s]", "", text)


_STEM_SWAPS = [
    (r"\bfind\s+the\s+value\s+of\b", "calculate the value of"),
    (r"\bcalculate\s+the\s+value\s+of\b", "determine the value of"),
    (r"\bdetermine\s+the\s+value\s+of\b", "find the value of"),
    (r"\bwhich\s+of\s+the\s+following\b", "what of the following"),
    (r"\bwhat\s+of\s+the\s+following\b", "which of the following"),
    (r"\bif\s+", "suppose "),
]


def p_stem_swap(text, rng):
    for pat, repl in _STEM_SWAPS:
        if re.search(pat, text, flags=re.I):
            return re.sub(pat, repl, text, count=1, flags=re.I)
    # No stem matched — return None to signal "skip this perturbation".
    return None


def _word_positions(text):
    """Index of (start, end) for each alphabetic token >= length 4."""
    return [(m.start(), m.end()) for m in re.finditer(r"[A-Za-z]{4,}", to_clean(text))]


def p_typo_swap(text, rng):
    clean = to_clean(text)
    positions = _word_positions(text)
    if not positions:
        return None
    s, e = rng.choice(positions)
    word = clean[s:e]
    if len(word) < 4:
        return None
    p = rng.randint(1, len(word) - 2)
    new_word = word[:p] + word[p + 1] + word[p] + word[p + 2:]
    return clean[:s] + new_word + clean[e:]


def p_typo_delete(text, rng):
    clean = to_clean(text)
    positions = _word_positions(text)
    if not positions:
        return None
    s, e = rng.choice(positions)
    word = clean[s:e]
    if len(word) < 5:
        return None
    p = rng.randint(1, len(word) - 2)
    new_word = word[:p] + word[p + 1:]
    return clean[:s] + new_word + clean[e:]


def p_prefix_filler(text, rng):
    return f"Note: please read carefully. {text}"


def p_suffix_filler(text, rng):
    return f"{text} Choose the best answer from the options."


def p_truncate_first_half(text, rng):
    clean = to_clean(text)
    if len(clean) < 30:
        return None
    return clean[: max(20, int(len(clean) * 0.6))]


PERT_FUNCS = {
    "identical": p_identical,
    "case_change": p_case_change,
    "whitespace": p_whitespace,
    "html_wrap": p_html_wrap,
    "punctuation_strip": p_punctuation_strip,
    "stem_swap": p_stem_swap,
    "typo_swap": p_typo_swap,
    "typo_delete": p_typo_delete,
    "prefix_filler": p_prefix_filler,
    "suffix_filler": p_suffix_filler,
    "truncate_first_half": p_truncate_first_half,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10,
                    help="Number of source questions to perturb (default 10).")
    ap.add_argument("--subject", type=int,
                    help="Optionally restrict source sampling to one subject_id.")
    ap.add_argument("--cross-n", type=int, default=5,
                    help="How many cross-subject NEW controls (default 5).")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for reproducible perturbations (default 42).")
    ap.add_argument("--output", type=Path,
                    help="CSV output path (default test_data/synthetic_test_<ts>.csv).")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    output_path = args.output or (OUT_DIR / f"synthetic_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    rng = random.Random(args.seed)

    print("Connecting to database...")
    conn = connect_pg()
    print(f"  host={os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}  db={os.getenv('DB_NAME')}")

    print(f"Sampling {args.n} source questions...")
    sources = fetch_sources(conn, args.n, args.subject)
    print(f"  got {len(sources)} sources.")

    print(f"Sampling {args.cross_n} cross-subject controls...")
    src_subj_ids = list({s["subject_id"] for s in sources})
    cross = fetch_cross_subject_questions(conn, src_subj_ids, args.cross_n)
    print(f"  got {len(cross)} cross-subject controls.")
    conn.close()

    rows = []
    next_id = 1
    skipped = 0

    for src in sources:
        src_text = src["question"]
        src_subj = src["subject_id"]
        src_id = src["id"]
        for pert in PERTURBATIONS:
            perturbed = PERT_FUNCS[pert](src_text, rng)
            if perturbed is None:
                skipped += 1
                continue
            rows.append({
                "id": next_id,
                "subject_id": src_subj,
                "question": perturbed,
                "expected_verdict": EXPECTED[pert],
                "perturbation": pert,
                "source_question_id": src_id,
            })
            next_id += 1

    # Cross-subject controls: take a question from a DIFFERENT subject,
    # but label it with a SOURCE subject_id so the detector searches a
    # subject where this question genuinely does not belong.
    src_subj_ids_iter = iter(src_subj_ids * (args.cross_n // max(1, len(src_subj_ids)) + 1))
    for c in cross:
        mislabel_subj = next(src_subj_ids_iter)
        rows.append({
            "id": next_id,
            "subject_id": mislabel_subj,
            "question": c["question"],
            "expected_verdict": EXPECTED["cross_subject"],
            "perturbation": "cross_subject",
            "source_question_id": c["id"],
        })
        next_id += 1

    fieldnames = ["id", "subject_id", "question", "expected_verdict", "perturbation", "source_question_id"]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} synthetic rows to:\n  {output_path}")
    if skipped:
        print(f"  ({skipped} perturbations skipped — source text not amenable, e.g. no stem to swap)")

    # Distribution summary.
    from collections import Counter
    counts = Counter(r["perturbation"] for r in rows)
    print("\nPerturbation counts:")
    for p in PERTURBATIONS + ["cross_subject"]:
        print(f"  {p:<22} {counts.get(p, 0):>3}  -> expected {EXPECTED[p]}")


if __name__ == "__main__":
    main()
