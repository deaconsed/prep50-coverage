"""score_synthetic_test.py — compare detector output to expected verdicts.

Joins the synthetic-test CSV (with expected_verdict per row) against the
JSON report from check_duplicates.py. Prints:
    - Per-perturbation accuracy (expected vs actual verdict)
    - Confusion matrix (expected x actual)
    - Failing rows: which inputs got the wrong verdict and what the top match was
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERDICT_ORDER = ["REPEAT", "NEAR_HIGH", "NEAR", "NEW"]


def load_csv(path):
    """input_id (string) -> {expected_verdict, perturbation, source_question_id}."""
    out = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out[r["id"]] = {
                "expected_verdict": r["expected_verdict"],
                "perturbation": r["perturbation"],
                "source_question_id": int(r["source_question_id"]),
                "subject_id": int(r["subject_id"]),
            }
    return out


def load_json(path):
    """input_id (string) -> {verdict, top1, fingerprint_matches, ...}."""
    data = json.load(open(path, encoding="utf-8"))
    out = {}
    for r in data["results"]:
        # check_duplicates wrote input_id as whatever was in the csv `id` column.
        out[str(r["input_id"])] = {
            "verdict": r["verdict"],
            "reason": r["reason"],
            "top1_id": r["top_k"][0]["question_id"] if r["top_k"] else None,
            "top1_cos": r["top_k"][0]["cosine"] if r["top_k"] else None,
            "fp_match_ids": [h["question_id"] for h in r["fingerprint_matches"]],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True, help="Synthetic test CSV.")
    ap.add_argument("--json", type=Path, required=True, help="check_duplicates JSON report.")
    ap.add_argument("--show-failures", type=int, default=15, help="Max failure rows to print (default 15).")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    expected = load_csv(args.csv)
    actual = load_json(args.json)

    missing = set(expected.keys()) - set(actual.keys())
    if missing:
        print(f"WARNING: {len(missing)} rows in CSV but not in JSON report.")

    # --- Per-perturbation accuracy ---
    per_pert = defaultdict(lambda: {"correct": 0, "total": 0, "wrong": []})
    for k, exp in expected.items():
        if k not in actual:
            continue
        act = actual[k]
        per_pert[exp["perturbation"]]["total"] += 1
        if act["verdict"] == exp["expected_verdict"]:
            per_pert[exp["perturbation"]]["correct"] += 1
        else:
            per_pert[exp["perturbation"]]["wrong"].append({
                "input_id": k,
                "source_id": exp["source_question_id"],
                "expected": exp["expected_verdict"],
                "actual": act["verdict"],
                "top1_id": act["top1_id"],
                "top1_cos": act["top1_cos"],
                "fp_hit": exp["source_question_id"] in act["fp_match_ids"],
                "reason": act["reason"],
            })

    print("=== Per-perturbation accuracy ===")
    print(f"{'perturbation':<22} {'correct':>8} {'total':>6} {'pct':>6}  expected")
    overall_correct = 0
    overall_total = 0
    for pert, d in per_pert.items():
        pct = (100 * d["correct"] / d["total"]) if d["total"] else 0
        exp_v = expected[next(k for k, v in expected.items() if v["perturbation"] == pert)]["expected_verdict"]
        print(f"{pert:<22} {d['correct']:>8} {d['total']:>6} {pct:>5.0f}%  {exp_v}")
        overall_correct += d["correct"]
        overall_total += d["total"]
    overall_pct = (100 * overall_correct / overall_total) if overall_total else 0
    print(f"{'OVERALL':<22} {overall_correct:>8} {overall_total:>6} {overall_pct:>5.0f}%")

    # --- Confusion matrix ---
    cm = defaultdict(Counter)
    for k, exp in expected.items():
        if k not in actual:
            continue
        cm[exp["expected_verdict"]][actual[k]["verdict"]] += 1

    print("\n=== Confusion matrix (rows=expected, cols=actual) ===")
    header = f"{'expected\\actual':<14}" + "".join(f"{v:>11}" for v in VERDICT_ORDER) + f"{'  total':>8}"
    print(header)
    for exp_v in VERDICT_ORDER:
        row = [exp_v.ljust(14)]
        total = 0
        for act_v in VERDICT_ORDER:
            n = cm[exp_v][act_v]
            total += n
            row.append(f"{n:>11}")
        row.append(f"{total:>8}")
        print("".join(row))

    # --- Failure inspection ---
    print(f"\n=== Failures (up to {args.show_failures}) ===")
    fails = []
    for pert, d in per_pert.items():
        for w in d["wrong"]:
            fails.append((pert, w))
    if not fails:
        print("  (none — every row got the expected verdict)")
    else:
        print(f"  {len(fails)} total failures.")
        for pert, w in fails[: args.show_failures]:
            fp_str = "fp_hit=YES" if w["fp_hit"] else "fp_hit=no"
            cos = f"{w['top1_cos']:.4f}" if w["top1_cos"] is not None else "n/a"
            print(f"  [{pert}] src={w['source_id']} expected={w['expected']:<9} got={w['actual']:<9}  "
                  f"top1=q{w['top1_id']} cos={cos}  {fp_str}")


if __name__ == "__main__":
    main()
