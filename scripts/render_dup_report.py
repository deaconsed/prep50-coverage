"""render_dup_report.py — turn a check_duplicates JSON report into a demo HTML page.

Reads the JSON produced by scripts/check_duplicates.py and emits a single
self-contained HTML file (inline CSS + JS, no external assets) that can be
opened from any browser, attached to an email, or printed to PDF.

Maps the 4 calibrated verdicts onto the boss's 3-bucket view:
    REPEAT                    -> "EXACT MATCH" pill (red)
    NEAR_HIGH | NEAR          -> "SIMILAR" pill (amber)
    NEW                       -> "NEW" pill (green)

The actual cosine score is shown alongside each row so a reviewer can still
distinguish NEAR_HIGH (>=0.80) from NEAR (>=0.75).

Each matched corpus question is rendered with its (year, Q-number) appended
in red italics per the boss spec.

Usage:
    python scripts/render_dup_report.py --json test_data/dup_check_20260605_142200.json
    python scripts/render_dup_report.py --json <path> --out test_data/report.html
"""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def display_status(verdict: str) -> tuple[str, str]:
    """Return (label, css_class)."""
    if verdict == "REPEAT":
        return "EXACT MATCH", "exact"
    if verdict in ("NEAR_HIGH", "NEAR"):
        return "SIMILAR", "similar"
    return "NEW", "new"


def primary_match(res: dict):
    """Pick the candidate to show as 'best match' for the row.

    REPEAT     -> fingerprint match (canonical exact)
    NEAR_HIGH/NEAR -> top_k[0]
    NEW        -> None
    """
    if res["verdict"] == "REPEAT" and res["fingerprint_matches"]:
        m = res["fingerprint_matches"][0]
        return {**m, "_kind": "fingerprint", "cosine": 1.0}
    if res["top_k"]:
        return {**res["top_k"][0], "_kind": "cosine"}
    return None


def esc(s) -> str:
    if s is None:
        return ""
    return html.escape(str(s))


def render_options(opts) -> str:
    items = [o for o in opts if o]
    if not items:
        return ""
    li = "".join(f"<li>{esc(o)}</li>" for o in items)
    return f"<div class='options'><ol>{li}</ol></div>"


def render_year_meta(year, q_num) -> str:
    """The boss's red-italic year/number tag after a corpus question."""
    if year is None and q_num is None:
        return ""
    if year and q_num:
        txt = f"({year}, Q{q_num})"
    elif year:
        txt = f"({year})"
    else:
        txt = f"(Q{q_num})"
    return f" <span class='qmeta'>{esc(txt)}</span>"


def render_match_card(label: str, text: str, opts: list, year=None, q_num=None) -> str:
    return (
        f"<div class='qcard'>"
        f"<h3>{esc(label)}</h3>"
        f"<div class='qtext'>{esc(text)}{render_year_meta(year, q_num)}</div>"
        f"{render_options(opts)}"
        f"</div>"
    )


def render_empty_card(label: str, message: str) -> str:
    return (
        f"<div class='qcard empty'>"
        f"<h3>{esc(label)}</h3>"
        f"<div class='qtext'>{esc(message)}</div>"
        f"</div>"
    )


def render_other_candidates(top_k_rest) -> str:
    if not top_k_rest:
        return ""
    rows = []
    for c in top_k_rest:
        year_lbl = ""
        if c.get("question_year") or c.get("question_year_number"):
            year = c.get("question_year") or "—"
            q_num = c.get("question_year_number")
            year_lbl = f"({year}, Q{q_num})" if q_num else f"({year})"
        snippet = (c.get("text_clean") or "").strip()
        if len(snippet) > 180:
            snippet = snippet[:177] + "…"
        rows.append(
            f"<li>"
            f"<span class='other-score'>{c['cosine']:.3f}</span> "
            f"<span class='qmeta'>{esc(year_lbl)}</span> "
            f"<span class='other-text'>{esc(snippet)}</span>"
            f"</li>"
        )
    return f"<div class='others'><h4>Other candidates</h4><ul>{''.join(rows)}</ul></div>"


def render(report: dict, out_path: Path):
    results = report["results"]
    meta = report["meta"]
    summary = report["summary"]

    # Subject for the page header — if all results share a subject, name it.
    subjects = {r["input"].get("subject_name") for r in results if r["input"].get("subject_name")}
    if len(subjects) == 1:
        subject_label = next(iter(subjects))
    else:
        subject_label = f"{len(subjects)} subjects"

    n_total = summary["total"]
    n_exact = summary.get("REPEAT", 0)
    n_similar = summary.get("NEAR_HIGH", 0) + summary.get("NEAR", 0)
    n_new = summary.get("NEW", 0)

    # Compute elapsed if not in meta.
    elapsed_str = ""
    if "duration_seconds" in meta:
        elapsed_str = f" in {float(meta['duration_seconds']):.1f}s"

    row_blocks = []
    for i, r in enumerate(results, start=1):
        verdict = r["verdict"]
        status_label, status_cls = display_status(verdict)
        new_q = r["input"]["question_raw"]
        primary = primary_match(r)

        preview = (r["input"].get("text_clean") or new_q or "").strip()
        if len(preview) > 130:
            preview = preview[:127] + "…"

        if primary:
            year = primary.get("question_year")
            q_num = primary.get("question_year_number")
            if year and q_num:
                best_match_lbl = f"{year}, Q{q_num}"
            elif year:
                best_match_lbl = f"{year}"
            else:
                best_match_lbl = "—"
            score = primary.get("cosine")
            score_txt = "exact" if primary["_kind"] == "fingerprint" else f"{score:.3f}"
        else:
            best_match_lbl = "—"
            score_txt = "—"

        row_blocks.append(
            f"<tr class='row-summary' data-row-id='{i}'>"
            f"<td>{i}</td>"
            f"<td>{esc(preview)}</td>"
            f"<td><span class='pill {status_cls}'>{esc(status_label)}</span></td>"
            f"<td>{esc(best_match_lbl)}</td>"
            f"<td class='score-cell'>{esc(score_txt)}</td>"
            f"</tr>"
        )

        # Detail row — only render if there's something to show or for NEW.
        new_card = render_match_card("New question", new_q, [])
        if primary:
            opts = [primary.get("option_1"), primary.get("option_2"),
                    primary.get("option_3"), primary.get("option_4")]
            match_card = render_match_card(
                "Best match in corpus",
                primary.get("text_clean") or "",
                opts,
                year=primary.get("question_year"),
                q_num=primary.get("question_year_number"),
            )
            if primary["_kind"] == "fingerprint":
                score_note = (
                    "Exact fingerprint match — same canonical template after "
                    "normalization. " + esc(r.get("reason", ""))
                )
            else:
                score_note = (
                    f"Cosine similarity: {primary['cosine']:.3f}. "
                    f"{esc(r.get('reason', ''))}"
                )
        else:
            match_card = render_empty_card(
                "Best match in corpus",
                "No candidate above similarity threshold — this question appears new.",
            )
            score_note = esc(r.get("reason", ""))

        # Other candidates: top_k[1:] when we have one, OR all of top_k when
        # the primary is a fingerprint match (we still want to see ANN runners).
        if primary and primary["_kind"] == "cosine":
            others = r.get("top_k", [])[1:]
        else:
            others = r.get("top_k", [])

        row_blocks.append(
            f"<tr class='row-detail' data-detail-for='{i}'>"
            f"<td colspan='5'>"
            f"<div class='detail-grid'>"
            f"{new_card}{match_card}"
            f"<div class='score-note'>{score_note}</div>"
            f"</div>"
            f"{render_other_candidates(others)}"
            f"</td>"
            f"</tr>"
        )

    rows_html = "\n".join(row_blocks)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_at = meta.get("run_at", "")
    source = meta.get("source", "")

    css = """
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
       max-width: 1180px; margin: 0 auto; padding: 1.5rem 2rem;
       color: #1f2937; background: #fff; }
h1 { font-size: 1.4rem; margin: 0 0 0.25rem 0; }
.subtitle { color: #6b7280; font-size: 0.85rem; margin-bottom: 1.25rem; }
.summary { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 0.9rem 1.25rem; display: flex; gap: 2.5rem; margin-bottom: 1.25rem;
           flex-wrap: wrap; }
.summary > div { line-height: 1.2; }
.summary b { font-size: 1.6rem; display: block; font-weight: 700; line-height: 1.1; }
.summary span { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: #6b7280; }
.summary .exact b { color: #dc2626; }
.summary .similar b { color: #d97706; }
.summary .new b { color: #059669; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 0.55rem 0.55rem; text-align: left; border-bottom: 1px solid #e5e7eb;
         vertical-align: top; }
th { background: #f9fafb; font-weight: 600; font-size: 11.5px;
     text-transform: uppercase; letter-spacing: 0.5px; color: #374151; }
.score-cell { font-variant-numeric: tabular-nums; }
tr.row-summary { cursor: pointer; }
tr.row-summary:hover { background: #f3f4f6; }
tr.row-detail { display: none; }
tr.row-detail.open { display: table-row; }
tr.row-detail td { background: #fafafa; padding: 0; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 12px;
        font-size: 10.5px; font-weight: 700; letter-spacing: 0.5px;
        white-space: nowrap; }
.pill.exact   { background: #fee2e2; color: #b91c1c; }
.pill.similar { background: #fef3c7; color: #b45309; }
.pill.new     { background: #d1fae5; color: #047857; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem;
               padding: 1.25rem; }
.qcard { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
         padding: 0.9rem 1.1rem; }
.qcard.empty { background: #f9fafb; color: #6b7280; font-style: italic; }
.qcard h3 { margin: 0 0 0.5rem 0; font-size: 0.7rem; text-transform: uppercase;
            color: #6b7280; letter-spacing: 0.5px; font-weight: 600; }
.qtext { font-size: 14.5px; line-height: 1.55; }
.qmeta { color: #dc2626; font-style: italic; font-weight: 500; }
.options { font-size: 13px; color: #4b5563; margin-top: 0.55rem; }
.options ol { padding-left: 1.4rem; margin: 0.25rem 0; }
.options li { margin: 2px 0; }
.score-note { padding: 0.65rem 0.95rem; background: #f3f4f6; font-size: 12.5px;
              color: #374151; grid-column: 1 / -1; border-radius: 6px; line-height: 1.5; }
.others { padding: 0.4rem 1.25rem 1rem 1.25rem; }
.others h4 { margin: 0.4rem 0 0.4rem 0; font-size: 11px; text-transform: uppercase;
             letter-spacing: 0.5px; color: #6b7280; font-weight: 600; }
.others ul { list-style: none; padding: 0; margin: 0; font-size: 13px; line-height: 1.5; }
.others li { padding: 4px 0; border-top: 1px solid #e5e7eb; color: #4b5563;
             display: flex; gap: 8px; align-items: baseline; }
.other-score { display: inline-block; min-width: 48px; padding: 1px 6px;
               background: #e5e7eb; color: #1f2937; border-radius: 4px;
               font-size: 11.5px; font-weight: 600; text-align: center;
               font-variant-numeric: tabular-nums; }
.other-text { flex: 1; }
footer { font-size: 12px; color: #9ca3af; margin-top: 2rem; text-align: right;
         border-top: 1px solid #e5e7eb; padding-top: 0.75rem; }
@media print {
  body { max-width: none; padding: 0.75rem; }
  tr.row-detail { display: table-row !important; }
  .qcard { page-break-inside: avoid; }
  tr { page-break-inside: avoid; }
  .row-summary { background: transparent !important; }
}
"""

    js = """
document.querySelectorAll('tr.row-summary').forEach(function(row) {
  row.addEventListener('click', function() {
    var id = row.getAttribute('data-row-id');
    var detail = document.querySelector('tr[data-detail-for="' + id + '"]');
    if (detail) detail.classList.toggle('open');
  });
});
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Repeat Report — {esc(subject_label)}</title>
<style>{css}</style>
</head>
<body>
<h1>Repeat Report — {esc(subject_label)}</h1>
<div class="subtitle">
  {n_total} questions checked · model: {esc(meta.get('model_name', ''))} ({meta.get('embed_dims', '')}d) ·
  thresholds: hard={meta.get('thresholds', {}).get('hard', '?')} soft={meta.get('thresholds', {}).get('soft', '?')}
</div>

<div class="summary">
  <div class="exact"><b>{n_exact}</b><span>Exact match found</span></div>
  <div class="similar"><b>{n_similar}</b><span>Similar found</span></div>
  <div class="new"><b>{n_new}</b><span>New</span></div>
  <div><b>{n_total}</b><span>Total</span></div>
</div>

<table>
<thead>
<tr>
  <th style="width: 36px;">#</th>
  <th>Question</th>
  <th style="width: 130px;">Status</th>
  <th style="width: 110px;">Best match</th>
  <th style="width: 70px;">Score</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<footer>
  Generated {esc(generated_at)}{esc(elapsed_str)} · check run at {esc(run_at)} · source: {esc(source)}
</footer>

<script>{js}</script>
</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Render a check_duplicates JSON report as HTML.")
    ap.add_argument("--json", type=Path, required=True, help="Path to dup_check_*.json")
    ap.add_argument("--out", type=Path, help="Output HTML path (default: alongside the JSON, .html)")
    args = ap.parse_args()

    if not args.json.exists():
        sys.exit(f"JSON not found: {args.json}")
    report = json.loads(args.json.read_text(encoding="utf-8"))

    out_path = args.out or args.json.with_suffix(".html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render(report, out_path)
    print(f"Wrote: {out_path}")
    print(f"Open:  start \"\" \"{out_path}\"")


if __name__ == "__main__":
    main()
