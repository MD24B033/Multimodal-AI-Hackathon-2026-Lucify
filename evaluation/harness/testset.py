from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from harness.client import StudyCompanionClient
from harness.judge import GroqJudge

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "reference_answer": {"type": "string"},
    },
    "required": ["question", "reference_answer"],
    "additionalProperties": False,
}

OFF_MATERIAL_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
    "additionalProperties": False,
}

ANSWERABLE_SYSTEM = """You build an evaluation set for a retrieval system.

You are given ONE excerpt from a course. Write a question that this excerpt alone fully answers.

Rules:
- The question must be answerable from this excerpt and need no other source.
- Ask about the subject matter. Never mention the document, page, slide or excerpt.
- reference_answer is the correct answer in one to three sentences, taken only from the excerpt.
- Write a natural question a student would actually ask."""

OFF_MATERIAL_SYSTEM = """You build negative test cases for a course assistant that must refuse questions its material does not cover.

Given a course description, write questions that sound like they belong to the same broad academic area but are definitely NOT answerable from that course's material.

Rules:
- Stay plausible and adjacent. A good negative case is a neighbouring topic, not an absurd one.
- Never ask something the description suggests is covered.
- Write each question as a student would ask it."""


@dataclass
class TestCase:
    question: str
    expected_behavior: str
    reference_answer: str | None = None
    ground_truth_unit_ids: list[str] = field(default_factory=list)
    ground_truth_locator: str = ""
    modality: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TestCase":
        return cls(**payload)


def _locator_label(unit: dict[str, Any], sources: dict[str, str]) -> str:
    title = sources.get(unit["source_id"], "Source")
    if unit.get("slide_no") is not None:
        return f"{title} — Slide {unit['slide_no']}"
    if unit.get("start_time_s") is not None:
        seconds = int(unit["start_time_s"])
        return f"{title} — {seconds // 60}:{seconds % 60:02d}"
    if unit.get("page_no") is not None:
        return f"{title} — Page {unit['page_no']}"
    return title


def build(
    client: StudyCompanionClient,
    judge: GroqJudge,
    course_id: str,
    *,
    answerable: int = 10,
    off_material: int = 4,
    seed: int = 7,
    min_tokens: int = 40,
) -> list[TestCase]:
    random.seed(seed)

    sources = {source["id"]: source["title"] for source in client.sources(course_id)}
    units = client.units(course_id, limit=200)
    usable = [unit for unit in units if unit.get("token_count", 0) >= min_tokens]
    if not usable:
        raise RuntimeError("No units long enough to build a test set from")

    random.shuffle(usable)
    cases: list[TestCase] = []

    for unit in usable:
        if len(cases) >= answerable:
            break
        try:
            payload = judge.complete_json(
                [
                    {"role": "system", "content": ANSWERABLE_SYSTEM},
                    {"role": "user", "content": f"EXCERPT:\n{unit['text'][:2500]}"},
                ],
                schema=QUESTION_SCHEMA,
                max_tokens=1200,
                temperature=0.4,
            )
        except Exception:
            continue

        question = (payload.get("question") or "").strip()
        reference = (payload.get("reference_answer") or "").strip()
        if not question or not reference:
            continue

        cases.append(
            TestCase(
                question=question,
                expected_behavior="answerable",
                reference_answer=reference,
                ground_truth_unit_ids=[unit["id"]],
                ground_truth_locator=_locator_label(unit, sources),
                modality=unit.get("modality", "text"),
            )
        )

    if off_material > 0:
        course = next((c for c in client.courses() if c["id"] == course_id), {})
        description = (
            f"Course: {course.get('title')}\n"
            f"Description: {course.get('description') or 'not given'}\n"
            f"Sources: {', '.join(list(sources.values())[:10])}"
        )
        try:
            payload = judge.complete_json(
                [
                    {"role": "system", "content": OFF_MATERIAL_SYSTEM},
                    {"role": "user", "content": f"{description}\n\nWrite {off_material} questions."},
                ],
                schema=OFF_MATERIAL_SCHEMA,
                max_tokens=1200,
                temperature=0.6,
            )
            for question in payload.get("questions", [])[:off_material]:
                if question and question.strip():
                    cases.append(
                        TestCase(question=question.strip(), expected_behavior="off_material")
                    )
        except Exception:
            pass

    return cases


def save(cases: list[TestCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([case.to_dict() for case in cases], indent=2), encoding="utf-8"
    )


def load(path: Path) -> list[TestCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [TestCase.from_dict(entry) for entry in payload]
