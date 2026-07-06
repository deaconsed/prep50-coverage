"""Pydantic schemas that mirror the canonical report JSON shape.

The existing ingestion_batches/*.json files (written by dashboard/app.py and
scripts/ingest_batch.py) are the source of truth. These schemas validate the
same shape on the wire, so the React app and the saved JSON stay in lockstep.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    REPEAT = "REPEAT"
    NEAR_HIGH = "NEAR_HIGH"
    NEAR = "NEAR"
    NEW = "NEW"


class Subject(BaseModel):
    id: int
    name: str
    tag: str
    corpus_count: int = 0


class CorpusStats(BaseModel):
    total: int
    by_subject: dict[int, int]
    model_name: str
    model_version: str
    embed_dims: int


class InsightSubject(BaseModel):
    """A subject with topic-mapped archive questions (for the Insights page)."""
    id: int
    name: str
    tag: str
    total: int
    topic_count: int
    year_min: Optional[int] = None
    year_max: Optional[int] = None


class TopicStat(BaseModel):
    """Per-topic coverage stats within a subject."""
    topic: str
    n: int          # total questions ever asked on this topic
    years: int      # distinct exam years it appears in (1990-2026)
    ssce: int       # reach in WAEC (tag W or JW)
    utme: int       # reach in UTME (tag J or JW)


class InsightQuestion(BaseModel):
    """One archived past question, exam-tagged."""
    id: int
    question: str
    options: list[Optional[str]] = Field(default_factory=list)
    year: Optional[int] = None
    exam: int = 2    # 0 = WAEC, 1 = UTME, 2 = both
    answer: int = 0  # 1-4 = correct option, 0 = unknown


class InsightQuestions(BaseModel):
    total: int
    years: list[int] = Field(default_factory=list)
    items: list[InsightQuestion] = Field(default_factory=list)


class FingerprintMatch(BaseModel):
    question_id: int
    question_year: Optional[int] = None
    question_year_number: Optional[int] = None
    text_clean: str
    option_1: Optional[str] = None
    option_2: Optional[str] = None
    option_3: Optional[str] = None
    option_4: Optional[str] = None


class TopKItem(BaseModel):
    question_id: int
    cosine: float
    question_year: Optional[int] = None
    question_year_number: Optional[int] = None
    text_clean: str
    fingerprint_match: bool = False
    option_1: Optional[str] = None
    option_2: Optional[str] = None
    option_3: Optional[str] = None
    option_4: Optional[str] = None
    # AI rerank: 0-100 confidence that this candidate asks the same question
    # as the new one; null when rerank was disabled or the call failed.
    ai_score: Optional[int] = None
    ai_reason: Optional[str] = None


class InputData(BaseModel):
    subject_id: int
    subject_name: Optional[str] = None
    question_year: Optional[int] = None
    question_raw: str
    text_clean: str
    search_fingerprint: str
    options: list[Optional[str]] = Field(default_factory=list)
    short_answer: Optional[str] = None


class VerdictItem(BaseModel):
    input_index: int
    input_id: Optional[str] = None
    input: InputData
    verdict: Verdict
    reason: str
    fingerprint_matches: list[FingerprintMatch] = Field(default_factory=list)
    top_k: list[TopKItem] = Field(default_factory=list)
    reviewer_decision: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None


class Summary(BaseModel):
    total: int
    REPEAT: int = 0
    NEAR_HIGH: int = 0
    NEAR: int = 0
    NEW: int = 0
    by_subject: dict[str, dict[str, int]] = Field(default_factory=dict)
    intra_batch_duplicate_groups: int = 0


class IntraBatchDup(BaseModel):
    search_fingerprint: str
    input_indices: list[int]


class BatchMeta(BaseModel):
    batch_id: str
    ingested_at: str
    source_file: str
    model_name: str
    model_version: str
    embed_dims: int
    task_type_query: str
    thresholds: dict[str, float]
    top_k: int
    status: str


class BatchReport(BaseModel):
    meta: BatchMeta
    summary: Summary
    intra_batch_duplicates: list[IntraBatchDup] = Field(default_factory=list)
    items: list[VerdictItem] = Field(default_factory=list)


class BatchCreated(BaseModel):
    batch_id: str
    total_questions: int
    subject_id: int
    subject_name: str


class BatchSummaryRow(BaseModel):
    """One row in the batch history list."""
    batch_id: str
    ingested_at: str
    subject_id: Optional[int] = None
    subject_name: Optional[str] = None
    total: int
    counts: dict[str, int]
    status: str


class SingleCheckRequest(BaseModel):
    question: str
    subject_id: int


class SingleCheckResponse(BaseModel):
    input: InputData
    verdict: Verdict
    reason: str
    fingerprint_matches: list[FingerprintMatch] = Field(default_factory=list)
    top_k: list[TopKItem] = Field(default_factory=list)
