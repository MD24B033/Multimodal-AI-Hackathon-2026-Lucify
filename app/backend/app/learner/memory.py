from __future__ import annotations

import hashlib
import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LearnerMemory, MemoryKind, Topic
from app.learner import profile as learner_profile

logger = logging.getLogger(__name__)

MAX_PROMPT_MEMORIES = 8

PREFERENCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(explain|keep it|make it)\s+(simpl|basic|easy)", re.I), "Prefers simple, plain explanations"),
    (re.compile(r"\b(in detail|more detail|deeper|thorough)\b", re.I), "Prefers detailed, thorough explanations"),
    (re.compile(r"\b(example|examples|worked example)\b", re.I), "Learns best from worked examples"),
    (re.compile(r"\b(analogy|analogies|intuition|intuitive)\b", re.I), "Responds well to analogies and intuition"),
    (re.compile(r"\b(step by step|step-by-step)\b", re.I), "Prefers step-by-step walkthroughs"),
    (re.compile(r"\b(math|maths|derivation|proof|formula)\b", re.I), "Comfortable with the mathematical detail"),
    (re.compile(r"\b(no math|skip the math|without math)\b", re.I), "Prefers to avoid heavy mathematics"),
    (re.compile(r"\b(diagram|visual|picture|figure)\b", re.I), "Learns best from diagrams and visuals"),
    (re.compile(r"\b(hindi|hinglish)\b", re.I), "Comfortable receiving explanations in Hindi or Hinglish"),
]

GOAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(exam|test|midterm|final)\b", re.I), "Studying towards an exam"),
    (re.compile(r"\b(interview|placement)\b", re.I), "Preparing for interviews"),
    (re.compile(r"\b(assignment|homework|project)\b", re.I), "Working on an assignment or project"),
    (re.compile(r"\b(revis|revision|recap)\w*\b", re.I), "Revising material already covered"),
]

CONFUSION = re.compile(
    r"\b(i don'?t (get|understand)|confus|still lost|lost me|makes no sense|explain again|samajh nahi)\b",
    re.I,
)


def _fingerprint(kind: MemoryKind, content: str, course_id: uuid.UUID | None) -> str:
    material = f"{kind.value}|{content.strip().lower()}|{course_id or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def remember(
    session: Session,
    student_id: uuid.UUID,
    kind: MemoryKind,
    content: str,
    *,
    course_id: uuid.UUID | None = None,
    origin: str = "derived",
    confidence: float = 0.6,
    evidence: dict | None = None,
) -> LearnerMemory | None:
    content = content.strip()
    if not content:
        return None

    digest = _fingerprint(kind, content, course_id)
    existing = session.scalar(
        select(LearnerMemory).where(
            LearnerMemory.student_id == student_id, LearnerMemory.fingerprint == digest
        )
    )

    if existing is not None:
        existing.confidence = min(0.98, existing.confidence + 0.08)
        if evidence:
            existing.evidence = {**(existing.evidence or {}), **evidence}
        if existing.archived:
            return existing
        session.flush()
        return existing

    memory = LearnerMemory(
        student_id=student_id,
        course_id=course_id,
        kind=kind,
        content=content,
        origin=origin,
        confidence=confidence,
        evidence=evidence or {},
        fingerprint=digest,
    )
    session.add(memory)
    session.flush()
    return memory


def observe_message(
    session: Session,
    student_id: uuid.UUID,
    message: str,
    *,
    course_id: uuid.UUID | None = None,
) -> list[LearnerMemory]:
    """Rule-based extraction from what the student typed. Costs no model tokens."""
    captured: list[LearnerMemory] = []

    for pattern, statement in PREFERENCE_PATTERNS:
        if pattern.search(message):
            memory = remember(
                session,
                student_id,
                MemoryKind.preference,
                statement,
                course_id=course_id,
                origin="chat",
                confidence=0.55,
                evidence={"quote": message[:200]},
            )
            if memory is not None:
                captured.append(memory)

    for pattern, statement in GOAL_PATTERNS:
        if pattern.search(message):
            memory = remember(
                session,
                student_id,
                MemoryKind.goal,
                statement,
                course_id=course_id,
                origin="chat",
                confidence=0.5,
                evidence={"quote": message[:200]},
            )
            if memory is not None:
                captured.append(memory)

    return captured


def observe_assessment(
    session: Session,
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    weak_topics: list[dict],
    strong_topics: list[dict],
    misconceptions: list[dict],
) -> None:
    """Derive memory from graded results. Pure data, no model call."""
    for entry in weak_topics[:3]:
        remember(
            session,
            student_id,
            MemoryKind.struggle,
            f"Finds {entry.get('topic')} difficult",
            course_id=course_id,
            origin="assessment",
            confidence=0.7,
            evidence={"accuracy": entry.get("accuracy")},
        )

    for entry in strong_topics[:2]:
        remember(
            session,
            student_id,
            MemoryKind.strength,
            f"Solid on {entry.get('topic')}",
            course_id=course_id,
            origin="assessment",
            confidence=0.65,
            evidence={"accuracy": entry.get("accuracy")},
        )

    for entry in misconceptions[:2]:
        statement = (entry.get("misconception") or "").strip()
        if statement:
            remember(
                session,
                student_id,
                MemoryKind.struggle,
                f"Misconception: {statement}",
                course_id=course_id,
                origin="assessment",
                confidence=0.75,
                evidence={"topic": entry.get("topic")},
            )


def observe_confusion(
    session: Session,
    student_id: uuid.UUID,
    message: str,
    topic_ids: list[uuid.UUID],
    course_id: uuid.UUID | None = None,
) -> None:
    if not CONFUSION.search(message) or not topic_ids:
        return

    names = session.scalars(select(Topic.name).where(Topic.id.in_(topic_ids[:2]))).all()
    for name in names:
        remember(
            session,
            student_id,
            MemoryKind.struggle,
            f"Asked for a clearer explanation of {name}",
            course_id=course_id,
            origin="chat",
            confidence=0.6,
            evidence={"quote": message[:200]},
        )


def active_memories(
    session: Session,
    student_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    limit: int = MAX_PROMPT_MEMORIES,
) -> list[LearnerMemory]:
    statement = select(LearnerMemory).where(
        LearnerMemory.student_id == student_id, LearnerMemory.archived.is_(False)
    )
    if course_id is not None:
        statement = statement.where(
            (LearnerMemory.course_id == course_id) | (LearnerMemory.course_id.is_(None))
        )
    rows = session.scalars(
        statement.order_by(
            LearnerMemory.pinned.desc(),
            LearnerMemory.confidence.desc(),
            LearnerMemory.updated_at.desc(),
        ).limit(limit)
    ).all()
    return list(rows)


def prompt_block(
    session: Session,
    student_id: uuid.UUID | None,
    course_id: uuid.UUID | None = None,
) -> str:
    if student_id is None:
        return ""

    memories = active_memories(session, student_id, course_id)
    if not memories:
        return ""

    lines = [f"- [{memory.kind.value}] {memory.content}" for memory in memories]
    return "What you have learned about this student over time:\n" + "\n".join(lines)


def summarise(session: Session, student_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    snapshot = learner_profile.snapshot(session, student_id, course_id)
    practised = [item for item in snapshot if item.attempts > 0]
    return {
        "topics_practised": len(practised),
        "mean_mastery": round(
            sum(item.p_known for item in practised) / len(practised), 3
        )
        if practised
        else None,
        "memories": len(active_memories(session, student_id, course_id, limit=200)),
    }
