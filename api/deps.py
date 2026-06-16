"""Shared dependencies: DB connection (with idle-reconnect) and Vertex AI client.

Why a custom DB dep instead of a pool:
- The pipeline already has fine-grained DB access via scripts/ingest_batch.py
  helpers. Adding a connection pool here would duplicate state and complicate
  the (already-working) per-request idiom.
- DigitalOcean managed Postgres closes idle connections ~30s. We cache one
  connection, but verify it with SELECT 1 before handing it out; on failure
  we reconnect transparently. See [[reference-envs]] memory.

The Vertex client is initialized once at startup and reused; init_genai_client()
reads service-account creds from disk and is too expensive to do per-request.
"""
from __future__ import annotations

import sys
from pathlib import Path
from threading import Lock
from typing import Optional

# Make scripts/ importable so we can reuse the production pipeline as-is.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg2
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from ingest_batch import connect_pg, init_genai_client  # noqa: E402

_db_conn: Optional[psycopg2.extensions.connection] = None
_db_lock = Lock()

_genai_client = None
_genai_lock = Lock()


def _open_conn():
    """Open a fresh DB connection. Wrapped so tests can monkeypatch."""
    return connect_pg()


def get_db():
    """FastAPI dependency: returns a live psycopg2 connection.

    Strategy:
      1. If we have a cached conn that's not .closed, ping with SELECT 1.
      2. On any InterfaceError/OperationalError (server-side idle timeout),
         drop the cache and reopen.
      3. Hand the live conn to the caller.

    The same conn is reused across requests; that's safe for FastAPI's
    threadpool-backed sync endpoints as long as we serialize access via the
    lock around the liveness check. For routes that need long-running per-
    request DB access (the SSE streamer), they should hold the conn for the
    duration of their work and release it back.
    """
    global _db_conn
    with _db_lock:
        if _db_conn is not None and not _db_conn.closed:
            try:
                with _db_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return _db_conn
            except (psycopg2.InterfaceError, psycopg2.OperationalError):
                try:
                    _db_conn.close()
                except Exception:
                    pass
                _db_conn = None
        _db_conn = _open_conn()
        return _db_conn


def get_genai_client():
    """FastAPI dependency: returns the lazily-initialized Vertex AI client."""
    global _genai_client
    with _genai_lock:
        if _genai_client is None:
            _genai_client = init_genai_client()
        return _genai_client


def shutdown():
    """Called from FastAPI lifespan on shutdown — close the cached DB conn."""
    global _db_conn
    with _db_lock:
        if _db_conn is not None and not _db_conn.closed:
            try:
                _db_conn.close()
            except Exception:
                pass
        _db_conn = None
