from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.assessment.generator import create_assessment
from app.db.models import AssessmentKind, GenerationTask
from app.enhancements.notes import generate_notes
from app.enhancements.revision import generate_audio_brief, revision_pack
from app.enhancements.schedule import build_study_plan
from app.tasks import handler


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


@handler("notes")
def run_notes(session: Session, task: GenerationTask) -> dict[str, Any]:
    params = task.params or {}
    note = generate_notes(
        session,
        task.course_id,
        task.student_id,
        note_format=params.get("note_format", "summary"),
        topic_id=_uuid_or_none(params.get("topic_id")),
        concept_id=_uuid_or_none(params.get("concept_id")),
        free_text=params.get("free_text"),
        source_ids=[uuid.UUID(value) for value in params.get("source_ids") or []],
        depth=params.get("depth", "standard"),
        language=params.get("language", "en"),
        extra_instructions=params.get("extra_instructions"),
    )
    if note is None:
        raise RuntimeError("The course material does not cover that well enough to write notes from.")
    return {"note_id": note.get("id"), "title": note.get("title"), "format": note.get("format")}


@handler("assessment")
def run_assessment(session: Session, task: GenerationTask) -> dict[str, Any]:
    params = task.params or {}
    try:
        kind = AssessmentKind(params.get("kind", "quiz"))
    except ValueError:
        kind = AssessmentKind.quiz

    assessment, stats = create_assessment(
        session,
        task.course_id,
        task.student_id,
        title=params.get("title"),
        kind=kind,
        num_questions=int(params.get("num_questions", 5)),
        topic_ids=[uuid.UUID(value) for value in params.get("topic_ids") or []] or None,
        source_ids=[uuid.UUID(value) for value in params.get("source_ids") or []] or None,
        qtypes=params.get("qtypes"),
        difficulty=params.get("difficulty"),
        adaptive=bool(params.get("adaptive", True)),
        verify=bool(params.get("verify", True)),
    )

    if stats.generated == 0:
        raise RuntimeError(
            "Could not generate any questions for that scope. Try a wider scope or fewer questions."
        )

    return {
        "assessment_id": str(assessment.id),
        "generated": stats.generated,
        "rejected_duplicate": stats.rejected_duplicate,
        "rejected_verification": stats.rejected_verification,
        "topics_covered": stats.topics_covered,
    }


@handler("revision_pack")
def run_revision_pack(session: Session, task: GenerationTask) -> dict[str, Any]:
    params = task.params or {}
    return revision_pack(
        session,
        task.course_id,
        task.student_id,
        topic_limit=int(params.get("topic_limit", 2)),
        cards_per_topic=int(params.get("cards_per_topic", 5)),
        with_audio=bool(params.get("with_audio", False)),
    )


@handler("audio_brief")
def run_audio_brief(session: Session, task: GenerationTask) -> dict[str, Any]:
    params = task.params or {}
    topic_id = _uuid_or_none(params.get("topic_id"))
    if topic_id is None:
        raise RuntimeError("A topic is required for an audio brief")

    asset = generate_audio_brief(
        session,
        task.course_id,
        task.student_id,
        topic_id,
        synthesize=bool(params.get("synthesize", True)),
    )
    if asset is None:
        raise RuntimeError("Could not build a brief for that topic")
    return {"asset_id": str(asset.id), "title": asset.title}


@handler("study_plan")
def run_study_plan(session: Session, task: GenerationTask) -> dict[str, Any]:
    from datetime import date

    params = task.params or {}
    exam = params.get("exam_date")
    if not exam:
        raise RuntimeError("An exam date is required to build a plan")

    plan = build_study_plan(
        session,
        task.course_id,
        task.student_id,
        date.fromisoformat(str(exam)),
        int(params.get("daily_minutes", 60)),
    )
    return {"plan_id": str(plan.id), "sessions": len(plan.sessions or [])}
