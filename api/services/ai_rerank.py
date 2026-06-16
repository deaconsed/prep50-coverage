"""LLM rerank stage that sits between cosine retrieval and the verdict.

Cosine retrieval is lexically biased — it misses pairs where the same
underlying question is phrased very differently (e.g. a fill-in-the-blank
whose meaning lives in its options vs. a fully-worded multiple-choice).
Calibration data showed cosine ~0.64 on such pairs, well below NEAR.

This stage hands the top-K candidates to OpenAI's `gpt-4o-mini` (override via
env) with their options attached, and asks for a 0-100 equivalence score per
candidate. The candidate that scores highest after the rerank becomes the
"best match", and the score is plumbed through to the UI and used in the
verdict decision.

Requires OPENAI_API_KEY in the environment. If the key is missing or any call
fails, we silently fall back to the cosine-only ordering — never blocks a
batch.

Cost / latency notes (gpt-4o-mini, defaults):
  - ~$0.00015 per question; 80-question batch ≈ $0.012
  - ~1-2s per question; 80-question batch adds ~2 minutes end-to-end
  - Disable with `AI_RERANK_ENABLED=false` if you need raw speed.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openai import OpenAI

DEFAULT_MODEL = os.getenv("AI_RERANK_MODEL", "gpt-4o-mini")
ENABLED = os.getenv("AI_RERANK_ENABLED", "true").lower() in ("1", "true", "yes")
TOP_K_FOR_RERANK = int(os.getenv("AI_RERANK_TOP_K", "20"))

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    """Lazy-init the OpenAI client. Returns None if OPENAI_API_KEY is missing
    so the rest of the pipeline can degrade gracefully."""
    global _client
    if _client is not None:
        return _client
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set — AI rerank disabled")
        return None
    _client = OpenAI()
    return _client


SYSTEM_PROMPT = (
    "You are an expert in matching WAEC exam questions across years. Respond "
    "ONLY with a valid JSON object — no prose, no markdown fencing."
)

USER_PROMPT = """Two questions are SAME if they test the same underlying concept and have the same correct answer — even if phrased very differently or with different question formats (fill-in-the-blank vs. multiple-choice). Pay special attention to fill-in-the-blank stems where the meaning lives in the options.

NEW QUESTION:
{new_text}
{new_options}

CANDIDATES FROM CORPUS (each with its year and options):
{candidates}

For EACH candidate, return one object with:
- "candidate" (1-indexed integer matching the candidates above)
- "score" (0-100, where 100 means it asks the EXACT same thing as the new question)
- "reason" (one short sentence — why this score)

Scoring guide:
  90-100: Same question, same answer. Just rephrased.
  70-89:  Same topic and concept; minor scope difference.
  50-69:  Related topic, but the underlying ask differs.
  30-49:  Same domain (e.g. both about Jesus), but different question.
  0-29:   Unrelated.

Return a JSON object: {{"matches": [{{"candidate": 1, "score": 95, "reason": "..."}}, ...]}}
"""


def _fmt_options(opts: list[Any]) -> str:
    clean = [str(o).strip() for o in opts if o and str(o).strip()]
    if not clean:
        return ""
    letters = ["A", "B", "C", "D"][: len(clean)]
    return "  Options: " + " | ".join(f"{l}. {o}" for l, o in zip(letters, clean))


def _format_candidates(candidates: list[dict]) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        year = c.get("question_year") or "?"
        qnum = c.get("question_year_number")
        year_lbl = f"{year}, Q{qnum}" if qnum else f"{year}"
        opts = _fmt_options(
            [c.get("option_1"), c.get("option_2"), c.get("option_3"), c.get("option_4")]
        )
        lines.append(f"{i}. ({year_lbl})\n  {c['text_clean']}\n{opts}")
    return "\n\n".join(lines)


def rerank(
    new_text: str,
    new_options: list[Any] | None,
    candidates: list[dict],
    *,
    model: str = DEFAULT_MODEL,
) -> list[dict]:
    """Score each candidate via OpenAI. Mutates `candidates` to add
    `ai_score` (int|None) and `ai_reason` (str|None), then re-sorts by
    ai_score descending (cosine as tiebreaker).

    Falls back to cosine order if the rerank is disabled, the API key is
    missing, or the call fails.
    """
    if not ENABLED or not candidates:
        return candidates

    client = _get_client()
    if client is None:
        return candidates

    candidates = candidates[:TOP_K_FOR_RERANK]

    user_prompt = USER_PROMPT.format(
        new_text=new_text,
        new_options=_fmt_options(new_options or []),
        candidates=_format_candidates(candidates),
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or "{}"
        payload = json.loads(raw)
        scores = payload.get("matches") if isinstance(payload, dict) else None
        if not isinstance(scores, list):
            raise ValueError("LLM payload missing 'matches' array")
    except Exception as exc:
        logger.warning("AI rerank failed: %s — falling back to cosine order", exc)
        return candidates

    score_map: dict[int, int] = {}
    reason_map: dict[int, str] = {}
    for s in scores:
        try:
            idx = int(s["candidate"]) - 1
            score_map[idx] = max(0, min(100, int(s["score"])))
            reason_map[idx] = str(s.get("reason") or "").strip()[:240]
        except (KeyError, TypeError, ValueError):
            continue

    for i, c in enumerate(candidates):
        c["ai_score"] = score_map.get(i)
        c["ai_reason"] = reason_map.get(i)

    candidates.sort(
        key=lambda c: (
            c.get("ai_score") if c.get("ai_score") is not None else -1,
            float(c.get("cosine") or 0.0),
        ),
        reverse=True,
    )
    return candidates


def verdict_with_ai(
    fp_hits: list[dict],
    ann: list[dict],
    threshold_hard: float,
    threshold_soft: float,
) -> tuple[str, str]:
    """Verdict policy with AI-aware tiers.

    REPEAT     — fingerprint match (unchanged)
    NEAR_HIGH  — AI score >= 80 on top candidate, OR cosine >= threshold_hard
    NEAR       — AI score >= 55, OR cosine >= threshold_soft
    NEW        — otherwise
    """
    if fp_hits:
        return "REPEAT", "exact fingerprint match"

    top = ann[0] if ann else None
    if not top:
        return "NEW", "no candidates retrieved"

    cos = float(top.get("cosine") or 0.0)
    ai_score = top.get("ai_score")

    if ai_score is not None and ai_score >= 80:
        return "NEAR_HIGH", (
            f"AI judged same question (score {ai_score}, cos {cos:.3f})"
        )

    if cos >= threshold_hard:
        return "NEAR_HIGH", f"semantic cosine {cos:.3f} >= {threshold_hard}"

    if ai_score is not None and ai_score >= 55:
        return "NEAR", (
            f"AI partial match (score {ai_score}, cos {cos:.3f})"
        )

    if cos >= threshold_soft:
        return "NEAR", f"semantic cosine {cos:.3f} >= {threshold_soft}"

    return "NEW", f"top cosine {cos:.3f} below {threshold_soft}" + (
        f"; AI score {ai_score}" if ai_score is not None else ""
    )
