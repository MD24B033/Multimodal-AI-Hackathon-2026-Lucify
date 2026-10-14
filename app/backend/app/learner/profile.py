from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Interaction,
    Topic,
    TopicKind,
    TopicMastery,
    TopicPrerequisite,
)
from app.learner import bkt, irt, scheduler

PREREQUISITE_PROPAGATION = 0.25
PARENT_PROPAGATION = 0.35
WEAK_THRESHOLD = 0.5
STRONG_THRESHOLD = 0.75


@dataclass
class MasterySnapshot:
    topic_id: uuid.UUID
    topic_name: str
    kind: str
    p_known: float
    theta: float
    attempts: int
    correct: int
    due_at: datetime | None
    last_seen_at: datetime | None
    recall: float
    urgency: float
    parent_id: uuid.UUID | None
    interval_days: float = 0.0


def get_or_create_mastery(session: Session, student_id: uuid.UUID, topic_id: uuid.UUID) -> TopicMastery:
    record = session.scalar(
        select(TopicMastery).where(
            TopicMastery.student_id == student_id, TopicMastery.topic_id == topic_id
        )
    )
    if record is None:
        record = TopicMastery(student_id=student_id, topic_id=topic_id)
        session.add(record)
        session.flush()
    return record


def _decayed_prior(record: TopicMastery) -> float:
    if record.last_seen_at is None:
        return record.p_known
    last_seen = record.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    elapsed_days = max(0.0, (datetime.now(timezone.utc) - last_seen).total_seconds() / 86400.0)
    return bkt.apply_forgetting(record.p_known, elapsed_days)


def record_response(
    session: Session,
    student_id: uuid.UUID,
    topic_id: uuid.UUID,
    *,
    score: float,
    difficulty: str | None = None,
    kind: str = "quiz_answer",
    propagate: bool = True,
    meta: dict | None = None,
) -> tuple[float, float]:
    record = get_or_create_mastery(session, student_id, topic_id)
    prior = _decayed_prior(record)

    if score >= 0.999:
        updated = bkt.update(prior, True, difficulty)
    elif score <= 0.001:
        updated = bkt.update(prior, False, difficulty)
    else:
        updated = bkt.update_partial(prior, score, difficulty)

    record.p_known = updated
    record.attempts += 1
    if score >= 0.5:
        record.correct += 1
    record.last_seen_at = datetime.now(timezone.utc)

    ease, interval, repetitions, due_at = scheduler.sm2(
        record.ease_factor, record.interval_days, record.repetitions, score
    )
    record.ease_factor = ease
    record.interval_days = interval
    record.repetitions = repetitions
    record.due_at = due_at

    session.add(
        Interaction(
            student_id=student_id,
            topic_id=topic_id,
            kind=kind,
            correct=score >= 0.5,
            score=score,
            difficulty=difficulty,
            p_known_before=prior,
            p_known_after=updated,
            meta=meta or {},
        )
    )

    if propagate:
        _propagate(session, student_id, topic_id, prior, updated)

    session.flush()
    return prior, updated


def _propagate(
    session: Session,
    student_id: uuid.UUID,
    topic_id: uuid.UUID,
    prior: float,
    updated: float,
) -> None:
    delta = updated - prior
    if abs(delta) < 0.01:
        return

    topic = session.get(Topic, topic_id)
    if topic is not None and topic.parent_id is not None:
        parent = get_or_create_mastery(session, student_id, topic.parent_id)
        parent.p_known = max(0.01, min(0.99, parent.p_known + delta * PARENT_PROPAGATION))

    if delta >= 0:
        return

    prerequisite_ids = session.scalars(
        select(TopicPrerequisite.prerequisite_id).where(TopicPrerequisite.topic_id == topic_id)
    ).all()
    for prerequisite_id in prerequisite_ids:
        record = get_or_create_mastery(session, student_id, prerequisite_id)
        record.p_known = max(0.01, min(0.99, record.p_known + delta * PREREQUISITE_PROPAGATION))


def update_theta(session: Session, student_id: uuid.UUID, topic_id: uuid.UUID) -> float:
    rows = session.execute(
        select(Interaction.correct, Interaction.difficulty)
        .where(
            Interaction.student_id == student_id,
            Interaction.topic_id == topic_id,
            Interaction.correct.isnot(None),
        )
        .order_by(Interaction.created_at)
        .limit(60)
    ).all()
    if not rows:
        return 0.0

    responses = [
        irt.Response(difficulty=irt.difficulty_to_value(difficulty), discrimination=1.0, correct=bool(correct))
        for correct, difficulty in rows
    ]
    theta, standard_error = irt.estimate_theta(responses)

    record = get_or_create_mastery(session, student_id, topic_id)
    record.theta = theta
    record.theta_se = standard_error
    session.flush()
    return theta


def record_chat_signal(
    session: Session,
    student_id: uuid.UUID,
    topic_ids: list[uuid.UUID],
    *,
    confusion: bool,
    weight: float = 0.35,
) -> None:
    for topic_id in topic_ids[:3]:
        record = get_or_create_mastery(session, student_id, topic_id)
        prior = _decayed_prior(record)
        direction = -1.0 if confusion else 1.0
        adjusted = prior + direction * weight * (0.12 if confusion else 0.06)
        record.p_known = max(0.01, min(0.99, adjusted))
        record.last_seen_at = datetime.now(timezone.utc)
        session.add(
            Interaction(
                student_id=student_id,
                topic_id=topic_id,
                kind="chat_turn",
                correct=None if confusion else True,
                score=0.0 if confusion else 0.6,
                p_known_before=prior,
                p_known_after=record.p_known,
                meta={"signal": "confusion" if confusion else "engagement"},
            )
        )
    session.flush()


def snapshot(session: Session, student_id: uuid.UUID, course_id: uuid.UUID) -> list[MasterySnapshot]:
    rows = session.execute(
        select(Topic, TopicMastery)
        .outerjoin(
            TopicMastery,
            (TopicMastery.topic_id == Topic.id) & (TopicMastery.student_id == student_id),
        )
        .where(Topic.course_id == course_id)
        .order_by(Topic.ordinal, Topic.name)
    ).all()

    snapshots: list[MasterySnapshot] = []
    for topic, mastery in rows:
        p_known = mastery.p_known if mastery else 0.25
        interval = mastery.interval_days if mastery else 0.0
        last_seen = mastery.last_seen_at if mastery else None
        snapshots.append(
            MasterySnapshot(
                topic_id=topic.id,
                topic_name=topic.name,
                kind=topic.kind.value if isinstance(topic.kind, TopicKind) else str(topic.kind),
                p_known=p_known,
                theta=mastery.theta if mastery else 0.0,
                attempts=mastery.attempts if mastery else 0,
                correct=mastery.correct if mastery else 0,
                due_at=mastery.due_at if mastery else None,
                last_seen_at=last_seen,
                recall=scheduler.recall_probability(last_seen, interval),
                urgency=scheduler.urgency(p_known, last_seen, interval),
                parent_id=topic.parent_id,
                interval_days=interval,
            )
        )
    return snapshots


def weak_topics(
    session: Session,
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    limit: int = 5,
    include_untouched: bool = True,
) -> list[MasterySnapshot]:
    items = snapshot(session, student_id, course_id)
    candidates = [
        item
        for item in items
        if item.p_known < WEAK_THRESHOLD and (include_untouched or item.attempts > 0)
    ]
    candidates.sort(key=lambda item: (-item.urgency, item.p_known))
    return candidates[:limit]


def overall_mastery(session: Session, student_id: uuid.UUID, course_id: uuid.UUID) -> float:
    items = [item for item in snapshot(session, student_id, course_id) if item.kind == "subtopic"]
    if not items:
        items = snapshot(session, student_id, course_id)
    if not items:
        return 0.0
    return sum(item.p_known for item in items) / len(items)
