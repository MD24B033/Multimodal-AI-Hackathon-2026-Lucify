from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.serializers import (
    serialize_flashcard,
    serialize_mastery,
    serialize_plan,
    serialize_student,
)
from app.assessment.generator import create_assessment
from app.db.models import (
    Assessment,
    AssessmentKind,
    AssessmentReport,
    Course,
    Interaction,
    Student,
    StudyPlan,
    Topic,
)
from app.enhancements.flowmap import learning_path
from app.enhancements.revision import (
    due_flashcards,
    generate_audio_brief,
    generate_flashcards,
    review_flashcard,
    revision_pack,
)
from app.enhancements.schedule import build_study_plan, retention_forecast
from app.learner import profile

router = APIRouter(prefix="/api/learner", tags=["learner"])


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    preferred_language: str = "en"


class PlanRequest(BaseModel):
    course_id: uuid.UUID
    exam_date: date
    daily_minutes: int = Field(default=60, ge=15, le=480)


class FlashcardRequest(BaseModel):
    course_id: uuid.UUID
    topic_id: uuid.UUID
    count: int = Field(default=6, ge=1, le=20)


class ReviewRequest(BaseModel):
    score: float = Field(ge=0.0, le=1.0)


class RevisionPackRequest(BaseModel):
    course_id: uuid.UUID
    topic_limit: int = Field(default=3, ge=1, le=8)
    cards_per_topic: int = Field(default=5, ge=1, le=12)
    with_audio: bool = False


class BriefRequest(BaseModel):
    course_id: uuid.UUID
    topic_id: uuid.UUID
    synthesize: bool = True


@router.post("/students", status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, session: Session = DbSession):
    student = Student(
        name=payload.name,
        email=payload.email,
        preferred_language=payload.preferred_language,
    )
    session.add(student)
    session.commit()
    return serialize_student(student)


@router.get("/students")
def list_students(include_simulated: bool = False, session: Session = DbSession):
    statement = select(Student).order_by(Student.created_at.desc())
    if not include_simulated:
        statement = statement.where(Student.is_simulated.is_(False))
    return [serialize_student(student) for student in session.scalars(statement.limit(100)).all()]


@router.get("/students/{student_id}")
def get_student_detail(student_id: uuid.UUID, session: Session = DbSession):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return serialize_student(student)


@router.post("/students/{student_id}/diagnostic", status_code=status.HTTP_201_CREATED)
def start_diagnostic(
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    num_questions: int = 5,
    session: Session = DbSession,
):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if session.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")

    assessment, stats = create_assessment(
        session,
        course_id,
        student_id,
        title="Diagnostic check",
        kind=AssessmentKind.diagnostic,
        num_questions=num_questions,
        qtypes=["mcq"],
        adaptive=False,
        difficulty="medium",
    )
    if student.onboarded_at is None:
        student.onboarded_at = datetime.now(timezone.utc)
        session.commit()

    if stats.generated == 0:
        raise HTTPException(
            status_code=422,
            detail="Could not generate a diagnostic. Ingest course material first.",
        )
    return {"assessment_id": str(assessment.id), "generated": stats.generated}


@router.get("/students/{student_id}/dashboard")
def dashboard(student_id: uuid.UUID, course_id: uuid.UUID, session: Session = DbSession):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    snapshots = profile.snapshot(session, student_id, course_id)
    weak = profile.weak_topics(session, student_id, course_id, limit=5)
    overall = profile.overall_mastery(session, student_id, course_id)

    assessments = session.scalars(
        select(Assessment)
        .where(Assessment.student_id == student_id, Assessment.course_id == course_id)
        .order_by(Assessment.created_at.desc())
        .limit(10)
    ).all()
    reports = {
        report.assessment_id: report
        for report in session.scalars(
            select(AssessmentReport).where(
                AssessmentReport.assessment_id.in_([a.id for a in assessments])
            )
        ).all()
    }

    # Interactions carry a topic, and a topic belongs to a course, which is how this
    # dashboard stays about the course it claims to be about.
    in_course = (
        select(Interaction.id)
        .join(Topic, Topic.id == Interaction.topic_id)
        .where(Interaction.student_id == student_id, Topic.course_id == course_id)
    )
    course_interaction_ids = in_course.scalar_subquery()

    interaction_count = session.scalar(
        select(func.count(Interaction.id)).where(Interaction.id.in_(course_interaction_ids))
    )

    graded_count = session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.id.in_(course_interaction_ids),
            Interaction.kind != "chat_turn",
        )
    )

    history = session.execute(
        select(
            func.date_trunc("day", Interaction.created_at).label("day"),
            func.avg(Interaction.p_known_after),
            func.count(Interaction.id),
            func.count(Interaction.id).filter(Interaction.kind != "chat_turn").label("graded"),
        )
        .where(
            Interaction.id.in_(course_interaction_ids),
            Interaction.p_known_after.isnot(None),
        )
        .group_by("day")
        .order_by("day")
    ).all()

    due_count = sum(
        1
        for item in snapshots
        if item.due_at is not None and item.due_at <= datetime.now(timezone.utc)
    )

    return {
        "student": serialize_student(student),
        "overall_mastery": round(overall, 4),
        "topics_tracked": len([item for item in snapshots if item.attempts > 0]),
        "interactions": interaction_count or 0,
        "due_for_review": due_count,
        "mastery": [serialize_mastery(item) for item in snapshots],
        "weak_topics": [serialize_mastery(item) for item in weak],
        "next_up": learning_path(session, course_id, student_id, limit=5),
        "graded_interactions": graded_count or 0,
        "mastery_history": [
            {
                "date": day.isoformat(),
                "mastery": round(float(average), 4),
                "events": int(count),
                # How much of that day's movement came from graded answers rather than
                # from conversation. A curve driven only by chat signals is a weaker
                # claim, and the page should be able to say so.
                "graded_events": int(graded),
            }
            for day, average, count, graded in history
        ],
        "recent_assessments": [
            {
                "id": str(assessment.id),
                "title": assessment.title,
                "kind": assessment.kind.value,
                "status": assessment.status.value,
                "created_at": assessment.created_at.isoformat(),
                "score_percent": reports[assessment.id].score_percent
                if assessment.id in reports
                else None,
            }
            for assessment in assessments
        ],
    }


@router.get("/students/{student_id}/mastery")
def mastery(student_id: uuid.UUID, course_id: uuid.UUID, session: Session = DbSession):
    return [serialize_mastery(item) for item in profile.snapshot(session, student_id, course_id)]


@router.post("/students/{student_id}/study-plan")
def create_plan(student_id: uuid.UUID, payload: PlanRequest, session: Session = DbSession):
    if session.get(Student, student_id) is None:
        raise HTTPException(status_code=404, detail="Student not found")
    plan = build_study_plan(
        session, payload.course_id, student_id, payload.exam_date, payload.daily_minutes
    )
    return serialize_plan(plan)


@router.get("/students/{student_id}/study-plan")
def get_plan(student_id: uuid.UUID, course_id: uuid.UUID, session: Session = DbSession):
    plan = session.scalar(
        select(StudyPlan).where(
            StudyPlan.student_id == student_id, StudyPlan.course_id == course_id
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="No study plan yet")
    return serialize_plan(plan)


@router.get("/students/{student_id}/retention-forecast")
def forecast(
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    horizon_days: int = 21,
    session: Session = DbSession,
):
    return retention_forecast(session, course_id, student_id, horizon_days)


@router.post("/students/{student_id}/flashcards")
def make_flashcards(student_id: uuid.UUID, payload: FlashcardRequest, session: Session = DbSession):
    cards = generate_flashcards(
        session, payload.course_id, student_id, payload.topic_id, count=payload.count
    )
    if not cards:
        raise HTTPException(
            status_code=422, detail="Could not build flashcards for this topic from the material"
        )
    return [serialize_flashcard(card) for card in cards]


@router.get("/students/{student_id}/flashcards/due")
def list_due_flashcards(
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    limit: int = 20,
    session: Session = DbSession,
):
    cards = due_flashcards(session, student_id, course_id, limit=limit)
    return [serialize_flashcard(card) for card in cards]


@router.post("/flashcards/{card_id}/review")
def review(card_id: uuid.UUID, payload: ReviewRequest, session: Session = DbSession):
    card = review_flashcard(session, card_id, payload.score)
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    return serialize_flashcard(card)


@router.post("/students/{student_id}/revision-pack")
def build_revision_pack(
    student_id: uuid.UUID, payload: RevisionPackRequest, session: Session = DbSession
):
    return revision_pack(
        session,
        payload.course_id,
        student_id,
        topic_limit=payload.topic_limit,
        cards_per_topic=payload.cards_per_topic,
        with_audio=payload.with_audio,
    )


@router.post("/students/{student_id}/audio-brief")
def audio_brief(student_id: uuid.UUID, payload: BriefRequest, session: Session = DbSession):
    asset = generate_audio_brief(
        session,
        payload.course_id,
        student_id,
        payload.topic_id,
        synthesize=payload.synthesize,
    )
    if asset is None:
        raise HTTPException(status_code=422, detail="Could not build a brief for this topic")

    topic = session.get(Topic, asset.topic_id) if asset.topic_id else None
    return {
        "id": str(asset.id),
        "title": asset.title,
        "topic": topic.name if topic else None,
        "script": asset.payload.get("script"),
        "key_points": asset.payload.get("key_points", []),
        "citations": asset.payload.get("citations", []),
        "audio_url": f"/api/media/brief/{asset.id}" if asset.audio_path else None,
    }
