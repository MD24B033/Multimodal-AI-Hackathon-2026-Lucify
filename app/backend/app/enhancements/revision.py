from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Flashcard, RevisionAsset, Topic
from app.learner import profile, scheduler
from app.llm.groq_client import GroqError, get_client
from app.retrieval.hybrid import search

logger = logging.getLogger(__name__)

FLASHCARD_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                    "source_markers": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["front", "back", "source_markers"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}

FLASHCARD_SYSTEM = """You write revision flashcards from course excerpts.

Rules:
- front is a single question or prompt. Keep it under 20 words.
- back is the answer in one to three sentences, drawn only from the excerpts.
- source_markers lists the excerpt numbers that support the card.
- Each card tests one idea. Do not write cards that merely restate a definition's wording.
- Never use information that is not in the excerpts."""

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "script": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "source_markers": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["title", "script", "key_points", "source_markers"],
    "additionalProperties": False,
}

BRIEF_SYSTEM = """You write a short spoken revision brief for a student who is weak on a topic.

Rules:
- script is plain spoken prose, 150 to 220 words, suitable for reading aloud. No markdown, no bullet characters, no bracket citations in the script itself.
- Open by naming the topic, explain the core idea, then give the one thing most students get wrong.
- key_points lists three to five short takeaways.
- source_markers lists the excerpt numbers the brief draws on.
- Use only what the excerpts contain."""


def generate_flashcards(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    topic_id: uuid.UUID,
    count: int = 6,
) -> list[Flashcard]:
    topic = session.get(Topic, topic_id)
    if topic is None:
        return []

    query = f"{topic.name}. {topic.summary or ''}".strip()
    retrieval = search(session, course_id, query, top_k=6, topic_ids=[topic_id])
    if not retrieval.units:
        retrieval = search(session, course_id, query, top_k=6)
    if not retrieval.units:
        return []

    citations = retrieval.citations()
    try:
        payload = get_client().complete_json(
            [
                {"role": "system", "content": FLASHCARD_SYSTEM},
                {
                    "role": "user",
                    "content": f"SOURCE EXCERPTS:\n{retrieval.context_block()}\n\n"
                    f"Topic: {topic.name}\nWrite {count} flashcards.",
                },
            ],
            schema=FLASHCARD_SCHEMA,
            max_tokens=4000,
            temperature=0.4,
            reasoning_effort="low",
            task="flashcards",
        )
    except GroqError:
        logger.exception("Flashcard generation failed for topic %s", topic_id)
        return []

    created: list[Flashcard] = []
    for entry in payload.get("cards", [])[:count]:
        front = (entry.get("front") or "").strip()
        back = (entry.get("back") or "").strip()
        if not front or not back:
            continue
        markers = {marker for marker in entry.get("source_markers", []) if isinstance(marker, int)}
        card_citations = [citation for citation in citations if citation["marker"] in markers]
        card = Flashcard(
            student_id=student_id,
            course_id=course_id,
            topic_id=topic_id,
            front=front,
            back=back,
            citations=card_citations or citations[:1],
            due_at=datetime.now(timezone.utc),
        )
        session.add(card)
        created.append(card)

    session.commit()
    return created


def review_flashcard(session: Session, card_id: uuid.UUID, score: float) -> Flashcard | None:
    card = session.get(Flashcard, card_id)
    if card is None:
        return None

    ease, interval, repetitions, due_at = scheduler.sm2(
        card.ease_factor, card.interval_days, card.repetitions, score
    )
    card.ease_factor = ease
    card.interval_days = interval
    card.repetitions = repetitions
    card.due_at = due_at

    if card.topic_id is not None:
        profile.record_response(
            session,
            card.student_id,
            card.topic_id,
            score=score,
            difficulty="easy",
            kind="flashcard",
            propagate=False,
        )

    session.commit()
    return card


def due_flashcards(
    session: Session,
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    limit: int = 20,
) -> list[Flashcard]:
    now = datetime.now(timezone.utc)
    return list(
        session.scalars(
            select(Flashcard)
            .where(
                Flashcard.student_id == student_id,
                Flashcard.course_id == course_id,
                (Flashcard.due_at.is_(None)) | (Flashcard.due_at <= now),
            )
            .order_by(Flashcard.due_at.nulls_first())
            .limit(limit)
        ).all()
    )


def generate_audio_brief(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    topic_id: uuid.UUID,
    *,
    synthesize: bool = True,
) -> RevisionAsset | None:
    from app.enhancements.tts import synthesize_to_file

    topic = session.get(Topic, topic_id)
    if topic is None:
        return None

    retrieval = search(
        session, course_id, f"{topic.name}. {topic.summary or ''}".strip(), top_k=6, topic_ids=[topic_id]
    )
    if not retrieval.units:
        return None

    citations = retrieval.citations()
    try:
        payload = get_client().complete_json(
            [
                {"role": "system", "content": BRIEF_SYSTEM},
                {
                    "role": "user",
                    "content": f"SOURCE EXCERPTS:\n{retrieval.context_block()}\n\nTopic: {topic.name}",
                },
            ],
            schema=BRIEF_SCHEMA,
            max_tokens=3000,
            temperature=0.4,
            reasoning_effort="low",
            task="audio_brief",
        )
    except GroqError:
        logger.exception("Audio brief generation failed for topic %s", topic_id)
        return None

    script = (payload.get("script") or "").strip()
    if not script:
        return None

    markers = {marker for marker in payload.get("source_markers", []) if isinstance(marker, int)}
    used = [citation for citation in citations if citation["marker"] in markers] or citations[:2]

    asset = RevisionAsset(
        student_id=student_id,
        course_id=course_id,
        topic_id=topic_id,
        kind="audio_brief",
        title=(payload.get("title") or f"{topic.name} refresher").strip(),
        payload={
            "script": script,
            "key_points": payload.get("key_points", []),
            "citations": used,
        },
    )
    session.add(asset)
    session.flush()

    if synthesize:
        audio_path = synthesize_to_file(script, f"brief_{asset.id}")
        if audio_path is not None:
            asset.audio_path = str(audio_path)

    session.commit()
    return asset


def revision_pack(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    topic_limit: int = 3,
    cards_per_topic: int = 5,
    with_audio: bool = False,
) -> dict:
    weak = profile.weak_topics(session, student_id, course_id, limit=topic_limit)
    if not weak:
        return {"topics": [], "cards": 0, "briefs": 0}

    summary = []
    total_cards = 0
    briefs = 0

    for item in weak:
        cards = generate_flashcards(
            session, course_id, student_id, item.topic_id, count=cards_per_topic
        )
        total_cards += len(cards)
        entry = {
            "topic_id": str(item.topic_id),
            "topic": item.topic_name,
            "mastery": round(item.p_known, 3),
            "cards": len(cards),
        }
        if with_audio:
            asset = generate_audio_brief(session, course_id, student_id, item.topic_id)
            if asset is not None:
                briefs += 1
                entry["brief_id"] = str(asset.id)
        summary.append(entry)

    return {"topics": summary, "cards": total_cards, "briefs": briefs}
