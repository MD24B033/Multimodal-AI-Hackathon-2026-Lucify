from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

MIN_EASE = 1.3
MAX_EASE = 2.8


def quality_from_score(score: float) -> int:
    if score >= 0.95:
        return 5
    if score >= 0.8:
        return 4
    if score >= 0.6:
        return 3
    if score >= 0.4:
        return 2
    if score > 0:
        return 1
    return 0


def sm2(
    ease_factor: float,
    interval_days: float,
    repetitions: int,
    score: float,
) -> tuple[float, float, int, datetime]:
    quality = quality_from_score(score)

    if quality < 3:
        repetitions = 0
        interval = 1.0
    else:
        repetitions += 1
        if repetitions == 1:
            interval = 1.0
        elif repetitions == 2:
            interval = 6.0
        else:
            interval = interval_days * ease_factor

    ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(MIN_EASE, min(MAX_EASE, ease_factor))

    interval = max(0.5, min(interval, 180.0))
    due_at = datetime.now(timezone.utc) + timedelta(days=interval)
    return ease_factor, interval, repetitions, due_at


def retention(days_since_review: float, stability_days: float) -> float:
    if stability_days <= 0:
        return 0.0
    return math.exp(-days_since_review / stability_days)


def recall_probability(last_seen_at: datetime | None, interval_days: float) -> float:
    if last_seen_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    elapsed_days = max(0.0, (now - last_seen_at).total_seconds() / 86400.0)
    stability = max(0.5, interval_days if interval_days > 0 else 1.0)
    return retention(elapsed_days, stability)


def urgency(p_known: float, last_seen_at: datetime | None, interval_days: float) -> float:
    recall = recall_probability(last_seen_at, interval_days)
    decayed_mastery = p_known * (0.4 + 0.6 * recall)
    return 1.0 - decayed_mastery
