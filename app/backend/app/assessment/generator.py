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
from app.assessment.verifier import verify_batch
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
                    "target": {"type": "string"},
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
                    "target",
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
- Each request lists one or more targets, each with an id like T1, how many questions it wants and at what difficulty. Put that id in "target" and honour the per-target counts.
- Write questions a student could answer without seeing the excerpts, using only knowledge of the subject."""


@dataclass
class TopicPlan:
    """One target for a generation call: a topic (or the whole course), how many
    questions it should contribute, and the difficulty chosen for it."""

    topic: "Topic | None"
    count: int
    difficulty: str

    @property
    def label(self) -> str:
        return self.topic.name if self.topic is not None else "the course material as a whole"


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


def _already_asked(
    session: Session, course_id: uuid.UUID, topics: list["Topic | None"], limit: int = 14
) -> list[str]:
    """Stems already in the bank for these topics, newest first.

    Bounded deliberately: the point is to steer away from the obvious repeats, not to
    hand the model the whole history at a few tokens per line.
    """
    topic_ids = [topic.id for topic in topics if topic is not None]
    statement = select(Question.stem).where(Question.course_id == course_id)
    if topic_ids:
        statement = statement.where(Question.topic_id.in_(topic_ids))
    stems = session.scalars(
        statement.order_by(Question.created_at.desc()).limit(limit)
    ).all()
    return [stem.strip()[:110] for stem in stems if stem and stem.strip()]


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
    """One target. Kept for the top-up path, which asks for whatever a quiz is short."""
    return generate_for_plan(
        session,
        course_id,
        [TopicPlan(topic=topic, count=count, difficulty=difficulty)],
        qtypes=qtypes,
        source_ids=source_ids,
        novelty=novelty,
        verify=verify,
        stats=stats,
    )


def generate_for_plan(
    session: Session,
    course_id: uuid.UUID,
    plan: list[TopicPlan],
    *,
    qtypes: list[str],
    source_ids: list[uuid.UUID] | None,
    novelty: NoveltyFilter,
    verify: bool,
    stats: GenerationStats,
) -> list[Question]:
    """Every target in one call.

    A quiz used to cost one generation call per topic, each carrying its own copy of
    the system prompt and its own excerpts, and each booking its own reservation
    against an 8,000 token minute. Three topics therefore spilled across minute
    windows before a single question came back. The excerpts for the targets overlap
    anyway, so sending them once is both cheaper and gives the model a wider view.
    """
    plan = [item for item in plan if item.count > 0]
    if not plan:
        return []

    units: list[ContentUnit] = []
    seen_units: set[uuid.UUID] = set()
    targets: list[tuple[str, TopicPlan]] = []
    for index, item in enumerate(plan, start=1):
        found = _units_for_topic(
            session, course_id, item.topic.id if item.topic else None, source_ids, MAX_UNITS_PER_BATCH
        )
        if not found:
            continue
        targets.append((f"T{index}", item))
        for unit in found:
            if unit.id not in seen_units:
                seen_units.add(unit.id)
                units.append(unit)

    if not units or not targets:
        return []

    context, mapping = _context_block(session, units)
    embedder = get_embedder()
    client = get_client()

    topic_by_target = {key: item.topic for key, item in targets}
    wanted = sum(item.count for _key, item in targets)
    target_lines = "\n".join(
        f"  {key}: {item.label} - {item.count} question(s) at {item.difficulty} difficulty"
        for key, item in targets
    )
    asked = _already_asked(session, course_id, [item.topic for _key, item in targets])
    avoid_block = ""
    if asked:
        listed = "\n".join(f"  - {stem}" for stem in asked)
        avoid_block = (
            f"ALREADY ASKED - do not repeat these or rephrase them:\n{listed}\n\n"
            "Cover different ideas, or the same idea from a genuinely different angle.\n\n"
        )

    request = (
        f"SOURCE EXCERPTS:\n{context}\n\n"
        f"{avoid_block}"
        f"TARGETS:\n{target_lines}\n\n"
        f"Write {wanted + 2} questions in total, honouring each target's count, and put the "
        f"target id in the \"target\" field of every question.\n"
        f"Allowed question types: {', '.join(qtypes)}. Spread them across the allowed types."
    )
    count = wanted

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
        logger.exception(
            "Question generation failed for %s", ", ".join(item.label for _key, item in targets)
        )
        return []

    # Two phases. Everything that can reject a candidate for free -- schema, option
    # count, novelty -- runs first, so the verifier is only asked about questions that
    # could still survive, and is asked about all of them at once.
    # The model is asked for count + 2, and the spare two are what absorb a
    # verification failure without leaving the quiz short.
    candidates: list[dict] = []
    for entry in payload.get("questions", []):
        if len(candidates) >= count + 2:
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

        candidates.append(
            {
                "entry": entry,
                "qtype": qtype,
                "stem": stem,
                "answer": answer,
                "options": options,
                "vector": vector,
                "cited_units": cited_units,
                "target": str(entry.get("target") or "").strip().upper(),
            }
        )

    if not candidates:
        return []

    if verify:
        verdicts = verify_batch(
            [
                {
                    "qtype": candidate["qtype"].value,
                    "stem": candidate["stem"],
                    "options": candidate["options"],
                    "answer_key": candidate["answer"],
                    "answer_explanation": candidate["entry"].get("explanation"),
                }
                for candidate in candidates
            ],
            context,
        )
    else:
        verdicts = [None] * len(candidates)

    produced: list[Question] = []
    for candidate, result in zip(candidates, verdicts):
        if len(produced) >= count:
            break
        entry = candidate["entry"]
        qtype = candidate["qtype"]
        stem = candidate["stem"]
        answer = candidate["answer"]
        options = candidate["options"]
        vector = candidate["vector"]
        cited_units = candidate["cited_units"]

        is_still_novel, _similarity = novelty.check(stem, answer, vector)
        if not is_still_novel:
            stats.rejected_duplicate += 1
            continue

        if result is None:
            verification = {"passed": False, "skipped": True}
        elif not result.passed and result.error is None:
            stats.rejected_verification += 1
            stats.verification_issues.extend(result.issues[:2])
            continue
        else:
            verification = result.as_dict()

        target_topic = topic_by_target.get(candidate["target"])
        resolved_topic_id = (
            target_topic.id if target_topic is not None else _infer_topic_id(session, cited_units)
        )

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
        # Only a question that survived verification enters the novelty filter. Telling
        # the filter about a candidate before the verdict would let a rejected question
        # block its own replacement, and every later batch's.
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

    # Spread the questions over the chosen topics, then ask for all of them at once.
    # Difficulty is still decided per topic from that topic's own mastery estimate --
    # the batching changes how many calls it takes, not what is asked for.
    plan: list[TopicPlan] = []
    remaining = num_questions
    for position, topic in enumerate(targets):
        if remaining <= 0:
            break
        share = -(-remaining // (len(targets) - position))
        if difficulty:
            target_difficulty = difficulty
        elif topic is not None and kind is not AssessmentKind.diagnostic:
            mastery = profile.get_or_create_mastery(session, student_id, topic.id)
            target_difficulty = irt.target_difficulty(mastery.theta)
        else:
            target_difficulty = "medium"
        plan.append(TopicPlan(topic=topic, count=share, difficulty=target_difficulty))
        remaining -= share

    collected: list[Question] = generate_for_plan(
        session,
        course_id,
        plan,
        qtypes=qtypes,
        source_ids=source_ids,
        novelty=novelty,
        verify=verify,
        stats=stats,
    )
    covered = {
        question.topic_id for question in collected if question.topic_id is not None
    }
    stats.topics_covered.extend(
        topic.name for topic in targets if topic is not None and topic.id in covered
    )

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
