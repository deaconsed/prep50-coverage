"""In-process batch job runner.

A batch upload kicks off a background thread that runs the existing pipeline
(normalize → embed → fingerprint + ANN lookup → verdict). As each question is
classified, the result is pushed onto an asyncio Queue so the SSE endpoint can
stream it to the frontend in real time.

Threading model:
  * The HTTP handler that creates the batch returns immediately.
  * A daemon thread runs the synchronous pipeline (psycopg2 + Vertex are sync).
  * Events cross the thread → event-loop boundary via loop.call_soon_threadsafe.
  * The SSE handler awaits items off the asyncio Queue.

State retention:
  * Each BatchJob keeps an `items` list — completed results so far. If the SSE
    consumer reconnects mid-flight, we replay the snapshot then continue from
    the queue.
  * Jobs are not persisted across process restarts; the final report.json on
    disk is the canonical record. The /api/batches/{id} GET endpoint reads
    from disk when the in-memory job is gone.
"""
from __future__ import annotations

import asyncio
import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from ingest_batch import (
    EMBED_BATCH, THRESHOLD_HARD, THRESHOLD_SOFT,
    chunked, embed_query_texts, find_intra_batch_duplicates,
    lookup_one,
)

from api.services.ai_rerank import rerank, verdict_with_ai
from api.services.pipeline import INGESTION_DIR, build_report_meta, serialize_item


class BatchJob:
    """In-memory state for one batch run."""

    def __init__(self, batch_id: str, inputs: list[dict],
                 subject: dict, source_file: str,
                 loop: asyncio.AbstractEventLoop):
        self.batch_id = batch_id
        self.inputs = inputs
        self.subject = subject  # {id, name, tag}
        self.source_file = source_file
        self.loop = loop
        # asyncio.Queue is bound to the captured event loop; we always push
        # via loop.call_soon_threadsafe to stay safe across thread boundaries.
        self.queue: asyncio.Queue = asyncio.Queue()
        self.items: list[dict] = []      # serialized result items as they complete
        self.intra_dups: list[dict] = []
        self.summary: dict[str, Any] = {}
        self.status: str = "pending"     # pending | embedding | scoring | done | error
        self.report_path: Optional[Path] = None
        self.error: Optional[str] = None

    def _put(self, event: str, data: Any):
        """Thread-safe enqueue of an SSE event."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, {"event": event, "data": data})


_jobs: dict[str, BatchJob] = {}
_jobs_lock = threading.Lock()


def make_batch_id() -> str:
    return (
        f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid4().hex[:6]}"
    )


def create_job(inputs: list[dict], subject: dict, source_file: str,
               loop: asyncio.AbstractEventLoop) -> BatchJob:
    job = BatchJob(make_batch_id(), inputs, subject, source_file, loop)
    with _jobs_lock:
        _jobs[job.batch_id] = job
    return job


def get_job(batch_id: str) -> Optional[BatchJob]:
    with _jobs_lock:
        return _jobs.get(batch_id)


def delete_job(batch_id: str) -> bool:
    """Remove the in-memory job for a batch_id, if any. Returns True if removed."""
    with _jobs_lock:
        return _jobs.pop(batch_id, None) is not None


def _save_report(job: BatchJob):
    INGESTION_DIR.mkdir(exist_ok=True)
    report = {
        "meta": build_report_meta(job.batch_id, job.source_file),
        "summary": job.summary,
        "intra_batch_duplicates": job.intra_dups,
        "items": job.items,
    }
    job.report_path = INGESTION_DIR / f"{job.batch_id}.json"
    with open(job.report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)


def _run_pipeline(job: BatchJob, conn, client):
    """Synchronous pipeline executed on a worker thread."""
    try:
        job._put("started", {"total": len(job.inputs)})

        # 1. Intra-batch duplicates (purely from fingerprints — no Vertex call).
        job.intra_dups = find_intra_batch_duplicates(job.inputs)
        if job.intra_dups:
            job._put("intra_dups", {"groups": job.intra_dups})

        # 2. Embed all queries — Vertex handles batches of EMBED_BATCH.
        job.status = "embedding"
        job._put("phase", {"phase": "embedding"})
        for batch in chunked(job.inputs, EMBED_BATCH):
            with_text = [r for r in batch if r["text_clean"].strip()]
            if not with_text:
                continue
            vectors = embed_query_texts(client, [r["text_clean"] for r in with_text])
            for r, v in zip(with_text, vectors):
                r["embedding"] = v

        # 3. Per-question lookup + verdict.
        job.status = "scoring"
        job._put("phase", {"phase": "scoring"})
        counts = {"REPEAT": 0, "NEAR_HIGH": 0, "NEAR": 0, "NEW": 0}
        for i, r in enumerate(job.inputs):
            if "embedding" not in r:
                verdict, reason = "NEW", "empty text after normalization"
                fp_hits, ann = [], []
            else:
                # Pull a wider ANN net so the AI rerank can see deeper candidates.
                fp_hits, ann = lookup_one(
                    conn, r["subject_id"], r["search_fingerprint"], r["embedding"], top_k=20,
                )
                if not fp_hits:
                    ann = rerank(r["text_clean"], r.get("options"), ann)
                verdict, reason = verdict_with_ai(fp_hits, ann, THRESHOLD_HARD, THRESHOLD_SOFT)
                # Trim back to the top 5 for the persisted report — keeps the
                # JSON the same size as before while preserving the AI's pick.
                ann = ann[:5]

            item = serialize_item(r, job.subject["name"], verdict, reason, fp_hits, ann)
            job.items.append(item)
            counts[verdict] += 1
            job._put("item", {
                "index": i,
                "total": len(job.inputs),
                "counts": dict(counts),
                "item": item,
            })

        # 4. Build summary + persist report.
        job.summary = {
            "total": len(job.items),
            **counts,
            "by_subject": {
                job.subject["name"]: {"total": len(job.items), **counts}
            },
            "intra_batch_duplicate_groups": len(job.intra_dups),
        }
        _save_report(job)
        job.status = "done"
        job._put("done", {
            "summary": job.summary,
            "report_path": str(job.report_path),
        })
    except Exception as e:
        job.error = "".join(traceback.format_exception_only(type(e), e)).strip()
        job.status = "error"
        job._put("error", {"error": job.error})


def start_job(job: BatchJob, conn, client):
    """Spawn the pipeline thread. Returns immediately."""
    t = threading.Thread(
        target=_run_pipeline,
        args=(job, conn, client),
        name=f"batch-{job.batch_id}",
        daemon=True,
    )
    t.start()
