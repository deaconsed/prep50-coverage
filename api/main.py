"""FastAPI entrypoint.

Run from the project root:
    uvicorn api.main:app --reload --port 8000

All routes are prefixed with /api so the Next.js frontend can proxy under a
single path.

CORS: allows the dev frontend at localhost:3000 (Next.js default). Override
via FRONTEND_ORIGINS env var (comma-separated) for prod.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import deps
from api.routes import batches, check, corpus, health, insights, subjects


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: nothing to eagerly do — DB + Vertex client lazy-init on first use.
    yield
    # Shutdown: close the cached DB connection so we don't leak it.
    deps.shutdown()


app = FastAPI(
    title="Prep50 Coverage API",
    version="0.1.0",
    lifespan=lifespan,
)

_origins_env = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins_env.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["meta"])
app.include_router(subjects.router, prefix="/api", tags=["subjects"])
app.include_router(corpus.router, prefix="/api", tags=["corpus"])
app.include_router(insights.router, prefix="/api", tags=["insights"])
app.include_router(batches.router, prefix="/api", tags=["batches"])
app.include_router(check.router, prefix="/api", tags=["check"])
