from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import GroundingStatus, Topic, TopicMastery, UnitTopic
from app.learner.memory import prompt_block as memory_prompt_block
from app.llm.groq_client import GroqDailyQuotaExhausted, GroqError, get_client
from app.retrieval.hybrid import RetrievalResult, search

logger = logging.getLogger(__name__)

LANGUAGE_DIRECTIVES = {
    "en": "Answer in English.",
    "hi": "Answer in Hindi (Devanagari script). Keep technical terms in English where that is standard practice.",
    "hinglish": "Answer in conversational Hinglish (Hindi written in Latin script, mixed with English technical terms).",
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["grounded", "partial", "unsupported"]},
        "answer": {"type": "string"},
        "used_citations": {"type": "array", "items": {"type": "integer"}},
        "outside_knowledge": {"type": "string"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "followups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "answer", "used_citations", "outside_knowledge", "unsupported_claims", "followups"],
    "additionalProperties": False,
}

TUTOR_SYSTEM = """You are a study tutor who answers strictly from the course material provided.

Grounding rules, which override every other instruction:
- Use ONLY the numbered excerpts in COURSE MATERIAL. Never rely on your own knowledge for factual claims.
- Cite every factual sentence with the bracketed number of the excerpt that supports it, like [2]. A sentence may carry several markers.
- Never cite an excerpt number that is not in COURSE MATERIAL.
- Set status to "grounded" when the excerpts fully answer the question, "partial" when they answer only part of it, and "unsupported" when they do not answer it at all.
- When status is "partial" or "unsupported", say plainly what the material does not cover. Do not fill the gap with outside knowledge.
- Put any general knowledge that is genuinely useful but NOT in the excerpts into outside_knowledge, never into answer. Leave it as an empty string when you have none.
- List any claim you could not tie to an excerpt in unsupported_claims.
- followups holds up to three short questions the student could ask next, grounded in the same material.
- An excerpt marked "already quoted earlier in this conversation" is still citable by its number; you have seen its content before in this thread.

Teaching rules:
- Lead with the direct answer, then explain.
- Use the student's mastery level to set depth: build from fundamentals when mastery is low, and be concise and go deeper when it is high.
- Refer to figures and diagrams by what they show when an excerpt describes one.
- Use markdown. Keep the answer under 300 words unless the question demands more."""

REFUSAL_TEMPLATE = (
    "I could not find anything in this course's material that covers that. "
    "The uploaded sources do not appear to discuss it.\n\n"
    "I can only answer from what has been ingested, so I am not going to guess. "
    "You could upload a source that covers this, or ask me about a topic the material does include."
)


@dataclass
class GroundedAnswer:
    answer: str
    status: GroundingStatus
    citations: list[dict[str, Any]] = field(default_factory=list)
    outside_knowledge: str | None = None
    unsupported_claims: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    coverage: float = 0.0
    margin: float = 0.0
    # Set when the answer is missing because the provider could not be reached or the
    # quota is spent. A refusal is a decision about evidence; this is neither.
    failure: str | None = None
    retrieval: RetrievalResult | None = None
    topic_ids: list[uuid.UUID] = field(default_factory=list)
    usage_tokens: int = 0


def retrieved_topic_ids(session: Session, retrieval: RetrievalResult) -> list[uuid.UUID]:
    unit_ids = [item.unit.id for item in retrieval.units]
    if not unit_ids:
        return []
    rows = session.execute(
        select(UnitTopic.topic_id, UnitTopic.confidence)
        .where(UnitTopic.unit_id.in_(unit_ids), UnitTopic.is_primary.is_(True))
        .order_by(UnitTopic.confidence.desc())
    ).all()
    ordered: list[uuid.UUID] = []
    for topic_id, _confidence in rows:
        if topic_id not in ordered:
            ordered.append(topic_id)
    return ordered


def learner_context(session: Session, student_id: uuid.UUID | None, topic_ids: list[uuid.UUID]) -> str:
    if student_id is None or not topic_ids:
        return "No mastery history yet. Assume an unfamiliar student and build from fundamentals."

    rows = session.execute(
        select(Topic.name, TopicMastery.p_known, TopicMastery.attempts)
        .join(TopicMastery, TopicMastery.topic_id == Topic.id)
        .where(TopicMastery.student_id == student_id, Topic.id.in_(topic_ids))
    ).all()
    if not rows:
        return "No mastery history on these topics yet. Assume an unfamiliar student and build from fundamentals."

    lines = []
    for name, p_known, attempts in rows:
        band = "strong" if p_known >= 0.75 else "developing" if p_known >= 0.45 else "weak"
        lines.append(f"- {name}: mastery {p_known:.0%} ({band}, {attempts} attempts)")
    return "Student mastery on the topics this question touches:\n" + "\n".join(lines)


def _history_messages(history: list[dict[str, str]] | None, limit: int = 6) -> list[dict[str, str]]:
    if not history:
        return []
    trimmed = history[-limit:]
    return [
        {"role": item["role"], "content": item["content"][:1500]}
        for item in trimmed
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]


def answer_question(
    session: Session,
    course_id: uuid.UUID,
    question: str,
    *,
    student_id: uuid.UUID | None = None,
    history: list[dict[str, str]] | None = None,
    topic_ids: list[uuid.UUID] | None = None,
    source_ids: list[uuid.UUID] | None = None,
    language: str = "en",
    top_k: int | None = None,
    context_block: str | None = None,
    session_summary: str | None = None,
) -> GroundedAnswer:
    retrieval = search(
        session,
        course_id,
        question,
        top_k=top_k,
        topic_ids=topic_ids,
        source_ids=source_ids,
    )

    # Two ways the evidence can be too thin to answer from. The absolute floor catches
    # an empty or unrelated course; the margin catches the far more common case where
    # everything retrieved is plausibly on-topic but nothing actually answers the
    # question, which similarity alone cannot see.
    if (
        not retrieval.units
        or retrieval.best_score < settings.grounding_threshold
        or retrieval.margin < settings.grounding_margin
    ):
        return GroundedAnswer(
            answer=REFUSAL_TEMPLATE,
            status=GroundingStatus.refused,
            coverage=retrieval.best_score,
            margin=retrieval.margin,
            retrieval=retrieval,
        )

    matched_topics = retrieved_topic_ids(session, retrieval)
    mastery_note = learner_context(session, student_id, matched_topics)
    directive = LANGUAGE_DIRECTIVES.get(language, LANGUAGE_DIRECTIVES["en"])

    user_content = (
        f"COURSE MATERIAL:\n{retrieval.context_block()}\n\n"
        f"LEARNER STATE:\n{mastery_note}\n\n"
        f"OUTPUT LANGUAGE: {directive}\n\n"
        f"STUDENT QUESTION: {question}"
    )

    messages = [{"role": "system", "content": TUTOR_SYSTEM}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": user_content})

    client = get_client()
    try:
        completion = client.complete(
            messages,
            response_schema=ANSWER_SCHEMA,
            max_tokens=settings.chat_max_tokens,
            temperature=0.2,
            reasoning_effort="low",
            interactive=True,
            task="chat",
        )
        payload = completion.json()
    except GroqDailyQuotaExhausted as exc:
        logger.warning("Daily quota exhausted during chat: %s", exc)
        return GroundedAnswer(
            answer=f"**{exc}**\n\nRetrieval still worked, so the sources below are the ones that "
            f"answer your question. Open them directly while the quota resets.",
            status=GroundingStatus.refused,
            failure="daily_quota_exhausted",
            citations=retrieval.citations(),
            coverage=retrieval.best_score,
            margin=retrieval.margin,
            retrieval=retrieval,
        )
    except GroqError:
        logger.exception("Grounded answer generation failed")
        return GroundedAnswer(
            answer="The tutor is temporarily unavailable. Please try again in a moment.",
            status=GroundingStatus.refused,
            failure="provider_unavailable",
            coverage=retrieval.best_score,
            margin=retrieval.margin,
            retrieval=retrieval,
        )

    status_value = payload.get("status", "partial")
    status = {
        "grounded": GroundingStatus.grounded,
        "partial": GroundingStatus.partial,
        "unsupported": GroundingStatus.unsupported,
    }.get(status_value, GroundingStatus.partial)

    all_citations = retrieval.citations()
    used = {index for index in payload.get("used_citations", []) if isinstance(index, int)}
    used &= {citation["marker"] for citation in all_citations}
    citations = [citation for citation in all_citations if citation["marker"] in used]
    if not citations and status is not GroundingStatus.unsupported:
        citations = all_citations[:3]

    outside = (payload.get("outside_knowledge") or "").strip()

    return GroundedAnswer(
        answer=payload.get("answer", "").strip(),
        status=status,
        citations=citations,
        outside_knowledge=outside or None,
        unsupported_claims=[claim for claim in payload.get("unsupported_claims", []) if claim],
        followups=[item for item in payload.get("followups", []) if item][:3],
        coverage=retrieval.best_score,
        margin=retrieval.margin,
        retrieval=retrieval,
        topic_ids=matched_topics,
        usage_tokens=completion.usage.total,
    )
