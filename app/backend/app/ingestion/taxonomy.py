from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Concept,
    ContentUnit,
    Modality,
    Topic,
    TopicKind,
    TopicPrerequisite,
    UnitConcept,
    UnitTopic,
)
from app.llm.groq_client import GroqError, get_client
from app.retrieval.embedder import get_embedder

logger = logging.getLogger(__name__)

DIGEST_CHAR_BUDGET = 14000
PRIMARY_TAG_THRESHOLD = 0.34
SECONDARY_TAG_THRESHOLD = 0.46

TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "subtopics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "summary": {"type": "string"},
                                "concepts": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "summary", "concepts"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "summary", "subtopics"],
                "additionalProperties": False,
            },
        },
        "prerequisites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "requires": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["topic", "requires", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["topics", "prerequisites"],
    "additionalProperties": False,
}

TAXONOMY_SYSTEM = """You are a curriculum architect. You are given excerpts from one course's material.
Produce the course's topic structure.

Rules:
- Identify 4 to 9 major topics that genuinely appear in the excerpts.
- Give each major topic 2 to 5 subtopics, and each subtopic 2 to 6 key concepts.
- Concepts are short noun phrases a student would be tested on, not sentences.
- Prerequisite edges connect topics or subtopics by their exact names from your own output. Only assert a prerequisite when understanding one genuinely requires the other.
- Never invent material that is not present in the excerpts."""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:280] or "topic"


def _build_digest(units: list[ContentUnit]) -> str:
    by_section: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        heading = " > ".join(unit.heading_path) if unit.heading_path else "(no section)"
        by_section[heading].append(unit.text)

    lines: list[str] = []
    budget = DIGEST_CHAR_BUDGET
    per_section = max(400, budget // max(1, len(by_section)))

    for heading, texts in by_section.items():
        if budget <= 0:
            break
        body = " ".join(texts)[:per_section]
        block = f"## {heading}\n{body}"
        lines.append(block)
        budget -= len(block)
    return "\n\n".join(lines)


def _existing_topic_names(session: Session, course_id: uuid.UUID) -> dict[str, Topic]:
    rows = session.scalars(select(Topic).where(Topic.course_id == course_id)).all()
    return {topic.name.strip().lower(): topic for topic in rows}


def build_taxonomy(session: Session, course_id: uuid.UUID) -> dict:
    units = session.scalars(
        select(ContentUnit).where(ContentUnit.course_id == course_id).order_by(ContentUnit.ordinal)
    ).all()
    if not units:
        return {"topics": 0, "concepts": 0, "prerequisites": 0}

    digest = _build_digest(units)
    client = get_client()
    try:
        payload = client.complete_json(
            [
                {"role": "system", "content": TAXONOMY_SYSTEM},
                {"role": "user", "content": f"Course excerpts:\n\n{digest}"},
            ],
            schema=TAXONOMY_SCHEMA,
            max_tokens=7000,
            temperature=0.1,
            reasoning_effort="low",
            task="taxonomy",
        )
    except GroqError:
        logger.exception("Taxonomy extraction failed")
        return {"topics": 0, "concepts": 0, "prerequisites": 0, "error": "taxonomy_failed"}

    embedder = get_embedder()
    existing = _existing_topic_names(session, course_id)
    created_topics = 0
    created_concepts = 0
    name_to_topic: dict[str, Topic] = dict(existing)

    for order, entry in enumerate(payload.get("topics", [])):
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        major = name_to_topic.get(key)
        if major is None:
            major = Topic(
                course_id=course_id,
                name=name,
                slug=slugify(name),
                kind=TopicKind.major,
                summary=(entry.get("summary") or "").strip() or None,
                ordinal=order,
            )
            session.add(major)
            session.flush()
            created_topics += 1
            name_to_topic[key] = major

        for sub_order, sub in enumerate(entry.get("subtopics", [])):
            sub_name = (sub.get("name") or "").strip()
            if not sub_name:
                continue
            sub_key = sub_name.lower()
            subtopic = name_to_topic.get(sub_key)
            if subtopic is None:
                subtopic = Topic(
                    course_id=course_id,
                    name=sub_name,
                    slug=slugify(f"{name}-{sub_name}"),
                    kind=TopicKind.subtopic,
                    parent_id=major.id,
                    summary=(sub.get("summary") or "").strip() or None,
                    ordinal=sub_order,
                )
                session.add(subtopic)
                session.flush()
                created_topics += 1
                name_to_topic[sub_key] = subtopic

            for concept_name in sub.get("concepts", []):
                concept_name = (concept_name or "").strip()
                if not concept_name:
                    continue
                exists = session.scalar(
                    select(Concept).where(
                        Concept.course_id == course_id,
                        Concept.topic_id == subtopic.id,
                        Concept.name == concept_name,
                    )
                )
                if exists is None:
                    session.add(
                        Concept(course_id=course_id, topic_id=subtopic.id, name=concept_name)
                    )
                    created_concepts += 1

    session.flush()

    created_edges = 0
    for edge in payload.get("prerequisites", []):
        target = name_to_topic.get((edge.get("topic") or "").strip().lower())
        requirement = name_to_topic.get((edge.get("requires") or "").strip().lower())
        if target is None or requirement is None or target.id == requirement.id:
            continue
        exists = session.scalar(
            select(TopicPrerequisite).where(
                TopicPrerequisite.topic_id == target.id,
                TopicPrerequisite.prerequisite_id == requirement.id,
            )
        )
        if exists is None:
            session.add(
                TopicPrerequisite(
                    topic_id=target.id,
                    prerequisite_id=requirement.id,
                    rationale=(edge.get("reason") or "").strip() or None,
                )
            )
            created_edges += 1

    session.flush()
    _embed_taxonomy(session, course_id, embedder)
    session.commit()

    return {"topics": created_topics, "concepts": created_concepts, "prerequisites": created_edges}


def _embed_taxonomy(session: Session, course_id: uuid.UUID, embedder) -> None:
    topics = session.scalars(
        select(Topic).where(Topic.course_id == course_id, Topic.embedding.is_(None))
    ).all()
    if topics:
        texts = [f"{topic.name}. {topic.summary or ''}".strip() for topic in topics]
        for topic, vector in zip(topics, embedder.embed_documents(texts)):
            topic.embedding = vector

    concepts = session.scalars(
        select(Concept).where(Concept.course_id == course_id, Concept.embedding.is_(None))
    ).all()
    if concepts:
        texts = [f"{concept.name}. {concept.definition or ''}".strip() for concept in concepts]
        for concept, vector in zip(concepts, embedder.embed_documents(texts)):
            concept.embedding = vector
    session.flush()


def tag_units(session: Session, course_id: uuid.UUID, unit_ids: list[uuid.UUID] | None = None) -> dict:
    embedder = get_embedder()
    topics = session.scalars(
        select(Topic).where(Topic.course_id == course_id, Topic.embedding.isnot(None))
    ).all()
    if not topics:
        return {"tagged": 0, "links": 0}

    query = select(ContentUnit).where(ContentUnit.course_id == course_id)
    if unit_ids:
        query = query.where(ContentUnit.id.in_(unit_ids))
    units = session.scalars(query).all()

    concepts = session.scalars(
        select(Concept).where(Concept.course_id == course_id, Concept.embedding.isnot(None))
    ).all()

    topic_vectors = [topic.embedding for topic in topics]
    concept_vectors = [concept.embedding for concept in concepts]

    tagged = 0
    links = 0
    concept_links = 0

    for unit in units:
        if unit.embedding is None:
            continue
        scores = sorted(
            (
                (embedder.similarity(unit.embedding, vector), topic)
                for vector, topic in zip(topic_vectors, topics)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scores or scores[0][0] < PRIMARY_TAG_THRESHOLD:
            continue

        session.query(UnitTopic).filter(UnitTopic.unit_id == unit.id).delete()
        best_score, best_topic = scores[0]
        session.add(
            UnitTopic(unit_id=unit.id, topic_id=best_topic.id, confidence=float(best_score), is_primary=True)
        )
        links += 1
        tagged += 1

        if best_topic.parent_id is not None:
            session.add(
                UnitTopic(
                    unit_id=unit.id,
                    topic_id=best_topic.parent_id,
                    confidence=float(best_score) * 0.9,
                    is_primary=False,
                )
            )
            links += 1

        seen = {best_topic.id, best_topic.parent_id}
        for score, topic in scores[1:4]:
            if score < SECONDARY_TAG_THRESHOLD or topic.id in seen:
                continue
            session.add(
                UnitTopic(unit_id=unit.id, topic_id=topic.id, confidence=float(score), is_primary=False)
            )
            seen.add(topic.id)
            links += 1

        if concept_vectors:
            concept_scores = sorted(
                (
                    (embedder.similarity(unit.embedding, vector), concept)
                    for vector, concept in zip(concept_vectors, concepts)
                ),
                key=lambda pair: pair[0],
                reverse=True,
            )
            session.query(UnitConcept).filter(UnitConcept.unit_id == unit.id).delete()
            for score, concept in concept_scores[:3]:
                if score < SECONDARY_TAG_THRESHOLD:
                    break
                session.add(
                    UnitConcept(unit_id=unit.id, concept_id=concept.id, confidence=float(score))
                )
                concept_links += 1

    session.commit()
    return {"tagged": tagged, "links": links, "concept_links": concept_links}


def summarise_modalities(session: Session, course_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    rows = session.scalars(select(ContentUnit.modality).where(ContentUnit.course_id == course_id)).all()
    for modality in rows:
        counts[modality.value if isinstance(modality, Modality) else str(modality)] += 1
    return dict(counts)
