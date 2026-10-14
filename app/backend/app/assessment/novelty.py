from __future__ import annotations

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Question
from app.retrieval.embedder import get_embedder

_NORMALISE = re.compile(r"[^a-z0-9 ]+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "is", "are", "what", "which", "that",
    "for", "on", "and", "or", "it", "as", "by", "be", "with", "does", "do",
}


def normalise_stem(stem: str) -> str:
    lowered = _NORMALISE.sub(" ", stem.lower())
    tokens = [token for token in lowered.split() if token not in _STOPWORDS]
    return " ".join(sorted(set(tokens)))


def fingerprint(stem: str, answer_key: str) -> str:
    material = f"{normalise_stem(stem)}|{normalise_stem(answer_key)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class NoveltyFilter:
    def __init__(self, session: Session, course_id: uuid.UUID, threshold: float | None = None):
        self.session = session
        self.course_id = course_id
        self.threshold = threshold if threshold is not None else settings.novelty_threshold
        self.embedder = get_embedder()

        rows = session.execute(
            select(Question.fingerprint, Question.embedding).where(Question.course_id == course_id)
        ).all()
        self._fingerprints = {row[0] for row in rows if row[0]}
        self._vectors = [row[1] for row in rows if row[1] is not None]

    def check(self, stem: str, answer_key: str, vector: list[float] | None = None) -> tuple[bool, float]:
        digest = fingerprint(stem, answer_key)
        if digest in self._fingerprints:
            return False, 1.0

        if vector is None:
            vector = self.embedder.embed_documents([stem])[0]

        best = 0.0
        for existing in self._vectors:
            similarity = self.embedder.similarity(vector, existing)
            if similarity > best:
                best = similarity
            if best >= self.threshold:
                return False, best
        return True, best

    def accept(self, stem: str, answer_key: str, vector: list[float]) -> None:
        self._fingerprints.add(fingerprint(stem, answer_key))
        self._vectors.append(vector)

    @property
    def known_count(self) -> int:
        return len(self._fingerprints)
