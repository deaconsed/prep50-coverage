"""Convert a WAEC objective-paper DOCX to a Prep50-ready CSV.

Each paragraph in the source DOCX is expected to be one complete question:

    <stem> A. <opt1> B. <opt2> C. <opt3> D. <opt4>[.] [YYYY/N]

Output CSV columns: question, question_year, option_1, option_2, option_3,
option_4, short_answer. short_answer is left blank (the original DOCX doesn't
carry it); question_year defaults to whatever --year says (2026 unless overridden).

Usage:
    python scripts/docx_to_csv.py --input "WAEC CRS OBJ (2).docx" --out crs_2026.csv
    python scripts/docx_to_csv.py --input paper.docx --out paper.csv --year 2026
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from docx import Document

# One regex matches the whole question. `(?P<stem>.+?)` is non-greedy and
# bounded by the next required `\s+A\.\s+`, so each option capture stops at
# the next option marker. The final `\[YYYY/N\]` tail is required, so noise
# paragraphs (page headers, instructions) get skipped silently.
QUESTION_RE = re.compile(
    r"""^
        (?P<stem>.+?)
        \s+A\.\s+(?P<a>.+?)
        \s+B\.\s+(?P<b>.+?)
        \s+C\.\s+(?P<c>.+?)
        \s+D\.\s+(?P<d>.+?)
        \s*\[\d{4}/\d+\]\s*$
    """,
    re.VERBOSE | re.DOTALL,
)


def clean_text(s: str) -> str:
    """Collapse whitespace, strip stray leading punctuation, normalize quotes."""
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[.\s]+", "", s)               # leading "." or whitespace
    s = re.sub(r"\s+([.,;:?!])", r"\1", s)      # " ?" → "?"
    return s


def clean_option(s: str) -> str:
    """Same as clean_text plus drop a trailing terminal punctuation if any."""
    s = clean_text(s)
    s = re.sub(r"[.,;:]+$", "", s).strip()
    return s


def parse_paragraph(text: str) -> dict | None:
    m = QUESTION_RE.match(text)
    if not m:
        return None
    g = m.groupdict()
    return {
        "question": clean_text(g["stem"]),
        "option_1": clean_option(g["a"]),
        "option_2": clean_option(g["b"]),
        "option_3": clean_option(g["c"]),
        "option_4": clean_option(g["d"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path, help="DOCX file to read.")
    ap.add_argument("--out", required=True, type=Path, help="Output CSV path.")
    ap.add_argument("--year", type=int, default=2026,
                    help="question_year for every row (default 2026).")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    doc = Document(str(args.input))
    parsed: list[dict] = []
    skipped: list[tuple[int, str]] = []

    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text:
            continue
        row = parse_paragraph(text)
        if row is None:
            skipped.append((i, text[:90]))
            continue
        row["question_year"] = args.year
        row["short_answer"] = ""
        parsed.append(row)

    print(f"Parsed {len(parsed)} questions.")
    if skipped:
        print(f"Skipped {len(skipped)} paragraph(s) that didn't match:")
        for i, sample in skipped[:5]:
            print(f"  [{i}] {sample!r}…")
        if len(skipped) > 5:
            print(f"  …and {len(skipped) - 5} more")

    cols = [
        "question", "question_year",
        "option_1", "option_2", "option_3", "option_4",
        "short_answer",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig writes a BOM so Excel opens the CSV without mangling smart quotes.
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in parsed:
            w.writerow(row)
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
