"""Ingestion seen from anywhere in the app.

The per-course stream only exists while the material page is open, so leaving that
page used to look as though the work had stopped — it never had, it just went
unreported. These two endpoints give any page the same view: a snapshot of what is
in flight, and one stream carrying every job's progress.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.db.models import IngestionJob, JobStatus, Source
from app.realtime import ingestion_feed_channel, sse_stream

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

LIVE = (JobStatus.queued, JobStatus.running)


def _serialize(job: IngestionJob, source: Source) -> dict:
    """Deliberately the same shape the pipeline broadcasts, so a page can hold one
    map of source_id to progress and fill it from either the snapshot or the stream."""
    return {
        "source_id": str(source.id),
        "course_id": str(source.course_id),
        "title": source.title,
        "kind": source.kind.value,
        "status": job.status.value,
        "stage": job.stage or "queued",
        "progress": job.progress or 0.0,
        "detail": job.detail or {},
        "error": job.error,
        "terminal": False,
    }


@router.get("/active")
def active_jobs(session=DbSession) -> list[dict]:
    rows = session.execute(
        select(IngestionJob, Source)
        .join(Source, Source.id == IngestionJob.source_id)
        .where(IngestionJob.status.in_(LIVE))
        .order_by(IngestionJob.created_at)
    ).all()
    return [_serialize(job, source) for job, source in rows]


@router.get("/events")
async def ingestion_events(request: Request):
    return StreamingResponse(
        sse_stream(ingestion_feed_channel(), request, include_latest=False),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/sources/{source_id}")
def job_for_source(source_id: uuid.UUID, session=DbSession) -> dict | None:
    row = session.execute(
        select(IngestionJob, Source)
        .join(Source, Source.id == IngestionJob.source_id)
        .where(Source.id == source_id)
    ).first()
    if row is None:
        return None
    job, source = row
    return _serialize(job, source)
