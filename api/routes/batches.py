"""Batch lifecycle endpoints.

  POST /api/batches               upload CSV + subject, kick off processing
  GET  /api/batches/{id}/events   SSE stream of per-question results
  GET  /api/batches/{id}          full report (in-memory or from disk)
  GET  /api/batches               list past runs (paginated)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from sse_starlette.sse import EventSourceResponse

from api.deps import get_db, get_genai_client
from api.schemas import BatchCreated, BatchSummaryRow
from api.services import jobs as job_runner
from api.services.pipeline import INGESTION_DIR, build_inputs, decode_csv_bytes

router = APIRouter()


def _fetch_subject(conn, subject_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, tag FROM subjects WHERE id = %s AND tag IN ('W','JW')",
            (subject_id,),
        )
        r = cur.fetchone()
    return {"id": r[0], "name": r[1], "tag": str(r[2])} if r else None


@router.post("/batches", response_model=BatchCreated)
async def create_batch(
    file: UploadFile = File(...),
    subject_id: int = Form(...),
    conn = Depends(get_db),
    client = Depends(get_genai_client),
):
    # 1. Validate subject.
    subject = _fetch_subject(conn, subject_id)
    if subject is None:
        raise HTTPException(404, f"subject_id={subject_id} not found or not W/JW")

    # 2. Parse + decode the CSV body.
    raw = await file.read()
    try:
        rows, _enc_used = decode_csv_bytes(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        inputs = build_inputs(rows, subject_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not inputs:
        raise HTTPException(400, "No usable rows in CSV (all 'question' cells empty).")

    # 3. Create the in-memory job + start the background pipeline.
    loop = asyncio.get_running_loop()
    job = job_runner.create_job(inputs, subject, file.filename or "upload.csv", loop)
    job_runner.start_job(job, conn, client)

    return BatchCreated(
        batch_id=job.batch_id,
        total_questions=len(inputs),
        subject_id=subject_id,
        subject_name=subject["name"],
    )


@router.get("/batches/{batch_id}/events")
async def stream_batch_events(batch_id: str, request: Request):
    job = job_runner.get_job(batch_id)
    if job is None:
        raise HTTPException(404, f"batch {batch_id} not found (expired or never existed)")

    async def event_gen():
        # Replay any items already completed (handles refresh / reconnect).
        for i, item in enumerate(job.items):
            yield {
                "event": "item",
                "data": json.dumps({
                    "index": i,
                    "total": len(job.inputs),
                    "item": item,
                }, default=str),
            }
        # If the job already finished while we were replaying, end the stream.
        if job.status in ("done", "error"):
            yield {
                "event": job.status,
                "data": json.dumps(
                    {"summary": job.summary, "report_path": str(job.report_path)}
                    if job.status == "done" else {"error": job.error},
                    default=str,
                ),
            }
            return

        # Live tail: drain the queue until done/error or client disconnects.
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(job.queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Heartbeat to keep the connection alive through proxies.
                yield {"event": "ping", "data": "{}"}
                continue
            yield {"event": ev["event"], "data": json.dumps(ev["data"], default=str)}
            if ev["event"] in ("done", "error"):
                break

    return EventSourceResponse(event_gen())


@router.get("/batches/{batch_id}")
def get_batch_report(batch_id: str):
    """Return the full report — from memory if the job is still around, otherwise from disk."""
    job = job_runner.get_job(batch_id)
    if job is not None and job.status == "done" and job.report_path and job.report_path.exists():
        return json.loads(job.report_path.read_text(encoding="utf-8"))

    # Read from disk.
    path = INGESTION_DIR / f"{batch_id}.json"
    if not path.exists():
        raise HTTPException(404, f"batch {batch_id} not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: str):
    """Permanently delete a saved batch report.

    Removes the JSON file from ingestion_batches/ and drops any in-memory
    job state. 404 if neither was present.

    Running batches: this WILL remove a running job's in-memory state, but
    the background worker keeps going (no cancellation in v1). The thread
    will write its report after we delete, leaving a new file on disk —
    delete it again if needed.
    """
    on_disk = INGESTION_DIR / f"{batch_id}.json"
    file_existed = on_disk.exists()
    job_existed = job_runner.delete_job(batch_id)
    if not file_existed and not job_existed:
        raise HTTPException(404, f"batch {batch_id} not found")
    if file_existed:
        try:
            on_disk.unlink()
        except OSError as e:
            raise HTTPException(500, f"could not delete {on_disk.name}: {e}")
    return None


@router.get("/batches", response_model=list[BatchSummaryRow])
def list_batches(limit: int = 50):
    """List past batches by ingestion_batches/*.json (newest first)."""
    if not INGESTION_DIR.exists():
        return []
    files = sorted(INGESTION_DIR.glob("ingest_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = data.get("meta", {}) or {}
        summary = data.get("summary", {}) or {}
        # Pull subject name from the first item if available.
        items = data.get("items") or []
        subject_name = items[0]["input"].get("subject_name") if items else None
        subject_id = items[0]["input"].get("subject_id") if items else None
        out.append(BatchSummaryRow(
            batch_id=meta.get("batch_id", p.stem),
            ingested_at=meta.get("ingested_at", ""),
            subject_id=subject_id,
            subject_name=subject_name,
            total=summary.get("total", len(items)),
            counts={k: int(summary.get(k, 0))
                    for k in ("REPEAT", "NEAR_HIGH", "NEAR", "NEW")},
            status=meta.get("status", "unknown"),
        ))
    return out
