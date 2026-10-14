from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Assessment,
    AssessmentItem,
    AssessmentReport,
    AssessmentStatus,
    Question,
    Topic,
)
from app.assessment.grading import grade_answer
from app.learner import memory as learner_memory
from app.learner import profile
from app.llm.groq_client import GroqError, get_client

logger = logging.getLogger(__name__)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "misconceptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "misconception": {"type": "string"},
                    "evidence": {"type": "string"},
                    "correction": {"type": "string"},
                },
                "required": ["topic", "misconception", "evidence", "correction"],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "topic": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "topic", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "misconceptions", "recommendations"],
    "additionalProperties": False,
}

REPORT_SYSTEM = """You analyse a completed quiz and write a short diagnostic report for the student.

Rules:
- summary is two to four sentences, addressed to the student. Name what went well and what to work on. Be specific, never generic encouragement.
- misconceptions groups the errors into distinct wrong beliefs. Each needs the topic, the misconception in one phrase, the evidence from their answers, and a one-sentence correction. Return an empty list when the student made no substantive errors.
- recommendations gives two to four concrete next actions, each tied to a topic and a reason drawn from this attempt.
- Base everything on the attempt data given. Never invent errors the student did not make."""


def submit_assessment(
    session: Session,
    assessment_id: uuid.UUID,
    responses: dict[uuid.UUID, str],
) -> AssessmentReport:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    items = session.scalars(
        select(AssessmentItem).where(AssessmentItem.assessment_id == assessment_id)
    ).all()

    mastery_before: dict[uuid.UUID, float] = {}
    mastery_after: dict[uuid.UUID, float] = {}
    topic_results: dict[uuid.UUID, list[float]] = defaultdict(list)

    for item in items:
        question = session.get(Question, item.question_id)
        if question is None:
            continue

        response = responses.get(item.question_id, item.response or "")
        result = grade_answer(session, question, response)

        item.response = response
        item.score = result.score
        item.is_correct = result.is_correct
        item.feedback = result.feedback
        item.feedback_citations = result.citations
        item.misconception = result.misconception
        item.answered_at = datetime.now(timezone.utc)

        if question.topic_id is not None:
            before, after = profile.record_response(
                session,
                assessment.student_id,
                question.topic_id,
                score=result.score,
                difficulty=question.difficulty.value,
                kind="quiz_answer",
                meta={"assessment_id": str(assessment_id), "question_id": str(question.id)},
            )
            mastery_before.setdefault(question.topic_id, before)
            mastery_after[question.topic_id] = after
            topic_results[question.topic_id].append(result.score)

    for topic_id in topic_results:
        profile.update_theta(session, assessment.student_id, topic_id)

    assessment.status = AssessmentStatus.graded
    assessment.submitted_at = datetime.now(timezone.utc)
    session.flush()

    report = _build_report(session, assessment, items, mastery_before, mastery_after, topic_results)

    learner_memory.observe_assessment(
        session,
        assessment.student_id,
        assessment.course_id,
        report.weak_topics or [],
        report.strong_topics or [],
        report.misconceptions or [],
    )

    session.commit()
    return report


def _build_report(
    session: Session,
    assessment: Assessment,
    items: list[AssessmentItem],
    mastery_before: dict[uuid.UUID, float],
    mastery_after: dict[uuid.UUID, float],
    topic_results: dict[uuid.UUID, list[float]],
) -> AssessmentReport:
    answered = [item for item in items if item.score is not None]
    score_percent = (
        100.0 * sum(item.score for item in answered) / len(answered) if answered else 0.0
    )

    topic_names = {
        topic.id: topic.name
        for topic in session.scalars(
            select(Topic).where(Topic.id.in_(set(topic_results.keys()) | set(mastery_after.keys())))
        ).all()
    }

    weak_topics = []
    strong_topics = []
    for topic_id, scores in topic_results.items():
        average = sum(scores) / len(scores)
        entry = {
            "topic_id": str(topic_id),
            "topic": topic_names.get(topic_id, "Unknown"),
            "accuracy": round(average, 3),
            "questions": len(scores),
            "mastery": round(mastery_after.get(topic_id, 0.0), 3),
        }
        if average < 0.6:
            weak_topics.append(entry)
        else:
            strong_topics.append(entry)

    weak_topics.sort(key=lambda entry: entry["accuracy"])
    strong_topics.sort(key=lambda entry: entry["accuracy"], reverse=True)

    mastery_delta = [
        {
            "topic_id": str(topic_id),
            "topic": topic_names.get(topic_id, "Unknown"),
            "before": round(mastery_before.get(topic_id, 0.0), 3),
            "after": round(after, 3),
            "delta": round(after - mastery_before.get(topic_id, 0.0), 3),
        }
        for topic_id, after in mastery_after.items()
    ]
    mastery_delta.sort(key=lambda entry: entry["delta"])

    narrative = _narrative(session, assessment, items, topic_names, score_percent)

    report = session.scalar(
        select(AssessmentReport).where(AssessmentReport.assessment_id == assessment.id)
    )
    if report is None:
        report = AssessmentReport(assessment_id=assessment.id)
        session.add(report)

    report.summary = narrative["summary"]
    report.score_percent = round(score_percent, 2)
    report.weak_topics = weak_topics
    report.strong_topics = strong_topics
    report.misconceptions = narrative["misconceptions"]
    report.recommendations = narrative["recommendations"]
    report.mastery_delta = mastery_delta
    session.flush()
    return report


def _narrative(
    session: Session,
    assessment: Assessment,
    items: list[AssessmentItem],
    topic_names: dict[uuid.UUID, str],
    score_percent: float,
) -> dict:
    lines = []
    for index, item in enumerate(items, start=1):
        question = session.get(Question, item.question_id)
        if question is None:
            continue
        topic = topic_names.get(question.topic_id, "General")
        lines.append(
            f"Q{index} [{topic} / {question.difficulty.value}] {question.stem}\n"
            f"  expected: {question.answer_key}\n"
            f"  student: {item.response or '(blank)'}\n"
            f"  score: {item.score:.2f}"
            + (f"\n  flagged misconception: {item.misconception}" if item.misconception else "")
        )

    fallback = {
        "summary": f"You scored {score_percent:.0f}% on this attempt.",
        "misconceptions": [],
        "recommendations": [],
    }
    if not lines:
        return fallback

    try:
        payload = get_client().complete_json(
            [
                {"role": "system", "content": REPORT_SYSTEM},
                {
                    "role": "user",
                    "content": f"Overall score: {score_percent:.0f}%\n\nAttempt detail:\n\n"
                    + "\n\n".join(lines),
                },
            ],
            schema=SUMMARY_SCHEMA,
            max_tokens=3000,
            temperature=0.3,
            reasoning_effort="low",
            task="report",
        )
    except GroqError:
        logger.exception("Report narrative generation failed")
        return fallback

    return {
        "summary": (payload.get("summary") or fallback["summary"]).strip(),
        "misconceptions": payload.get("misconceptions", []),
        "recommendations": payload.get("recommendations", []),
    }
