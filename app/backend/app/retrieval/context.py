from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import ChatMessage, ChatSession
from app.llm.groq_client import GroqError, get_client
from app.retrieval.hybrid import RetrievalResult, RetrievedUnit

logger = logging.getLogger(__name__)

RECENT_TURNS = 2
SUMMARISE_EVERY = 6
SUMMARY_MAX_TOKENS = 400

SUMMARY_SYSTEM = """Compress a tutoring conversation into a brief running memo.

Keep only what changes how the next answer should be written:
- what the student is trying to understand
- what they already grasp, and where they got stuck
- any constraint they stated (format, language, depth, deadline)

Write at most 90 words of plain prose. No preamble, no bullet characters."""


@dataclass
class BuiltContext:
    fresh: list[RetrievedUnit] = field(default_factory=list)
    recalled: list[RetrievedUnit] = field(default_factory=list)
    block: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    tokens_saved: int = 0

    @property
    def all_units(self) -> list[RetrievedUnit]:
        return self.fresh + self.recalled


def _estimate(text: str) -> int:
    return max(1, len(text) // 4)


def build_context(
    session: Session,
    chat: ChatSession,
    retrieval: RetrievalResult,
    *,
    max_chars: int = 9000,
) -> BuiltContext:
    """Send full text only for excerpts this session has not seen yet. Excerpts already
    shown stay citable by a one-line reference, which keeps follow-up turns cheap."""
    seen: set[str] = {str(value) for value in (chat.seen_unit_ids or [])}

    fresh: list[RetrievedUnit] = []
    recalled: list[RetrievedUnit] = []
    for item in retrieval.units:
        if str(item.unit.id) in seen:
            recalled.append(item)
        else:
            fresh.append(item)

    blocks: list[str] = []
    used = 0
    saved = 0

    for index, item in enumerate(retrieval.units, start=1):
        header = f"[{index}] {item.source.title} — {item.label()}"
        if item in recalled:
            blocks.append(f"{header}\n(already quoted earlier in this conversation)")
            saved += _estimate(item.unit.text)
            continue

        body = item.unit.text.strip()
        candidate = f"{header}\n{body}"
        if used + len(candidate) > max_chars:
            blocks.append(f"{header}\n(omitted for length)")
            continue
        blocks.append(candidate)
        used += len(candidate)

    history, summary = _history(session, chat)

    return BuiltContext(
        fresh=fresh,
        recalled=recalled,
        block="\n\n".join(blocks),
        history=history,
        summary=summary,
        tokens_saved=saved,
    )


def _history(session: Session, chat: ChatSession) -> tuple[list[dict[str, str]], str]:
    messages = (
        session.query(ChatMessage)
        .filter(ChatMessage.session_id == chat.id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    recent = messages[-(RECENT_TURNS * 2) :] if messages else []
    history = [
        {"role": message.role, "content": message.content[:1200]}
        for message in recent
        if message.role in {"user", "assistant"}
    ]
    return history, (chat.summary or "")


def maybe_summarise(session: Session, chat: ChatSession) -> None:
    """Fold older turns into a short memo so history stops growing linearly."""
    total = (
        session.query(ChatMessage).filter(ChatMessage.session_id == chat.id).count()
    )
    if total - chat.summarised_upto < SUMMARISE_EVERY:
        return

    messages = (
        session.query(ChatMessage)
        .filter(ChatMessage.session_id == chat.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    foldable = messages[: max(0, total - RECENT_TURNS * 2)]
    if not foldable:
        return

    transcript = "\n".join(
        f"{message.role}: {message.content[:600]}" for message in foldable
    )
    prior = f"Existing memo:\n{chat.summary}\n\n" if chat.summary else ""

    try:
        completion = get_client().complete(
            [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": f"{prior}Conversation so far:\n{transcript[:6000]}"},
            ],
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=0.2,
            reasoning_effort="low",
            task="session_summary",
        )
    except GroqError:
        logger.debug("Session summary failed", exc_info=True)
        return

    summary = completion.text.strip()
    if summary:
        chat.summary = summary[:1500]
        chat.summarised_upto = len(foldable)
        session.flush()


def remember_units(session: Session, chat: ChatSession, units: list[RetrievedUnit]) -> None:
    seen = list(chat.seen_unit_ids or [])
    known = set(seen)
    for item in units:
        key = str(item.unit.id)
        if key not in known:
            seen.append(key)
            known.add(key)
    chat.seen_unit_ids = seen[-120:]
    session.flush()


def reset_context(session: Session, chat: ChatSession) -> None:
    chat.seen_unit_ids = []
    chat.summary = None
    chat.summarised_upto = 0
    session.flush()
