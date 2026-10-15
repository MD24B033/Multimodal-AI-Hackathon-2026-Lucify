from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.serializers import serialize_assessment, serialize_report
from app.assessment.generator import create_assessment
from app.assessment.report import submit_assessment
from app.db.models import (
    Assessment,
    AssessmentItem,
    AssessmentKind,
    AssessmentReport,
    AssessmentStatus,
    Course,
    Question,
    Student,
)

router = APIRouter(prefix="/api/assessments", tags=["assessments"])


class AssessmentCreate(BaseModel):
    course_id: uuid.UUID
    student_id: uuid.UUID
    title: str | None = None
    kind: AssessmentKind = AssessmentKind.quiz
    num_questions: int = Field(default=6, ge=1, le=20)
    topic_ids: list[uuid.UUID] | None = None
    source_ids: list[uuid.UUID] | None = None
    qtypes: list[str] | None = None
    difficulty: str | None = None
    adaptive: bool = True
    verify: bool = True


class AnswerSubmission(BaseModel):
    responses: dict[uuid.UUID, str]


class SingleAnswer(BaseModel):
    question_id: uuid.UUID
    response: str


def _load_items(session: Session, assessment_id: uuid.UUID) -> list[tuple[AssessmentItem, Question]]:
    rows = session.execute(
        select(AssessmentItem, Question)
        .join(Question, Question.id == AssessmentItem.question_id)
        .where(AssessmentItem.assessment_id == assessment_id)
        .order_by(AssessmentItem.ordinal)
    ).all()
    return [(item, question) for item, question in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create(payload: AssessmentCreate, session: Session = DbSession):
    if session.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if session.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=404, detail="Student not found")

    assessment, stats = create_assessment(
        session,
        payload.course_id,
        payload.student_id,
        title=payload.title,
        kind=payload.kind,
        num_questions=payload.num_questions,
        topic_ids=payload.topic_ids,
        source_ids=payload.source_ids,
        qtypes=payload.qtypes,
        difficulty=payload.difficulty,
        adaptive=payload.adaptive,
        verify=payload.verify,
    )

    items = _load_items(session, assessment.id)
    if not items:
        raise HTTPException(
            status_code=422,
            detail="Could not generate any questions. Ingest more material for this scope, or lower the question count.",
        )

    return {
        **serialize_assessment(assessment, items, reveal=False),
        "generation": {
            "requested": stats.requested,
            "generated": stats.generated,
            "rejected_duplicate": stats.rejected_duplicate,
            "rejected_verification": stats.rejected_verification,
            "topics_covered": stats.topics_covered,
            "verification_issues": stats.verification_issues[:5],
        },
    }


@router.get("")
def list_assessments(
    course_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    session: Session = DbSession,
):
    statement = select(Assessment).order_by(Assessment.created_at.desc())
    if course_id:
        statement = statement.where(Assessment.course_id == course_id)
    if student_id:
        statement = statement.where(Assessment.student_id == student_id)
    assessments = session.scalars(statement.limit(50)).all()

    # The score and length belong to the list: a history rail that cannot show how you
    # did is just a list of dates.
    reports = {
        report.assessment_id: report
        for report in session.scalars(
            select(AssessmentReport).where(
                AssessmentReport.assessment_id.in_([a.id for a in assessments])
            )
        ).all()
    }
    counts = dict(
        session.execute(
            select(AssessmentItem.assessment_id, func.count(AssessmentItem.id))
            .where(AssessmentItem.assessment_id.in_([a.id for a in assessments]))
            .group_by(AssessmentItem.assessment_id)
        ).all()
    )

    payload = []
    for assessment in assessments:
        row = serialize_assessment(assessment)
        report = reports.get(assessment.id)
        row["score_percent"] = round(report.score_percent, 1) if report else None
        row["question_count"] = counts.get(assessment.id, 0)
        payload.append(row)
    return payload


@router.get("/{assessment_id}")
def get_assessment(
    assessment_id: uuid.UUID,
    reveal: bool | None = None,
    session: Session = DbSession,
):
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    items = _load_items(session, assessment_id)
    return serialize_assessment(assessment, items, reveal=reveal)


@router.post("/{assessment_id}/answer")
def save_answer(assessment_id: uuid.UUID, payload: SingleAnswer, session: Session = DbSession):
    item = session.scalar(
        select(AssessmentItem).where(
            AssessmentItem.assessment_id == assessment_id,
            AssessmentItem.question_id == payload.question_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Question not part of this assessment")
    item.response = payload.response
    session.commit()
    return {"saved": True}


@router.post("/{assessment_id}/submit")
def submit(assessment_id: uuid.UUID, payload: AnswerSubmission, session: Session = DbSession):
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status is AssessmentStatus.graded:
        raise HTTPException(status_code=409, detail="This assessment has already been graded")

    report = submit_assessment(session, assessment_id, payload.responses)
    items = _load_items(session, assessment_id)
    return {
        "assessment": serialize_assessment(assessment, items, reveal=True),
        "report": serialize_report(report),
    }


@router.get("/{assessment_id}/report")
def get_report(assessment_id: uuid.UUID, session: Session = DbSession):
    report = session.scalar(
        select(AssessmentReport).where(AssessmentReport.assessment_id == assessment_id)
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return serialize_report(report)


@router.get("/questions/bank")
def question_bank(
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None = None,
    limit: int = 50,
    session: Session = DbSession,
):
    from app.api.serializers import serialize_question

    statement = select(Question).where(Question.course_id == course_id)
    if topic_id:
        statement = statement.where(Question.topic_id == topic_id)
    questions = session.scalars(
        statement.order_by(Question.created_at.desc()).limit(min(limit, 200))
    ).all()
    return [serialize_question(question, include_answer=True) for question in questions]
