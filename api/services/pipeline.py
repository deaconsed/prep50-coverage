"""Reusable pieces of the ingestion pipeline as called from FastAPI routes.

This module is a thin facade — all real work lives in scripts/ingest_batch.py
and scripts/normalize.py. We add:
  * CSV parsing with encoding fallback (mirrors dashboard/app.py:read_csv)
  * Input-row construction matching the dict shape that ingest_batch helpers
    consume.
  * Result-item construction matching the canonical report JSON shape.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ingest_batch import (
    MODEL_NAME, MODEL_VERSION, EMBED_DIMS,
    TASK_TYPE_QUERY, THRESHOLD_HARD, THRESHOLD_SOFT,
)
from normalize import to_clean, to_fingerprint

ROOT = Path(__file__).resolve().parents[2]
INGESTION_DIR = ROOT / "ingestion_batches"


def decode_csv_bytes(raw: bytes) -> tuple[list[dict[str, str]], str]:
    """Decode CSV bytes with progressive encoding fallback.

    Returns (rows, encoding_used). Raises ValueError if all encodings fail.
    """
    last_err: Optional[Exception] = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            reader = csv.DictReader(io.StringIO(text))
            rows = [dict(r) for r in reader]
            return rows, enc
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise ValueError(f"Could not decode CSV with utf-8 / cp1252 / latin-1: {last_err}")


def build_inputs(csv_rows: list[dict], subject_id: int) -> list[dict[str, Any]]:
    """Turn raw CSV rows into the dict shape consumed by ingest_batch helpers.

    Each input dict carries everything needed downstream: normalized text,
    fingerprint, and provenance for the final report.
    """
    # Case-insensitive column resolution.
    if not csv_rows:
        return []
    col_lower = {c.lower(): c for c in csv_rows[0].keys() if c}
    q_col = col_lower.get("question")
    if not q_col:
        raise ValueError("CSV is missing a 'question' column.")
    id_col = col_lower.get("id") or col_lower.get("question_id")
    year_col = col_lower.get("question_year") or col_lower.get("year")
    sid_col = col_lower.get("subject_id")
    sa_col = col_lower.get("short_answer")
    opt_cols = [col_lower.get(f"option_{k}") for k in range(1, 5)]

    inputs = []
    for i, r in enumerate(csv_rows):
        raw_q = (r.get(q_col) or "").strip()
        if not raw_q:
            continue
        text_clean = to_clean(raw_q)
        fp = to_fingerprint(text_clean)
        row_subject_id = subject_id
        if sid_col and (r.get(sid_col) or "").strip():
            try:
                row_subject_id = int(r[sid_col])
            except ValueError:
                pass
        year: Optional[int] = None
        if year_col and (r.get(year_col) or "").strip().isdigit():
            year = int(r[year_col])
        inputs.append({
            "input_index": i,
            "input_id": r.get(id_col) if id_col else None,
            "subject_id": row_subject_id,
            "question_year": year,
            "question_raw": raw_q,
            "options": [r.get(c) if c else None for c in opt_cols],
            "short_answer": r.get(sa_col) if sa_col else None,
            "text_clean": text_clean,
            "search_fingerprint": fp,
        })
    return inputs


def normalize_single(question: str, subject_id: int) -> dict[str, Any]:
    """Build the same input-dict shape for a single question (instant check)."""
    text_clean = to_clean(question)
    return {
        "input_index": 0,
        "input_id": None,
        "subject_id": subject_id,
        "question_year": None,
        "question_raw": question,
        "options": [None, None, None, None],
        "short_answer": None,
        "text_clean": text_clean,
        "search_fingerprint": to_fingerprint(text_clean),
    }


def serialize_item(r: dict, subject_name: str, verdict: str, reason: str,
                   fp_hits: list[dict], ann: list[dict]) -> dict[str, Any]:
    """Build the canonical result-item dict (matches ingestion_batches/*.json shape)."""
    fp_ids = {h["question_id"] for h in fp_hits}
    return {
        "input_index": r["input_index"],
        "input_id": r.get("input_id"),
        "input": {
            "subject_id": r["subject_id"],
            "subject_name": subject_name,
            "question_year": r.get("question_year"),
            "question_raw": r["question_raw"],
            "text_clean": r["text_clean"],
            "search_fingerprint": r["search_fingerprint"],
            "options": r.get("options") or [],
            "short_answer": r.get("short_answer"),
        },
        "verdict": verdict,
        "reason": reason,
        "fingerprint_matches": [
            {
                "question_id": h["question_id"],
                "question_year": h.get("question_year"),
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
                "question_year": a.get("question_year"),
                "question_year_number": a.get("question_year_number"),
                "text_clean": a["text_clean"],
                "fingerprint_match": a["question_id"] in fp_ids,
                "option_1": a.get("option_1"),
                "option_2": a.get("option_2"),
                "option_3": a.get("option_3"),
                "option_4": a.get("option_4"),
                "ai_score": a.get("ai_score"),
                "ai_reason": a.get("ai_reason"),
            }
            for a in ann
        ],
        "reviewer_decision": None,
        "reviewer_notes": None,
        "reviewed_at": None,
        "reviewed_by": None,
    }


def build_report_meta(batch_id: str, source_file: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": source_file,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "embed_dims": EMBED_DIMS,
        "task_type_query": TASK_TYPE_QUERY,
        "thresholds": {"hard": THRESHOLD_HARD, "soft": THRESHOLD_SOFT},
        "top_k": 5,
        "status": "pending_review",
    }
