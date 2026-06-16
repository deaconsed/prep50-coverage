"""GET /api/corpus/stats — total embedded count + by-subject map + model metadata."""
from fastapi import APIRouter, Depends

from api.deps import get_db
from api.schemas import CorpusStats
from ingest_batch import MODEL_NAME, MODEL_VERSION, EMBED_DIMS

router = APIRouter()


@router.get("/corpus/stats", response_model=CorpusStats)
def corpus_stats(conn = Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM question_embeddings WHERE model_name=%s AND model_version=%s",
            (MODEL_NAME, MODEL_VERSION),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT subject_id, COUNT(*) FROM question_embeddings "
            "WHERE model_name=%s AND model_version=%s GROUP BY subject_id",
            (MODEL_NAME, MODEL_VERSION),
        )
        by_subject = {r[0]: r[1] for r in cur.fetchall()}
    return CorpusStats(
        total=total,
        by_subject=by_subject,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        embed_dims=EMBED_DIMS,
    )
