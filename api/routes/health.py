"""Liveness check. Returns 200 even when DB is unreachable — the API itself
is up. Use /api/corpus/stats if you want to verify DB connectivity."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
