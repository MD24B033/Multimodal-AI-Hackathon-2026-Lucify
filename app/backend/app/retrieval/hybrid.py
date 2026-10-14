from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ContentUnit, Modality, Source, UnitTopic
from app.ingestion.types import format_timestamp
from app.llm import timing
from app.retrieval.embedder import get_embedder


@dataclass
class RetrievedUnit:
    unit: ContentUnit
    source: Source
    score: float
    vector_rank: int | None = None
    text_rank: int | None = None
    vector_score: float = 0.0

    def locator(self) -> dict[str, Any]:
        return {
            "page": self.unit.page_no,
            "slide": self.unit.slide_no,
            "start_time_s": self.unit.start_time_s,
            "end_time_s": self.unit.end_time_s,
            "bbox": self.unit.bbox,
        }

    def label(self) -> str:
        if self.unit.slide_no is not None:
            return f"Slide {self.unit.slide_no}"
        if self.unit.start_time_s is not None:
            return format_timestamp(self.unit.start_time_s)
        if self.unit.page_no is not None:
            return f"Page {self.unit.page_no}"
        return "Document"

    def citation(self, index: int | None = None) -> dict[str, Any]:
        payload = {
            "unit_id": str(self.unit.id),
            "source_id": str(self.source.id),
            "source_title": self.source.title,
            "source_kind": self.source.kind.value,
            "modality": self.unit.modality.value,
            "label": self.label(),
            "locator": self.locator(),
            "excerpt": self.unit.text[:420],
            "score": round(float(self.score), 4),
            "heading_path": self.unit.heading_path or [],
            "external_url": self.source.external_url,
            "has_image": bool(self.unit.image_path),
        }
        if index is not None:
            payload["marker"] = index
        return payload


def coverage_margin(scores: list[float]) -> float:
    """How far the best passage stands above the rest of the retrieved set.

    Absolute similarity says little on its own: bge-small puts almost any
    deep-learning question within 0.63-0.87 of almost any deep-learning passage, so
    a question the corpus cannot answer still scores high. What distinguishes the two
    is shape. When the answer is present, one passage pulls away; when it is absent,
    the whole set sits at the same middling similarity. Measured on the development
    set this separates answerable from off-material with AUC 0.96, against 0.87 for
    the top score alone.
    """
    usable = [score for score in scores if score]
    if len(usable) < 2:
        return 0.0
    ordered = sorted(usable, reverse=True)
    rest = ordered[1:]
    return ordered[0] - (sum(rest) / len(rest))


@dataclass
class RetrievalResult:
    query: str
    units: list[RetrievedUnit] = field(default_factory=list)
    best_score: float = 0.0
    mean_score: float = 0.0
    margin: float = 0.0

    def citations(self) -> list[dict[str, Any]]:
        return [unit.citation(index + 1) for index, unit in enumerate(self.units)]

    def context_block(self, max_chars: int = 9000) -> str:
        blocks: list[str] = []
        used = 0
        for index, item in enumerate(self.units, start=1):
            header = f"[{index}] {item.source.title} — {item.label()}"
            if item.unit.modality is not Modality.text:
                header += f" ({item.unit.modality.value})"
            body = item.unit.text.strip()
            block = f"{header}\n{body}"
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)


def _topic_filtered_unit_ids(
    session: Session, course_id: uuid.UUID, topic_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    rows = session.scalars(
        select(UnitTopic.unit_id).where(UnitTopic.topic_id.in_(topic_ids))
    ).all()
    return set(rows)


def search(
    session: Session,
    course_id: uuid.UUID,
    query: str,
    *,
    top_k: int | None = None,
    candidates: int | None = None,
    topic_ids: list[uuid.UUID] | None = None,
    source_ids: list[uuid.UUID] | None = None,
    modalities: list[Modality] | None = None,
    exclude_unit_ids: list[uuid.UUID] | None = None,
) -> RetrievalResult:
    top_k = top_k or settings.retrieval_top_k
    candidates = candidates or settings.retrieval_candidates

    embedder = get_embedder()
    with timing.stage("embed_ms"):
        query_vector = embedder.embed_query(query)

    def apply_filters(statement):
        statement = statement.where(ContentUnit.course_id == course_id)
        if source_ids:
            statement = statement.where(ContentUnit.source_id.in_(source_ids))
        if modalities:
            statement = statement.where(ContentUnit.modality.in_(modalities))
        if exclude_unit_ids:
            statement = statement.where(ContentUnit.id.notin_(exclude_unit_ids))
        if topic_ids:
            allowed = _topic_filtered_unit_ids(session, course_id, topic_ids)
            if not allowed:
                return None
            statement = statement.where(ContentUnit.id.in_(allowed))
        return statement

    distance = ContentUnit.embedding.cosine_distance(query_vector).label("distance")
    vector_statement = apply_filters(select(ContentUnit, distance))
    if vector_statement is None:
        return RetrievalResult(query=query)
    with timing.stage("vector_search_ms"):
        vector_rows = session.execute(
            vector_statement.where(ContentUnit.embedding.isnot(None))
            .order_by(distance)
            .limit(candidates)
        ).all()

    ts_query = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(ContentUnit.search_vector, ts_query).cast(Float).label("rank")
    text_statement = apply_filters(select(ContentUnit, rank))
    text_rows = []
    if text_statement is not None:
        with timing.stage("lexical_search_ms"):
            text_rows = session.execute(
                text_statement.where(ContentUnit.search_vector.op("@@")(ts_query))
                .order_by(rank.desc())
                .limit(candidates)
            ).all()

    scores: dict[uuid.UUID, dict[str, Any]] = {}
    k = settings.rrf_k

    for position, (unit, dist) in enumerate(vector_rows):
        entry = scores.setdefault(unit.id, {"unit": unit, "score": 0.0})
        entry["score"] += 1.0 / (k + position + 1)
        entry["vector_rank"] = position + 1
        entry["vector_score"] = 1.0 - float(dist)

    for position, (unit, _rank) in enumerate(text_rows):
        entry = scores.setdefault(unit.id, {"unit": unit, "score": 0.0})
        entry["score"] += 1.0 / (k + position + 1)
        entry["text_rank"] = position + 1

    if not scores:
        return RetrievalResult(query=query)

    ordered = sorted(scores.values(), key=lambda item: item["score"], reverse=True)[:top_k]
    source_ids_needed = {entry["unit"].source_id for entry in ordered}
    sources = {
        source.id: source
        for source in session.scalars(select(Source).where(Source.id.in_(source_ids_needed))).all()
    }

    retrieved = [
        RetrievedUnit(
            unit=entry["unit"],
            source=sources[entry["unit"].source_id],
            score=entry["score"],
            vector_rank=entry.get("vector_rank"),
            text_rank=entry.get("text_rank"),
            vector_score=entry.get("vector_score", 0.0),
        )
        for entry in ordered
        if entry["unit"].source_id in sources
    ]

    semantic_scores = [item.vector_score for item in retrieved if item.vector_score]
    return RetrievalResult(
        query=query,
        units=retrieved,
        best_score=max(semantic_scores) if semantic_scores else 0.0,
        mean_score=sum(semantic_scores) / len(semantic_scores) if semantic_scores else 0.0,
        margin=coverage_margin(semantic_scores),
    )
