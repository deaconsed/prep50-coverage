"""GET /api/subjects — list W/JW subjects with their corpus counts."""
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.schemas import Subject
from ingest_batch import MODEL_NAME, MODEL_VERSION

router = APIRouter()


@router.get("/subjects", response_model=list[Subject])
def list_subjects(conn = Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, tag FROM subjects WHERE tag IN ('W','JW') ORDER BY name;"
        )
        subjects = [(r[0], r[1], str(r[2])) for r in cur.fetchall()]
        cur.execute(
            "SELECT subject_id, COUNT(*) FROM question_embeddings "
            "WHERE model_name=%s AND model_version=%s GROUP BY subject_id",
            (MODEL_NAME, MODEL_VERSION),
        )
        counts = {r[0]: r[1] for r in cur.fetchall()}
    return [
        Subject(id=sid, name=name, tag=tag, corpus_count=counts.get(sid, 0))
        for sid, name, tag in subjects
    ]
