from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Concept, RevisionAsset, Topic
from app.llm.groq_client import GroqError, get_client
from app.retrieval.hybrid import RetrievalResult, search

logger = logging.getLogger(__name__)


class NotesGenerationFailed(RuntimeError):
    pass

NOTE_FORMATS = ("summary", "cornell", "cheatsheet", "flashcards")

DEPTH_GUIDANCE = {
    "brief": "Keep it tight: only the essentials, roughly 250 words of body text.",
    "standard": "Cover the topic properly in roughly 500 words of body text.",
    "deep": "Be thorough: include derivations, edge cases and worked detail, up to 900 words.",
}

BASE_RULES = """You write study notes strictly from the numbered course excerpts you are given.

Absolute rules:
- Use ONLY the excerpts. Never add facts from your own knowledge.
- Cite with bracketed excerpt numbers like [2] on any line that states something factual.
- Never cite a number that does not appear in the excerpts.
- If the excerpts do not cover part of the requested topic, say so in the gaps field rather than inventing content."""

FORMAT_RULES = {
    "summary": """Produce structured study notes in markdown.
Use `##` headings for sections, bullets for detail, and bold for key terms.
Open with a two-sentence overview, then the sections, then a short "Worked example" section if the excerpts contain one.""",
    "cornell": """Produce Cornell-style notes.
`cues` holds 5 to 9 short recall prompts, each a question or key term.
`body` holds the matching detailed notes in markdown, in the same order as the cues.
`summary_strip` is a 2 to 3 sentence synthesis of the whole topic.""",
    "cheatsheet": """Produce a dense one-page cheat sheet in markdown.
Formulas, definitions and key facts only. Minimal prose, no full sentences where a fragment will do.
Group under short `###` headings. Put equations in display form on their own lines.""",
    "flashcards": """Produce question and answer pairs for active recall.
`cards` holds 8 to 14 cards. Each front is one question under 20 words; each back is a 1 to 3 sentence answer.
Each card tests exactly one idea. Do not write cards that merely restate a definition verbatim.""",
}

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "string"},
        "body": {"type": "string"},
        "cues": {"type": "array", "items": {"type": "string"}},
        "summary_strip": {"type": "string"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                },
                "required": ["front", "back"],
                "additionalProperties": False,
            },
        },
        "key_terms": {"type": "array", "items": {"type": "string"}},
        "used_citations": {"type": "array", "items": {"type": "integer"}},
        "gaps": {"type": "string"},
    },
    "required": [
        "title",
        "overview",
        "body",
        "cues",
        "summary_strip",
        "cards",
        "key_terms",
        "used_citations",
        "gaps",
    ],
    "additionalProperties": False,
}


def _resolve_scope(
    session: Session,
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    concept_id: uuid.UUID | None,
    free_text: str | None,
) -> tuple[str, list[uuid.UUID] | None, str]:
    if concept_id is not None:
        concept = session.get(Concept, concept_id)
        if concept is not None:
            return (
                f"{concept.name}. {concept.definition or ''}".strip(),
                [concept.topic_id],
                concept.name,
            )

    if topic_id is not None:
        topic = session.get(Topic, topic_id)
        if topic is not None:
            children = session.scalars(
                select(Topic.id).where(Topic.parent_id == topic.id)
            ).all()
            return (
                f"{topic.name}. {topic.summary or ''}".strip(),
                [topic.id, *children],
                topic.name,
            )

    query = (free_text or "").strip()
    return query, None, query or "Course notes"


def generate_notes(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    note_format: str = "summary",
    topic_id: uuid.UUID | None = None,
    concept_id: uuid.UUID | None = None,
    free_text: str | None = None,
    source_ids: list[uuid.UUID] | None = None,
    depth: str = "standard",
    language: str = "en",
    extra_instructions: str | None = None,
    persist: bool = True,
) -> dict[str, Any] | None:
    if note_format not in NOTE_FORMATS:
        raise ValueError(f"Unsupported note format: {note_format}")

    query, topic_filter, label = _resolve_scope(
        session, course_id, topic_id, concept_id, free_text
    )
    if not query:
        raise ValueError("Give a topic, a concept, or some text describing what the notes cover")

    retrieval: RetrievalResult = search(
        session,
        course_id,
        query,
        top_k=settings.notes_top_k,
        topic_ids=topic_filter,
        source_ids=source_ids,
    )
    if not retrieval.units and topic_filter:
        retrieval = search(session, course_id, query, top_k=settings.notes_top_k, source_ids=source_ids)
    if not retrieval.units:
        return None

    citations = retrieval.citations()
    language_directive = {
        "en": "Write in English.",
        "hi": "Write in Hindi (Devanagari). Keep technical terms in English where that is standard.",
        "hinglish": "Write in Hinglish: Hindi in Latin script mixed with English technical terms.",
    }.get(language, "Write in English.")

    instructions = [
        BASE_RULES,
        "",
        FORMAT_RULES[note_format],
        "",
        DEPTH_GUIDANCE.get(depth, DEPTH_GUIDANCE["standard"]),
        language_directive,
    ]
    if extra_instructions:
        instructions.append(f"Additional instruction from the student: {extra_instructions.strip()}")

    unused = [
        field
        for field, needed in {
            "cues": note_format == "cornell",
            "summary_strip": note_format == "cornell",
            "cards": note_format == "flashcards",
        }.items()
        if not needed
    ]
    if unused:
        instructions.append(
            f"Leave these fields empty, they do not apply to this format: {', '.join(unused)}."
        )

    try:
        payload = get_client().complete_json(
            [
                {"role": "system", "content": "\n".join(instructions)},
                {
                    "role": "user",
                    "content": f"COURSE EXCERPTS:\n{retrieval.context_block(max_chars=settings.notes_context_chars)}\n\n"
                    f"Write {note_format} notes on: {label}",
                },
            ],
            schema=NOTES_SCHEMA,
            max_tokens=settings.notes_max_tokens,
            temperature=0.3,
            reasoning_effort="low",
            interactive=True,
            task="notes",
        )
    except GroqError as exc:
        logger.exception("Note generation failed for %s", label)
        raise NotesGenerationFailed(
            "The model could not finish writing these notes. Try a narrower topic, "
            "or a briefer depth."
        ) from exc

    used = {marker for marker in payload.get("used_citations", []) if isinstance(marker, int)}
    used &= {citation["marker"] for citation in citations}
    cited = [citation for citation in citations if citation["marker"] in used] or citations[:4]

    result = {
        "format": note_format,
        "title": (payload.get("title") or label).strip(),
        "overview": (payload.get("overview") or "").strip(),
        "body": (payload.get("body") or "").strip(),
        "cues": [item for item in payload.get("cues", []) if item],
        "summary_strip": (payload.get("summary_strip") or "").strip(),
        "cards": [
            card
            for card in payload.get("cards", [])
            if card.get("front") and card.get("back")
        ],
        "key_terms": [term for term in payload.get("key_terms", []) if term],
        "gaps": (payload.get("gaps") or "").strip(),
        "citations": cited,
        "topic_id": str(topic_id) if topic_id else None,
        "depth": depth,
        "language": language,
    }

    if persist:
        asset = RevisionAsset(
            student_id=student_id,
            course_id=course_id,
            topic_id=topic_id,
            kind=f"notes_{note_format}",
            title=result["title"][:300],
            payload=result,
        )
        session.add(asset)
        session.commit()
        result["id"] = str(asset.id)

    return result


def list_notes(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    limit: int = 30,
) -> list[dict[str, Any]]:
    assets = session.scalars(
        select(RevisionAsset)
        .where(
            RevisionAsset.course_id == course_id,
            RevisionAsset.student_id == student_id,
            RevisionAsset.kind.like("notes_%"),
        )
        .order_by(RevisionAsset.created_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": str(asset.id),
            "title": asset.title,
            "format": asset.kind.removeprefix("notes_"),
            "topic_id": str(asset.topic_id) if asset.topic_id else None,
            "created_at": asset.created_at.isoformat(),
            "payload": asset.payload,
        }
        for asset in assets
    ]


def export_markdown(note: dict[str, Any]) -> str:
    note_format = note.get("format", "summary")
    lines = [f"# {note.get('title', 'Notes')}", ""]

    if note.get("overview"):
        lines.extend([note["overview"], ""])

    if note_format == "cornell":
        lines.append("| Cue | Notes |")
        lines.append("|---|---|")
        body_parts = [part.strip() for part in (note.get("body") or "").split("\n\n") if part.strip()]
        for index, cue in enumerate(note.get("cues", [])):
            detail = body_parts[index] if index < len(body_parts) else ""
            lines.append(f"| {cue} | {detail.replace(chr(10), ' ')} |")
        if note.get("summary_strip"):
            lines.extend(["", "**Summary**", "", note["summary_strip"]])
    elif note_format == "flashcards":
        for index, card in enumerate(note.get("cards", []), start=1):
            lines.extend([f"**{index}. {card['front']}**", "", card["back"], ""])
    else:
        lines.append(note.get("body", ""))

    if note.get("key_terms"):
        lines.extend(["", "## Key terms", ""])
        lines.extend(f"- {term}" for term in note["key_terms"])

    if note.get("gaps"):
        lines.extend(["", "## Not covered by the material", "", note["gaps"]])

    if note.get("citations"):
        lines.extend(["", "## Sources", ""])
        for citation in note["citations"]:
            lines.append(
                f"- [{citation.get('marker', '?')}] {citation['source_title']} — {citation['label']}"
            )

    return "\n".join(lines)
