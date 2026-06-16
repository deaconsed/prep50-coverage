"""POST /api/check-single — synchronous single-question dup check.

Powers the instant-check popup. Same pipeline as the batch endpoint, but for
one question and returning the result directly (no SSE, no persisted report).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, get_genai_client
from api.schemas import (
    FingerprintMatch, InputData, SingleCheckRequest, SingleCheckResponse,
    TopKItem, Verdict,
)
from api.services.ai_rerank import rerank, verdict_with_ai
from api.services.pipeline import normalize_single
from ingest_batch import (
    THRESHOLD_HARD, THRESHOLD_SOFT,
    embed_query_texts, lookup_one,
)

router = APIRouter()


@router.post("/check-single", response_model=SingleCheckResponse)
def check_single(
    req: SingleCheckRequest,
    conn = Depends(get_db),
    client = Depends(get_genai_client),
):
    # 1. Validate subject.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM subjects WHERE id=%s AND tag IN ('W','JW')",
            (req.subject_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"subject_id={req.subject_id} not found or not W/JW")
    subject_name = row[0]

    r = normalize_single(req.question, req.subject_id)
    if not r["text_clean"].strip():
        return SingleCheckResponse(
            input=InputData(
                subject_id=req.subject_id, subject_name=subject_name,
                question_raw=req.question, text_clean=r["text_clean"],
                search_fingerprint=r["search_fingerprint"],
            ),
            verdict=Verdict.NEW, reason="empty text after normalization",
        )

    # 2. Embed + lookup (wide net so AI rerank has depth to evaluate).
    vectors = embed_query_texts(client, [r["text_clean"]])
    embedding = vectors[0]
    fp_hits, ann = lookup_one(conn, req.subject_id, r["search_fingerprint"], embedding, top_k=20)
    if not fp_hits:
        ann = rerank(r["text_clean"], None, ann)
    verdict, reason = verdict_with_ai(fp_hits, ann, THRESHOLD_HARD, THRESHOLD_SOFT)
    ann = ann[:5]
    fp_ids = {h["question_id"] for h in fp_hits}

    return SingleCheckResponse(
        input=InputData(
            subject_id=req.subject_id, subject_name=subject_name,
            question_raw=req.question, text_clean=r["text_clean"],
            search_fingerprint=r["search_fingerprint"],
        ),
        verdict=Verdict(verdict),
        reason=reason,
        fingerprint_matches=[
            FingerprintMatch(
                question_id=h["question_id"],
                question_year=h.get("question_year"),
                question_year_number=h.get("question_year_number"),
                text_clean=h["text_clean"],
                option_1=h.get("option_1"),
                option_2=h.get("option_2"),
                option_3=h.get("option_3"),
                option_4=h.get("option_4"),
            )
            for h in fp_hits
        ],
        top_k=[
            TopKItem(
                question_id=a["question_id"],
                cosine=float(a["cosine"]),
                question_year=a.get("question_year"),
                question_year_number=a.get("question_year_number"),
                text_clean=a["text_clean"],
                fingerprint_match=a["question_id"] in fp_ids,
                option_1=a.get("option_1"),
                option_2=a.get("option_2"),
                option_3=a.get("option_3"),
                option_4=a.get("option_4"),
                ai_score=a.get("ai_score"),
                ai_reason=a.get("ai_reason"),
            )
            for a in ann
        ],
    )
