from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import StudyPlan, Topic, TopicPrerequisite
from app.learner import profile, scheduler

MIN_BLOCK_MINUTES = 20
REVIEW_OFFSETS_DAYS = (1, 3, 7, 16)


def _topic_order(session: Session, course_id: uuid.UUID, snapshots: list) -> list:
    edges = session.execute(
        select(TopicPrerequisite.topic_id, TopicPrerequisite.prerequisite_id)
    ).all()
    prerequisite_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for topic_id, prerequisite_id in edges:
        prerequisite_map.setdefault(topic_id, set()).add(prerequisite_id)

    mastery = {item.topic_id: item.p_known for item in snapshots}

    def sort_key(item):
        blockers = sum(
            1
            for prerequisite in prerequisite_map.get(item.topic_id, set())
            if mastery.get(prerequisite, 0.25) < 0.5
        )
        return (blockers, -item.urgency, item.p_known)

    return sorted(snapshots, key=sort_key)


def build_study_plan(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    exam_date: date,
    daily_minutes: int = 60,
) -> StudyPlan:
    today = datetime.now(timezone.utc).date()
    days_available = max(1, (exam_date - today).days)

    snapshots = [
        item
        for item in profile.snapshot(session, student_id, course_id)
        if item.kind == "subtopic"
    ]
    if not snapshots:
        snapshots = profile.snapshot(session, student_id, course_id)

    ordered = _topic_order(session, course_id, snapshots)
    weak_first = [item for item in ordered if item.p_known < 0.75]
    if not weak_first:
        weak_first = ordered

    total_weight = sum(max(0.15, 1.0 - item.p_known) for item in weak_first) or 1.0
    total_minutes = days_available * daily_minutes
    study_minutes = int(total_minutes * 0.72)

    allocations: list[dict] = []
    for item in weak_first:
        weight = max(0.15, 1.0 - item.p_known)
        minutes = int(study_minutes * weight / total_weight)
        if minutes < MIN_BLOCK_MINUTES:
            minutes = MIN_BLOCK_MINUTES
        allocations.append(
            {
                "topic_id": item.topic_id,
                "topic": item.topic_name,
                "mastery": round(item.p_known, 3),
                "recall": round(item.recall, 3),
                "minutes": minutes,
            }
        )

    sessions: list[dict] = []
    day_index = 0
    remaining_today = daily_minutes
    current_day = today

    for allocation in allocations:
        minutes_left = allocation["minutes"]
        while minutes_left > 0 and day_index < days_available:
            block = min(minutes_left, remaining_today, 45)
            if block < MIN_BLOCK_MINUTES and remaining_today < MIN_BLOCK_MINUTES:
                day_index += 1
                current_day = today + timedelta(days=day_index)
                remaining_today = daily_minutes
                continue

            sessions.append(
                {
                    "date": current_day.isoformat(),
                    "topic_id": str(allocation["topic_id"]),
                    "topic": allocation["topic"],
                    "minutes": block,
                    "activity": "learn" if allocation["mastery"] < 0.45 else "practice",
                    "reason": f"mastery {allocation['mastery']:.0%}, recall {allocation['recall']:.0%}",
                }
            )
            minutes_left -= block
            remaining_today -= block

            if remaining_today < MIN_BLOCK_MINUTES:
                day_index += 1
                current_day = today + timedelta(days=day_index)
                remaining_today = daily_minutes

        if day_index >= days_available:
            break

    first_touch: dict[str, date] = {}
    for item in sessions:
        first_touch.setdefault(item["topic_id"], date.fromisoformat(item["date"]))

    for topic_id, touched in first_touch.items():
        topic_name = next(
            (item["topic"] for item in sessions if item["topic_id"] == topic_id), "Topic"
        )
        for offset in REVIEW_OFFSETS_DAYS:
            review_day = touched + timedelta(days=offset)
            if review_day >= exam_date or review_day <= today:
                continue
            sessions.append(
                {
                    "date": review_day.isoformat(),
                    "topic_id": topic_id,
                    "topic": topic_name,
                    "minutes": 15,
                    "activity": "review",
                    "reason": f"spaced review at day +{offset} against the forgetting curve",
                }
            )

    sessions.sort(key=lambda item: (item["date"], item["activity"]))

    rationale = (
        f"{days_available} days until the exam at {daily_minutes} minutes per day. "
        f"Time is weighted toward {len(weak_first)} topics below full mastery, ordered so prerequisites "
        f"come first, with spaced reviews at +1, +3, +7 and +16 days to counter forgetting."
    )

    plan = session.scalar(
        select(StudyPlan).where(
            StudyPlan.student_id == student_id, StudyPlan.course_id == course_id
        )
    )
    if plan is None:
        plan = StudyPlan(student_id=student_id, course_id=course_id)
        session.add(plan)

    plan.exam_date = exam_date
    plan.daily_minutes = daily_minutes
    plan.sessions = sessions
    plan.rationale = rationale
    session.commit()
    return plan


def retention_forecast(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    horizon_days: int = 21,
) -> list[dict]:
    snapshots = profile.snapshot(session, student_id, course_id)
    forecast: list[dict] = []

    for day in range(0, horizon_days + 1, 3):
        total = 0.0
        counted = 0
        for item in snapshots:
            if item.attempts == 0:
                continue
            decay = scheduler.retention(day, max(1.0, item.interval_days))
            total += item.p_known * (0.4 + 0.6 * decay)
            counted += 1
        forecast.append(
            {
                "day": day,
                "projected_mastery": round(total / counted, 3) if counted else None,
            }
        )
    return forecast
