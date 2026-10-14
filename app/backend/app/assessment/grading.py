from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ContentUnit, Question, QuestionType, Source
from app.llm.groq_client import GroqError, get_client
from app.retrieval.hybrid import RetrievedUnit

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"-?\d+(?:[\.,]\d+)?(?:[eE][-+]?\d+)?")

GRADING_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "is_correct": {"type": "boolean"},
        "feedback": {"type": "string"},
        "misconception": {"type": "string"},
        "cited_markers": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["score", "is_correct", "feedback", "misconception", "cited_markers"],
    "additionalProperties": False,
}

GRADING_SYSTEM = """You grade a student's answer against a model answer and the source excerpts it came from.

Rules:
- score is 0 to 1. Award partial credit for a partially right answer. A blank or irrelevant answer scores 0.
- is_correct is true only when score is at least 0.6.
- feedback speaks directly to the student in two to four sentences. Say what was right, what was wrong, and what the material actually says. Cite excerpts with bracketed numbers like [1].
- misconception names the specific wrong belief the answer reveals, in one short phrase. Use an empty string when the answer is correct or simply blank.
- cited_markers lists the excerpt numbers used in your feedback.
- Judge the substance, not the wording. Do not penalise phrasing, spelling, or missing detail the model answer also omits."""


@dataclass
class GradeResult:
    score: float
    is_correct: bool
    feedback: str
    misconception: str | None
    citations: list[dict]


def _parse_number(text: str) -> float | None:
    match = _NUMBER.search((text or "").replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _question_units(session: Session, question: Question) -> list[ContentUnit]:
    unit_ids = [uuid.UUID(value) for value in (question.source_unit_ids or []) if value]
    if not unit_ids:
        return []
    units = session.scalars(select(ContentUnit).where(ContentUnit.id.in_(unit_ids))).all()
    order = {str(unit_id): index for index, unit_id in enumerate(unit_ids)}
    return sorted(units, key=lambda unit: order.get(str(unit.id), 0))


def _context_and_citations(session: Session, units: list[ContentUnit]) -> tuple[str, list[dict]]:
    if not units:
        return "", []
    sources = {
        source.id: source
        for source in session.scalars(
            select(Source).where(Source.id.in_({unit.source_id for unit in units}))
        ).all()
    }
    blocks: list[str] = []
    citations: list[dict] = []
    for index, unit in enumerate(units, start=1):
        source = sources.get(unit.source_id)
        if source is None:
            continue
        wrapper = RetrievedUnit(unit=unit, source=source, score=0.0)
        blocks.append(f"[{index}] {source.title} — {wrapper.label()}\n{unit.text.strip()}")
        citations.append(wrapper.citation(index))
    return "\n\n".join(blocks), citations


def grade_answer(session: Session, question: Question, response: str) -> GradeResult:
    response = (response or "").strip()
    units = _question_units(session, question)
    context, citations = _context_and_citations(session, units)

    if not response:
        return GradeResult(
            score=0.0,
            is_correct=False,
            feedback=f"No answer was given. The expected answer is: {question.answer_key}",
            misconception=None,
            citations=citations,
        )

    if question.qtype is QuestionType.mcq:
        return _grade_mcq(question, response, citations)

    if question.qtype is QuestionType.numerical:
        deterministic = _grade_numerical(question, response, citations)
        if deterministic is not None:
            return deterministic

    return _grade_with_model(question, response, context, citations)


def _grade_mcq(question: Question, response: str, citations: list[dict]) -> GradeResult:
    options = question.options or []
    normalised = response.strip()
    selected = normalised

    if len(normalised) == 1 and normalised.upper().isalpha():
        index = ord(normalised.upper()) - 65
        if 0 <= index < len(options):
            selected = options[index]

    correct = selected.strip().lower() == question.answer_key.strip().lower()
    if correct:
        feedback = f"Correct. {question.answer_explanation or ''}".strip()
        misconception = None
    else:
        feedback = (
            f"Not quite. The correct answer is \"{question.answer_key}\". "
            f"{question.answer_explanation or ''}"
        ).strip()
        misconception = f"Chose \"{selected}\" over \"{question.answer_key}\""

    return GradeResult(
        score=1.0 if correct else 0.0,
        is_correct=correct,
        feedback=feedback,
        misconception=misconception,
        citations=citations,
    )


def _grade_numerical(question: Question, response: str, citations: list[dict]) -> GradeResult | None:
    expected = _parse_number(question.answer_key)
    actual = _parse_number(response)
    if expected is None or actual is None:
        return None

    tolerance = question.tolerance if question.tolerance is not None else 0.0
    if tolerance <= 0:
        tolerance = max(abs(expected) * 0.01, 1e-9)

    difference = abs(actual - expected)
    correct = difference <= tolerance

    if correct:
        feedback = f"Correct. {question.answer_explanation or ''}".strip()
        misconception = None
    else:
        unit_label = f" {question.answer_units}" if question.answer_units else ""
        feedback = (
            f"That gives {actual:g}{unit_label}, but the material supports {expected:g}{unit_label}. "
            f"{question.answer_explanation or ''}"
        ).strip()
        magnitude = abs(actual) / abs(expected) if expected else 0
        if 9 < magnitude < 11 or 0.09 < magnitude < 0.11:
            misconception = "Order-of-magnitude or unit conversion error"
        else:
            misconception = "Incorrect numerical result"

    return GradeResult(
        score=1.0 if correct else 0.0,
        is_correct=correct,
        feedback=feedback,
        misconception=misconception,
        citations=citations,
    )


def _grade_with_model(
    question: Question,
    response: str,
    context: str,
    citations: list[dict],
) -> GradeResult:
    client = get_client()
    prompt = (
        f"SOURCE EXCERPTS:\n{context or 'No excerpts available.'}\n\n"
        f"QUESTION: {question.stem}\n"
        f"MODEL ANSWER: {question.answer_key}\n"
        f"EXPLANATION: {question.answer_explanation or ''}\n\n"
        f"STUDENT ANSWER: {response}"
    )

    try:
        payload = client.complete_json(
            [
                {"role": "system", "content": GRADING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            schema=GRADING_SCHEMA,
            max_tokens=2000,
            temperature=0.1,
            reasoning_effort="low",
            task="grading",
        )
    except GroqError:
        logger.exception("Model grading failed for question %s", question.id)
        overlap = _token_overlap(response, question.answer_key)
        return GradeResult(
            score=overlap,
            is_correct=overlap >= 0.6,
            feedback=f"Expected answer: {question.answer_key}",
            misconception=None,
            citations=citations,
        )

    score = max(0.0, min(1.0, float(payload.get("score") or 0.0)))
    markers = {marker for marker in payload.get("cited_markers", []) if isinstance(marker, int)}
    used = [citation for citation in citations if citation["marker"] in markers] or citations
    misconception = (payload.get("misconception") or "").strip()

    return GradeResult(
        score=score,
        is_correct=bool(payload.get("is_correct")) and score >= 0.6,
        feedback=(payload.get("feedback") or "").strip(),
        misconception=misconception or None,
        citations=used,
    )


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.lower().split())
    right_tokens = set(right.lower().split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(right_tokens)
