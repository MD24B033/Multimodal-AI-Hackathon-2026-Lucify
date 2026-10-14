from __future__ import annotations

import shutil
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.serializers import serialize_course, serialize_source, serialize_unit
from app.config import settings
from app.db.models import (
    Concept,
    ContentUnit,
    Course,
    IngestionJob,
    Modality,
    Source,
    SourceKind,
    SourceStatus,
    Student,
    Topic,
)
from app.api.routes.profiles import ensure_default_profile, owned_profile
from app.auth import require_student
from app.enhancements.flowmap import build_flow_map
from app.ingestion.jobs import worker
from app.ingestion.pipeline import detect_kind, file_digest
from app.realtime import course_channel, source_channel, sse_stream

router = APIRouter(prefix="/api/courses", tags=["courses"])


class CourseCreate(BaseModel):
    profile_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    exam_date: date | None = None
    start_date: date | None = None
    weekly_hours: int | None = Field(default=None, ge=1, le=80)
    difficulty: str | None = None
    goal: str | None = None


class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    exam_date: date | None = None
    start_date: date | None = None
    weekly_hours: int | None = None
    difficulty: str | None = None
    goal: str | None = None


class YoutubeIngest(BaseModel):
    url: str
    title: str | None = None


def _course_stats(session: Session, course_id: uuid.UUID) -> dict:
    units = session.scalar(
        select(func.count(ContentUnit.id)).where(ContentUnit.course_id == course_id)
    )
    sources = session.scalar(select(func.count(Source.id)).where(Source.course_id == course_id))
    ready = session.scalar(
        select(func.count(Source.id)).where(
            Source.course_id == course_id, Source.status == SourceStatus.ready
        )
    )
    topics = session.scalar(select(func.count(Topic.id)).where(Topic.course_id == course_id))
    concepts = session.scalar(select(func.count(Concept.id)).where(Concept.course_id == course_id))
    modality_rows = session.execute(
        select(ContentUnit.modality, func.count(ContentUnit.id))
        .where(ContentUnit.course_id == course_id)
        .group_by(ContentUnit.modality)
    ).all()
    return {
        "unit_count": units or 0,
        "source_count": sources or 0,
        "ready_source_count": ready or 0,
        "topic_count": topics or 0,
        "concept_count": concepts or 0,
        "modalities": {
            (modality.value if isinstance(modality, Modality) else str(modality)): count
            for modality, count in modality_rows
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    profile = (
        owned_profile(session, student, payload.profile_id)
        if payload.profile_id
        else ensure_default_profile(session, student)
    )
    course = Course(
        profile_id=profile.id,
        title=payload.title,
        description=payload.description,
        exam_date=payload.exam_date,
        start_date=payload.start_date,
        weekly_hours=payload.weekly_hours,
        difficulty=payload.difficulty,
        goal=payload.goal,
    )
    session.add(course)
    session.commit()
    return serialize_course(course, _course_stats(session, course.id))


@router.get("")
def list_courses(
    profile_id: uuid.UUID | None = None,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    ensure_default_profile(session, student)
    statement = select(Course).order_by(Course.created_at.desc())
    if profile_id is not None:
        owned_profile(session, student, profile_id)
        statement = statement.where(Course.profile_id == profile_id)
    courses = session.scalars(statement).all()
    return [serialize_course(course, _course_stats(session, course.id)) for course in courses]


@router.get("/{course_id}")
def get_course_detail(course_id: uuid.UUID, session: Session = DbSession):
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return serialize_course(course, _course_stats(session, course_id))


@router.patch("/{course_id}")
def update_course(course_id: uuid.UUID, payload: CourseUpdate, session: Session = DbSession):
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    session.commit()
    return serialize_course(course, _course_stats(session, course_id))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: uuid.UUID, session: Session = DbSession):
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    session.delete(course)
    session.commit()


@router.post("/{course_id}/sources", status_code=status.HTTP_202_ACCEPTED)
def upload_source(
    course_id: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    session: Session = DbSession,
):
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        kind = detect_kind(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_id = uuid.uuid4()
    destination = settings.uploads_dir / str(source_id) / (file.filename or "upload")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    digest = file_digest(destination)
    duplicate = session.scalar(
        select(Source).where(Source.course_id == course_id, Source.content_hash == digest)
    )
    if duplicate is not None:
        shutil.rmtree(destination.parent, ignore_errors=True)
        raise HTTPException(
            status_code=409,
            detail=f"This file was already uploaded as '{duplicate.title}'",
        )

    source = Source(
        id=source_id,
        course_id=course_id,
        kind=kind,
        title=title or (file.filename or "Untitled"),
        original_filename=file.filename,
        storage_path=str(destination),
        content_hash=digest,
    )
    session.add(source)
    session.add(IngestionJob(source_id=source_id))
    session.commit()

    worker.submit(source_id)
    return serialize_source(source)


@router.post("/{course_id}/sources/youtube", status_code=status.HTTP_202_ACCEPTED)
def ingest_youtube(course_id: uuid.UUID, payload: YoutubeIngest, session: Session = DbSession):
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    source = Source(
        course_id=course_id,
        kind=SourceKind.youtube,
        title=payload.title or payload.url,
        external_url=payload.url,
    )
    session.add(source)
    session.flush()
    session.add(IngestionJob(source_id=source.id))
    session.commit()

    worker.submit(source.id)
    return serialize_source(source)


@router.get("/{course_id}/sources")
def list_sources(course_id: uuid.UUID, session: Session = DbSession):
    sources = session.scalars(
        select(Source).where(Source.course_id == course_id).order_by(Source.created_at.desc())
    ).all()
    jobs = {
        job.source_id: job
        for job in session.scalars(
            select(IngestionJob).where(IngestionJob.source_id.in_([s.id for s in sources]))
        ).all()
    }
    return [serialize_source(source, jobs.get(source.id)) for source in sources]


@router.delete("/{course_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(course_id: uuid.UUID, source_id: uuid.UUID, session: Session = DbSession):
    source = session.get(Source, source_id)
    if source is None or source.course_id != course_id:
        raise HTTPException(status_code=404, detail="Source not found")
    session.delete(source)
    session.commit()


@router.post("/{course_id}/sources/{source_id}/reingest", status_code=status.HTTP_202_ACCEPTED)
def reingest_source(course_id: uuid.UUID, source_id: uuid.UUID, session: Session = DbSession):
    source = session.get(Source, source_id)
    if source is None or source.course_id != course_id:
        raise HTTPException(status_code=404, detail="Source not found")
    source.status = SourceStatus.pending
    source.error = None
    session.commit()
    worker.submit(source_id)
    return serialize_source(source)


@router.get("/{course_id}/units")
def list_units(
    course_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
    modality: Modality | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = DbSession,
):
    statement = select(ContentUnit).where(ContentUnit.course_id == course_id)
    if source_id:
        statement = statement.where(ContentUnit.source_id == source_id)
    if modality:
        statement = statement.where(ContentUnit.modality == modality)
    units = session.scalars(
        statement.order_by(ContentUnit.ordinal).offset(offset).limit(min(limit, 200))
    ).all()
    return [serialize_unit(unit) for unit in units]


@router.get("/{course_id}/topics")
def list_topics(course_id: uuid.UUID, session: Session = DbSession):
    topics = session.scalars(
        select(Topic).where(Topic.course_id == course_id).order_by(Topic.ordinal, Topic.name)
    ).all()
    concepts = session.scalars(select(Concept).where(Concept.course_id == course_id)).all()
    by_topic: dict[uuid.UUID, list[str]] = {}
    for concept in concepts:
        by_topic.setdefault(concept.topic_id, []).append(concept.name)

    return [
        {
            "id": str(topic.id),
            "name": topic.name,
            "kind": topic.kind.value,
            "parent_id": str(topic.parent_id) if topic.parent_id else None,
            "summary": topic.summary,
            "concepts": by_topic.get(topic.id, []),
        }
        for topic in topics
    ]


@router.get("/{course_id}/flow-map")
def course_flow_map(
    course_id: uuid.UUID,
    student_id: uuid.UUID | None = None,
    session: Session = DbSession,
):
    return build_flow_map(session, course_id, student_id)


@router.get("/{course_id}/units/{unit_id}/context")
def unit_context(
    course_id: uuid.UUID,
    unit_id: uuid.UUID,
    window: int = 3,
    session: Session = DbSession,
):
    """A cited unit plus its neighbours, so the reader can see it highlighted in place."""
    unit = session.get(ContentUnit, unit_id)
    if unit is None or unit.course_id != course_id:
        raise HTTPException(status_code=404, detail="Content unit not found")

    neighbours = session.scalars(
        select(ContentUnit)
        .where(
            ContentUnit.source_id == unit.source_id,
            ContentUnit.ordinal.between(unit.ordinal - window, unit.ordinal + window),
        )
        .order_by(ContentUnit.ordinal)
    ).all()

    source = session.get(Source, unit.source_id)
    return {
        "unit_id": str(unit.id),
        "source": {
            "id": str(source.id),
            "title": source.title,
            "kind": source.kind.value,
        },
        "window": [
            {
                **serialize_unit(item),
                "is_target": item.id == unit.id,
            }
            for item in neighbours
        ],
    }


@router.get("/{course_id}/events")
async def course_events(course_id: uuid.UUID, request: Request):
    return StreamingResponse(
        sse_stream(course_channel(course_id), request, include_latest=True),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{course_id}/sources/{source_id}/events")
async def source_events(course_id: uuid.UUID, source_id: uuid.UUID, request: Request):
    return StreamingResponse(
        sse_stream(source_channel(source_id), request, include_latest=True),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
