from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Concept, Topic, TopicPrerequisite, UnitTopic
from app.learner import profile


def _layer_assignment(
    node_ids: list[uuid.UUID], edges: list[tuple[uuid.UUID, uuid.UUID]]
) -> dict[uuid.UUID, int]:
    dependencies: dict[uuid.UUID, set[uuid.UUID]] = {node: set() for node in node_ids}
    for topic_id, prerequisite_id in edges:
        if topic_id in dependencies and prerequisite_id in dependencies:
            dependencies[topic_id].add(prerequisite_id)

    layers: dict[uuid.UUID, int] = {}
    remaining = set(node_ids)
    level = 0

    while remaining and level < 40:
        ready = {
            node
            for node in remaining
            if not (dependencies[node] & remaining)
        }
        if not ready:
            ready = set(remaining)
        for node in ready:
            layers[node] = level
        remaining -= ready
        level += 1

    for node in remaining:
        layers[node] = level
    return layers


def build_flow_map(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID | None = None,
) -> dict:
    topics = session.scalars(
        select(Topic).where(Topic.course_id == course_id).order_by(Topic.ordinal, Topic.name)
    ).all()
    if not topics:
        return {"nodes": [], "edges": [], "layers": 0}

    topic_ids = [topic.id for topic in topics]

    unit_counts = dict(
        session.execute(
            select(UnitTopic.topic_id, func.count(UnitTopic.unit_id))
            .where(UnitTopic.topic_id.in_(topic_ids))
            .group_by(UnitTopic.topic_id)
        ).all()
    )
    concept_counts = dict(
        session.execute(
            select(Concept.topic_id, func.count(Concept.id))
            .where(Concept.topic_id.in_(topic_ids))
            .group_by(Concept.topic_id)
        ).all()
    )

    edge_rows = session.execute(
        select(TopicPrerequisite.topic_id, TopicPrerequisite.prerequisite_id, TopicPrerequisite.rationale)
        .where(
            TopicPrerequisite.topic_id.in_(topic_ids),
            TopicPrerequisite.prerequisite_id.in_(topic_ids),
        )
    ).all()

    mastery_by_topic: dict[uuid.UUID, float] = {}
    attempts_by_topic: dict[uuid.UUID, int] = {}
    if student_id is not None:
        for item in profile.snapshot(session, student_id, course_id):
            mastery_by_topic[item.topic_id] = item.p_known
            attempts_by_topic[item.topic_id] = item.attempts

    layers = _layer_assignment(topic_ids, [(row[0], row[1]) for row in edge_rows])
    children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for topic in topics:
        if topic.parent_id is not None:
            children[topic.parent_id].append(topic.id)

    rolled_up_concepts = dict(concept_counts)
    rolled_up_units = dict(unit_counts)
    for topic in topics:
        if topic.parent_id is None:
            continue
        rolled_up_concepts[topic.parent_id] = rolled_up_concepts.get(
            topic.parent_id, 0
        ) + concept_counts.get(topic.id, 0)

    nodes = []
    for topic in topics:
        mastery = mastery_by_topic.get(topic.id)
        nodes.append(
            {
                "id": str(topic.id),
                "name": topic.name,
                "kind": topic.kind.value,
                "summary": topic.summary,
                "parent_id": str(topic.parent_id) if topic.parent_id else None,
                "children": [str(child) for child in children.get(topic.id, [])],
                "layer": layers.get(topic.id, 0),
                "unit_count": int(rolled_up_units.get(topic.id, 0)),
                "concept_count": int(rolled_up_concepts.get(topic.id, 0)),
                "mastery": round(mastery, 3) if mastery is not None else None,
                "attempts": attempts_by_topic.get(topic.id, 0),
            }
        )

    edges = [
        {
            "source": str(prerequisite_id),
            "target": str(topic_id),
            "rationale": rationale,
            "kind": "prerequisite",
        }
        for topic_id, prerequisite_id, rationale in edge_rows
    ]
    edges.extend(
        {
            "source": str(topic.parent_id),
            "target": str(topic.id),
            "rationale": None,
            "kind": "contains",
        }
        for topic in topics
        if topic.parent_id is not None
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "layers": max(layers.values()) + 1 if layers else 0,
    }


def learning_path(
    session: Session,
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    limit: int = 6,
) -> list[dict]:
    flow = build_flow_map(session, course_id, student_id)
    node_by_id = {node["id"]: node for node in flow["nodes"]}

    prerequisites: dict[str, list[str]] = defaultdict(list)
    for edge in flow["edges"]:
        if edge["kind"] == "prerequisite":
            prerequisites[edge["target"]].append(edge["source"])

    ranked = []
    for node in flow["nodes"]:
        if node["kind"] != "subtopic" or node["unit_count"] == 0:
            continue
        mastery = node["mastery"] if node["mastery"] is not None else 0.25
        blocked_by = [
            node_by_id[dep]["name"]
            for dep in prerequisites.get(node["id"], [])
            if dep in node_by_id
            and (node_by_id[dep]["mastery"] if node_by_id[dep]["mastery"] is not None else 0.25) < 0.5
        ]
        readiness = 1.0 - mastery - 0.3 * len(blocked_by)
        ranked.append(
            {
                "topic_id": node["id"],
                "topic": node["name"],
                "mastery": mastery,
                "layer": node["layer"],
                "blocked_by": blocked_by,
                "priority": round(readiness, 3),
            }
        )

    ranked.sort(key=lambda item: (item["layer"], -item["priority"]))
    return ranked[:limit]
