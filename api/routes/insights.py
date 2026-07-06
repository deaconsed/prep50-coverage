"""Insights: topic-level coverage analytics over the full question archive.

Unlike /corpus (which counts *embedded* rows), these endpoints read the raw
questions archive joined to the topic taxonomy:

    questions -> objective_questions -> objectives -> topic_objectives -> topics

Every archived question is objective and maps to exactly one topic. The `tag`
column encodes the exam: W = WAEC/SSCE, J = UTME/JAMB, JW = both. Valid exam
years are 1990-2026 (other year values are placeholder/dirty data).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from api.schemas import InsightQuestion, InsightQuestions, InsightSubject, TopicStat

router = APIRouter()

# Shared topic-linkage join. Kept as one string so every endpoint reads the
# archive through the exact same path.
_JOIN = """
  FROM questions q
  JOIN objective_questions oq ON oq.question_id = q.id
  JOIN objectives o ON o.id = oq.objective_id
  JOIN topic_objectives tob ON tob.objective_id = o.id
  JOIN topics t ON t.id = tob.topic_id
"""

_GOOD_YEAR = "q.question_year BETWEEN 1990 AND 2026"


@router.get("/insights/subjects", response_model=list[InsightSubject])
def insight_subjects(conn=Depends(get_db)):
    """Subjects that have topic-mapped questions, richest first."""
    sql = f"""
    SELECT s.id, s.name, s.tag,
           COUNT(*)                                        AS total,
           COUNT(DISTINCT t.id)                            AS topic_count,
           MIN(q.question_year) FILTER (WHERE {_GOOD_YEAR}) AS ymin,
           MAX(q.question_year) FILTER (WHERE {_GOOD_YEAR}) AS ymax
    {_JOIN}
    JOIN subjects s ON s.id = q.subject_id
    WHERE q.question IS NOT NULL AND q.question <> ''
    GROUP BY s.id, s.name, s.tag
    HAVING COUNT(*) > 0
    ORDER BY total DESC;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [
        InsightSubject(
            id=r[0], name=r[1], tag=str(r[2]),
            total=r[3], topic_count=r[4], year_min=r[5], year_max=r[6],
        )
        for r in rows
    ]


@router.get("/insights/topics", response_model=list[TopicStat])
def insight_topics(subject_id: int = Query(...), conn=Depends(get_db)):
    """Per-topic frequency, recurrence, and SSCE/UTME reach for one subject."""
    sql = f"""
    SELECT t.title,
           COUNT(*)                                                       AS n,
           COUNT(DISTINCT CASE WHEN {_GOOD_YEAR} THEN q.question_year END) AS years,
           COUNT(*) FILTER (WHERE q.tag IN ('W','JW'))                     AS ssce,
           COUNT(*) FILTER (WHERE q.tag IN ('J','JW'))                     AS utme
    {_JOIN}
    WHERE q.subject_id = %s AND q.question IS NOT NULL AND q.question <> ''
    GROUP BY t.title
    ORDER BY n DESC;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (subject_id,))
        rows = cur.fetchall()
    return [TopicStat(topic=r[0], n=r[1], years=r[2], ssce=r[3], utme=r[4]) for r in rows]


def _exam_clause(exam: str) -> str:
    return {
        "waec": " AND q.tag IN ('W','JW')",
        "utme": " AND q.tag IN ('J','JW')",
        "both": " AND q.tag = 'JW'",
    }.get(exam, "")


@router.get("/insights/questions", response_model=InsightQuestions)
def insight_questions(
    subject_id: int = Query(...),
    topic: str = Query(...),
    exam: str = Query("all", pattern="^(all|waec|utme|both)$"),
    year: Optional[int] = Query(None),
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db),
):
    """Real past questions for a topic, filtered by exam and year.

    `exam` (0=WAEC, 1=UTME, 2=both) and `answer` (1-4, 0=unknown) are returned
    as small ints; the frontend maps them to labels. Ordered most-recent first.
    """
    base = "WHERE q.subject_id = %s AND t.title = %s AND q.question IS NOT NULL AND q.question <> ''"
    base_params = [subject_id, topic]
    exam_sql = _exam_clause(exam)

    # Distinct years available for this topic+exam (ignores the year filter so
    # the dropdown always offers every year the topic was tested in).
    years_sql = f"""
    SELECT DISTINCT q.question_year
    {_JOIN}
    {base}{exam_sql} AND {_GOOD_YEAR}
    ORDER BY q.question_year DESC;
    """

    where = base + exam_sql
    params = list(base_params)
    if year is not None:
        where += " AND q.question_year = %s"
        params.append(year)

    count_sql = f"SELECT COUNT(*) {_JOIN} {where};"
    rows_sql = f"""
    SELECT q.id, q.question, q.option_1, q.option_2, q.option_3, q.option_4,
           CASE WHEN {_GOOD_YEAR} THEN q.question_year END          AS yr,
           CASE q.tag WHEN 'W' THEN 0 WHEN 'J' THEN 1 ELSE 2 END    AS exam,
           CASE q.short_answer::text
                WHEN 'option_1' THEN 1 WHEN 'option_2' THEN 2
                WHEN 'option_3' THEN 3 WHEN 'option_4' THEN 4 ELSE 0 END AS answer
    {_JOIN}
    {where}
    ORDER BY ({_GOOD_YEAR}) DESC, q.question_year DESC NULLS LAST, q.id DESC
    LIMIT %s OFFSET %s;
    """
    with conn.cursor() as cur:
        cur.execute(years_sql, base_params)
        years = [r[0] for r in cur.fetchall()]
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]
        cur.execute(rows_sql, params + [limit, offset])
        rows = cur.fetchall()
    items = [
        InsightQuestion(
            id=r[0], question=r[1], options=[r[2], r[3], r[4], r[5]],
            year=r[6], exam=r[7], answer=r[8],
        )
        for r in rows
    ]
    return InsightQuestions(total=total, years=years, items=items)
