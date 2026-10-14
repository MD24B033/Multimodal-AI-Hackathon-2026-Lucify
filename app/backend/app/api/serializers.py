from __future__ import annotations

from typing import Any

from app.db.models import (
    Assessment,
    AssessmentItem,
    AssessmentReport,
    ChatMessage,
    ContentUnit,
    Course,
    Flashcard,
    IngestionJob,
    Question,
    Source,
    Student,
    StudyPlan,
)
from app.learner.profile import MasterySnapshot


def serialize_course(course: Course, extra: dict[str, Any] | None = None) -> dict:
    payload = {
        "id": str(course.id),
        "profile_id": str(course.profile_id) if course.profile_id else None,
        "title": course.title,
        "description": course.description,
        "exam_date": course.exam_date.isoformat() if course.exam_date else None,
        "start_date": course.start_date.isoformat() if course.start_date else None,
        "weekly_hours": course.weekly_hours,
        "difficulty": course.difficulty,
        "goal": course.goal,
        "created_at": course.created_at.isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload


def serialize_source(source: Source, job: IngestionJob | None = None) -> dict:
    payload = {
        "id": str(source.id),
        "course_id": str(source.course_id),
        "kind": source.kind.value,
        "status": source.status.value,
        "title": source.title,
        "original_filename": source.original_filename,
        "external_url": source.external_url,
        "page_count": source.page_count,
        "duration_seconds": source.duration_seconds,
        "error": source.error,
        "meta": source.meta or {},
        "created_at": source.created_at.isoformat(),
    }
    if job is not None:
        payload["job"] = {
            "status": job.status.value,
            "stage": job.stage,
            "progress": round(job.progress, 3),
            "detail": job.detail or {},
            "error": job.error,
        }
    return payload


def serialize_unit(unit: ContentUnit) -> dict:
    return {
        "id": str(unit.id),
        "source_id": str(unit.source_id),
        "modality": unit.modality.value,
        "text": unit.text,
        "heading_path": unit.heading_path or [],
        "page_no": unit.page_no,
        "slide_no": unit.slide_no,
        "start_time_s": unit.start_time_s,
        "end_time_s": unit.end_time_s,
        "has_image": bool(unit.image_path),
        "figure_caption": unit.figure_caption,
        "token_count": unit.token_count,
    }


def serialize_message(message: ChatMessage) -> dict:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "citations": message.citations or [],
        "grounding_status": message.grounding_status.value if message.grounding_status else None,
        "coverage": message.coverage,
        # The passages the generator actually saw. Scoring retrieval from `citations`
        # measures which of them the model chose to mention, which is a different
        # property and a much harsher one.
        "retrieved_unit_ids": message.retrieved_unit_ids or [],
        "outside_knowledge": message.outside_knowledge,
        "language": message.language,
        "audio_url": f"/api/media/audio/{message.id}" if message.audio_path else None,
        "latency_ms": message.latency_ms,
        "created_at": message.created_at.isoformat(),
    }


def serialize_question(question: Question, include_answer: bool = False) -> dict:
    payload = {
        "id": str(question.id),
        "qtype": question.qtype.value,
        "stem": question.stem,
        "options": question.options,
        "difficulty": question.difficulty.value,
        "topic_id": str(question.topic_id) if question.topic_id else None,
        "citations": question.citations or [],
        "verified": question.verified,
        "answer_units": question.answer_units,
    }
    if include_answer:
        payload.update(
            {
                "answer_key": question.answer_key,
                "answer_explanation": question.answer_explanation,
                "verification": question.verification or {},
                "tolerance": question.tolerance,
            }
        )
    return payload


def serialize_item(item: AssessmentItem, question: Question, reveal: bool) -> dict:
    payload = {
        "id": str(item.id),
        "ordinal": item.ordinal,
        "question": serialize_question(question, include_answer=reveal),
        "response": item.response,
    }
    if reveal:
        payload.update(
            {
                "is_correct": item.is_correct,
                "score": item.score,
                "feedback": item.feedback,
                "feedback_citations": item.feedback_citations or [],
                "misconception": item.misconception,
            }
        )
    return payload


def serialize_assessment(
    assessment: Assessment,
    items: list[tuple[AssessmentItem, Question]] | None = None,
    reveal: bool | None = None,
) -> dict:
    graded = assessment.status.value == "graded"
    reveal = graded if reveal is None else reveal
    payload = {
        "id": str(assessment.id),
        "course_id": str(assessment.course_id),
        "student_id": str(assessment.student_id),
        "title": assessment.title,
        "kind": assessment.kind.value,
        "status": assessment.status.value,
        "scope": assessment.scope or {},
        "adaptive": assessment.adaptive,
        "created_at": assessment.created_at.isoformat(),
        "submitted_at": assessment.submitted_at.isoformat() if assessment.submitted_at else None,
    }
    if items is not None:
        payload["items"] = [serialize_item(item, question, reveal) for item, question in items]
        payload["question_count"] = len(items)
    return payload


def serialize_report(report: AssessmentReport) -> dict:
    return {
        "id": str(report.id),
        "assessment_id": str(report.assessment_id),
        "summary": report.summary,
        "score_percent": report.score_percent,
        "weak_topics": report.weak_topics or [],
        "strong_topics": report.strong_topics or [],
        "misconceptions": report.misconceptions or [],
        "recommendations": report.recommendations or [],
        "mastery_delta": report.mastery_delta or [],
        "created_at": report.created_at.isoformat(),
    }


def serialize_student(student: Student) -> dict:
    return {
        "id": str(student.id),
        "name": student.name,
        "email": student.email,
        "preferred_language": student.preferred_language,
        "onboarded_at": student.onboarded_at.isoformat() if student.onboarded_at else None,
        "is_simulated": student.is_simulated,
        "meta": student.meta or {},
    }


def serialize_mastery(item: MasterySnapshot) -> dict:
    return {
        "topic_id": str(item.topic_id),
        "topic": item.topic_name,
        "kind": item.kind,
        "parent_id": str(item.parent_id) if item.parent_id else None,
        "mastery": round(item.p_known, 4),
        "theta": round(item.theta, 4),
        "attempts": item.attempts,
        "correct": item.correct,
        "recall": round(item.recall, 4),
        "urgency": round(item.urgency, 4),
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
    }


def serialize_flashcard(card: Flashcard, reveal: bool = True) -> dict:
    payload = {
        "id": str(card.id),
        "front": card.front,
        "topic_id": str(card.topic_id) if card.topic_id else None,
        "citations": card.citations or [],
        "due_at": card.due_at.isoformat() if card.due_at else None,
        "repetitions": card.repetitions,
        "interval_days": round(card.interval_days, 2),
    }
    if reveal:
        payload["back"] = card.back
    return payload


def serialize_plan(plan: StudyPlan) -> dict:
    return {
        "id": str(plan.id),
        "exam_date": plan.exam_date.isoformat(),
        "daily_minutes": plan.daily_minutes,
        "sessions": plan.sessions or [],
        "rationale": plan.rationale,
        "created_at": plan.created_at.isoformat(),
    }
