from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Assessment,
    AssessmentItem,
    AssessmentKind,
    AssessmentStatus,
    Concept,
    ContentUnit,
    Difficulty,
    Question,
    QuestionType,
    Source,
    Topic,
    UnitTopic,
)
from app.assessment.novelty import NoveltyFilter, fingerprint
from app.assessment.verifier import verify_question
from app.learner import irt, profile
from app.llm.groq_client import GroqError, get_client
from app.retrieval.embedder import get_embedder
from app.retrieval.hybrid import RetrievedUnit

logger = logging.getLogger(__name__)

MAX_UNITS_PER_BATCH = 5
MAX_ATTEMPTS_PER_TOPIC = 2

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "qtype": {"type": "string", "enum": ["mcq", "short_answer", "numerical"]},
                    "stem": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "source_markers": {"type": "array", "items": {"type": "integer"}},
                    "concept": {"type": "string"},
                    "tolerance": {"type": "number"},
                    "answer_units": {"type": "string"},
                },
                "required": [
                    "qtype",
                    "stem",
                    "options",
                    "answer",
                    "explanation",
                    "difficulty",
                    "source_markers",
                    "concept",
                    "tolerance",
                    "answer_units",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

GENERATOR_SYSTEM = """You write exam questions from course material. Every question must be answerable from the numbered excerpts alone.

Rules:
- Base each question on specific content in the excerpts. Never use outside knowledge.
- source_markers lists the excerpt numbers that support the question and its answer. Never cite a number that is not shown.
- For "mcq", give exactly 4 options, with exactly one defensibly correct. Distractors must be plausible and wrong for a stated reason, not absurd. Put the full text of the correct option in answer.
- For "short_answer", answer is a concise model answer of one to three sentences. Leave options empty.
- For "numerical", the excerpts must contain the numbers needed. answer is the numeric result as a string, tolerance is the acceptable absolute error, and answer_units is the unit or an empty string. Leave options empty.
- explanation states why the answer is right and points at the excerpt that shows it.
- Ask about the subject matter itself, never about the documents. Questions such as "according to the spec, which item is NOT listed", "what does slide 4 show", or "which of these does the document mention" are forbidden. A student must be able to answer from understanding the concept, without having the document in front of them.
- Do not use the words "according to", "the document", "the slide", "the text", or "the spec" in a stem.
- Test understanding, not recall of incidental detail. These are forbidden: the name or signature of a helper function in a code sample, how many items a particular dataset split contains, an author's rhetorical aside, a figure's caption wording, notation a single source happens to use.
- A good question asks why something works, what would happen if a quantity changed, how two ideas relate, or makes the student apply a method. Prefer "what happens to the gradient if the learning rate is too large" over "what value of eta is used in the example".
- Set tolerance to 0 for non-numerical questions and answer_units to an empty string.
- Write questions a student could answer without seeing the excerpts, using only knowledge of the subject."""


@dataclass
class GenerationStats:
    requested: int = 0
    generated: int = 0
    rejected_duplicate: int = 0
    rejected_verification: int = 0
    verification_issues: list[str] = field(default_factory=list)
    topics_covered: list[str] = field(default_factory=list)


def _difficulty_enum(value: str | None) -> Difficulty:
    try:
        return Difficulty((value or "medium").lower())
    except ValueError:
        return Difficulty.medium


def _qtype_enum(value: str | None) -> QuestionType:
    try:
        return QuestionType((value or "mcq").lower())
    except ValueError:
        return QuestionType.mcq


def _units_for_topic(
    session: Session,
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    source_ids: list[uuid.UUID] | None,
    limit: int,
) -> list[ContentUnit]:
    statement = select(ContentUnit).where(ContentUnit.course_id == course_id)
    if topic_id is not None:
        unit_ids = session.scalars(
            select(UnitTopic.unit_id)
            .where(UnitTopic.topic_id == topic_id)
            .order_by(UnitTopic.confidence.desc())
        ).all()
        if not unit_ids:
            return []
        statement = statement.where(ContentUnit.id.in_(unit_ids))
    if source_ids:
        statement = statement.where(ContentUnit.source_id.in_(source_ids))

    units = session.scalars(statement.order_by(func.random()).limit(limit * 3)).all()
    units = [unit for unit in units if unit.token_count > 25]
    random.shuffle(units)
    return units[:limit]


def _context_block(session: Session, units: list[ContentUnit]) -> tuple[str, dict[int, ContentUnit]]:
    source_ids = {unit.source_id for unit in units}
    sources = {
        source.id: source
        for source in session.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }
    mapping: dict[int, ContentUnit] = {}
    blocks: list[str] = []
    for index, unit in enumerate(units, start=1):
        mapping[index] = unit
        source = sources.get(unit.source_id)
        wrapper = RetrievedUnit(unit=unit, source=source, score=0.0)
        header = f"[{index}] {source.title if source else 'Source'} — {wrapper.label()}"
        blocks.append(f"{header}\n{unit.text.strip()}")
    return "\n\n".join(blocks), mapping


def _citations_for(session: Session, units: list[ContentUnit]) -> list[dict]:
    sources = {
        source.id: source
        for source in session.scalars(
            select(Source).where(Source.id.in_({unit.source_id for unit in units}))
        ).all()
    }
    citations = []
    for index, unit in enumerate(units, start=1):
        source = sources.get(unit.source_id)
        if source is None:
            continue
        citations.append(RetrievedUnit(unit=unit, source=source, score=0.0).citation(index))
    return citations


def _budget_for(count: int, qtypes: list[str]) -> int:
    """Groq admits a request against prompt + max_completion_tokens, so a flat ceiling
    reserves the whole per-minute budget whatever the model actually writes. Sizing the
    ask to the questions requested is what keeps a short quiz short — and a truncated
    object is retried with double the headroom, so an underestimate costs nothing."""
    per_question = 300 if "mcq" in qtypes else 190
    estimate = 320 + per_question * max(1, count)
    return max(700, min(estimate, settings.generation_max_tokens))


def generate_for_topic(
    session: Session,
    course_id: uuid.UUID,
    topic: Topic | None,
    *,
    count: int,
    qtypes: list[str],
    difficulty: str,
    source_ids: list[uuid.UUID] | None,
    novelty: NoveltyFilter,
    verify: bool,
    stats: GenerationStats,
) -> list[Question]:
    units = _units_for_topic(session, course_id, topic.id if topic else None, source_ids, MAX_UNITS_PER_BATCH)
    if not units:
        return []

    context, mapping = _context_block(session, units)
    embedder = get_embedder()
    client = get_client()

    topic_line = f"Target topic: {topic.name}" if topic else "Target: the course material as a whole"
    request = (
        f"SOURCE EXCERPTS:\n{context}\n\n"
        f"{topic_line}\n"
        f"Write {count + 2} questions at {difficulty} difficulty.\n"
        f"Allowed question types: {', '.join(qtypes)}. Spread them across the allowed types."
    )

    try:
        payload = client.complete_json(
            [
                {"role": "system", "content": GENERATOR_SYSTEM},
                {"role": "user", "content": request},
            ],
            schema=QUESTION_SCHEMA,
            max_tokens=_budget_for(count, qtypes),
            temperature=0.65,
            reasoning_effort="low",
            use_cache=False,
            task="question_generation",
        )
    except GroqError:
        logger.exception("Question generation failed for topic %s", topic.name if topic else "course")
        return []

    produced: list[Question] = []
    for entry in payload.get("questions", []):
        if len(produced) >= count:
            break

        stem = (entry.get("stem") or "").strip()
        answer = (entry.get("answer") or "").strip()
        if not stem or not answer:
            continue

        qtype = _qtype_enum(entry.get("qtype"))
        options = [str(option).strip() for option in (entry.get("options") or []) if str(option).strip()]
        if qtype is QuestionType.mcq:
            if len(options) != 4 or answer not in options:
                continue
        else:
            options = None

        vector = embedder.embed_documents([stem])[0]
        is_novel, similarity = novelty.check(stem, answer, vector)
        if not is_novel:
            stats.rejected_duplicate += 1
            continue

        markers = [marker for marker in entry.get("source_markers", []) if marker in mapping]
        cited_units = [mapping[marker] for marker in markers] or units[:2]

        if verify:
            result = verify_question(
                {
                    "qtype": qtype.value,
                    "stem": stem,
                    "options": options,
                    "answer_key": answer,
                    "answer_explanation": entry.get("explanation"),
                },
                _context_for_units(session, cited_units),
            )
            if not result.passed and result.error is None:
                stats.rejected_verification += 1
                stats.verification_issues.extend(result.issues[:2])
                continue
            verification = result.as_dict()
        else:
            verification = {"passed": False, "skipped": True}

        resolved_topic_id = topic.id if topic is not None else _infer_topic_id(session, cited_units)

        difficulty_label = _difficulty_enum(entry.get("difficulty"))
        concept_name = (entry.get("concept") or "").strip()
        concept_id = None
        if concept_name and resolved_topic_id is not None:
            concept = session.scalar(
                select(Concept).where(
                    Concept.course_id == course_id,
                    Concept.name.ilike(concept_name),
                )
            )
            concept_id = concept.id if concept else None

        question = Question(
            course_id=course_id,
            topic_id=resolved_topic_id,
            concept_id=concept_id,
            qtype=qtype,
            stem=stem,
            options=options,
            answer_key=answer,
            answer_explanation=(entry.get("explanation") or "").strip() or None,
            tolerance=float(entry.get("tolerance") or 0.0) if qtype is QuestionType.numerical else None,
            answer_units=(entry.get("answer_units") or "").strip() or None,
            difficulty=difficulty_label,
            irt_difficulty=irt.difficulty_to_value(difficulty_label.value),
            source_unit_ids=[str(unit.id) for unit in cited_units],
            citations=_citations_for(session, cited_units),
            verified=bool(verification.get("passed")),
            verification=verification,
            fingerprint=fingerprint(stem, answer),
            embedding=vector,
        )
        session.add(question)
        novelty.accept(stem, answer, vector)
        produced.append(question)
        stats.generated += 1

    session.flush()
    return produced


def _infer_topic_id(session: Session, units: list[ContentUnit]) -> uuid.UUID | None:
    if not units:
        return None
    rows = session.execute(
        select(UnitTopic.topic_id, func.sum(UnitTopic.confidence).label("weight"))
        .join(Topic, Topic.id == UnitTopic.topic_id)
        .where(UnitTopic.unit_id.in_([unit.id for unit in units]), Topic.kind == "subtopic")
        .group_by(UnitTopic.topic_id)
        .order_by(func.sum(UnitTopic.confidence).desc())
        .limit(1)
    ).first()
    if rows is not None:
        return rows[0]

    fallback = session.execute(
        select(UnitTopic.topic_id, func.sum(UnitTopic.confidence).label("weight"))
        .where(UnitTopic.unit_id.in_([unit.id for unit in units]))
        .group_by(UnitTopic.topic_id)
        .order_by(func.sum(UnitTopic.confidence).desc())
        .limit(1)
    ).first()
    return fallback[0] if fallback is not None else None


def _context_for_units(session: Session, units: list[ContentUnit]) -> str:
    context, _ = _context_block(session, units)
    return context


def select_target_topics(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    topic_ids: list[uuid.UUID] | None,
    adaptive: bool,
    limit: int,
) -> list[Topic]:
    if topic_ids:
        topics = session.scalars(select(Topic).where(Topic.id.in_(topic_ids))).all()
        return list(topics)

    eligible = {topic.id: topic for topic in topics_with_content(session, course_id, limit=200)}
    if not eligible:
        return []

    if adaptive:
        weak = profile.weak_topics(session, student_id, course_id, limit=limit * 3)
        targeted = [eligible[item.topic_id] for item in weak if item.topic_id in eligible]
        if targeted:
            return targeted[:limit]

    return topics_with_content(session, course_id, limit)


def topics_with_content(session: Session, course_id: uuid.UUID, limit: int, minimum_units: int = 2) -> list[Topic]:
    counts = session.execute(
        select(UnitTopic.topic_id, func.count(UnitTopic.unit_id).label("units"))
        .join(Topic, Topic.id == UnitTopic.topic_id)
        .where(Topic.course_id == course_id)
        .group_by(UnitTopic.topic_id)
        .having(func.count(UnitTopic.unit_id) >= minimum_units)
    ).all()
    if not counts:
        return []

    topic_ids = [row[0] for row in counts]
    topics = session.scalars(select(Topic).where(Topic.id.in_(topic_ids))).all()
    subtopics = [topic for topic in topics if topic.kind.value == "subtopic"] or list(topics)
    random.shuffle(subtopics)
    return subtopics[:limit]


def create_assessment(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    title: str | None = None,
    kind: AssessmentKind = AssessmentKind.quiz,
    num_questions: int = 6,
    topic_ids: list[uuid.UUID] | None = None,
    source_ids: list[uuid.UUID] | None = None,
    qtypes: list[str] | None = None,
    difficulty: str | None = None,
    adaptive: bool = True,
    verify: bool = True,
) -> tuple[Assessment, GenerationStats]:
    qtypes = qtypes or ["mcq", "short_answer"]
    stats = GenerationStats(requested=num_questions)

    topics = select_target_topics(
        session,
        course_id,
        student_id,
        topic_ids=topic_ids,
        adaptive=adaptive and kind is not AssessmentKind.diagnostic,
        limit=max(2, min(num_questions, 5)),
    )

    novelty = NoveltyFilter(session, course_id)
    assessment = Assessment(
        course_id=course_id,
        student_id=student_id,
        title=title or _default_title(kind),
        kind=kind,
        status=AssessmentStatus.in_progress,
        adaptive=adaptive,
        scope={
            "topic_ids": [str(topic.id) for topic in topics],
            "source_ids": [str(sid) for sid in (source_ids or [])],
            "qtypes": qtypes,
            "requested": num_questions,
        },
    )
    session.add(assessment)
    session.flush()

    targets: list[Topic | None] = list(topics) or [None]
    per_topic = max(1, -(-num_questions // len(targets)))
    collected: list[Question] = []

    for topic in targets:
        if len(collected) >= num_questions:
            break
        want = min(per_topic, num_questions - len(collected))

        if difficulty:
            target_difficulty = difficulty
        elif topic is not None and kind is not AssessmentKind.diagnostic:
            mastery = profile.get_or_create_mastery(session, student_id, topic.id)
            target_difficulty = irt.target_difficulty(mastery.theta)
        else:
            target_difficulty = "medium"

        produced = generate_for_topic(
            session,
            course_id,
            topic,
            count=want,
            qtypes=qtypes,
            difficulty=target_difficulty,
            source_ids=source_ids,
            novelty=novelty,
            verify=verify,
            stats=stats,
        )
        collected.extend(produced)
        if topic is not None and produced:
            stats.topics_covered.append(topic.name)

    if len(collected) < num_questions:
        collected.extend(
            generate_for_topic(
                session,
                course_id,
                None,
                count=num_questions - len(collected),
                qtypes=qtypes,
                difficulty=difficulty or "medium",
                source_ids=source_ids,
                novelty=novelty,
                verify=verify,
                stats=stats,
            )
        )

    for ordinal, question in enumerate(collected[:num_questions]):
        question.times_used += 1
        session.add(
            AssessmentItem(assessment_id=assessment.id, question_id=question.id, ordinal=ordinal)
        )

    session.commit()
    return assessment, stats


def _default_title(kind: AssessmentKind) -> str:
    return {
        AssessmentKind.quiz: "Practice quiz",
        AssessmentKind.mock_exam: "Mock exam",
        AssessmentKind.diagnostic: "Diagnostic check",
    }.get(kind, "Assessment")
