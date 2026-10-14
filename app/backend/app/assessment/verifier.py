from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.llm.groq_client import GroqError, get_client

logger = logging.getLogger(__name__)

VERIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "supported_by_source": {"type": "boolean"},
        "answer_is_correct": {"type": "boolean"},
        "independent_answer": {"type": "string"},
        "single_correct_option": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "supported_by_source",
        "answer_is_correct",
        "independent_answer",
        "single_correct_option",
        "issues",
        "confidence",
    ],
    "additionalProperties": False,
}

VERIFIER_SYSTEM = """You are an exam quality checker. A different model wrote the question below from the given source excerpts.

Work independently:
1. Answer the question yourself using ONLY the excerpts. Put that in independent_answer.
2. supported_by_source: can the question be answered from the excerpts alone?
3. answer_is_correct: does the proposed answer match what the excerpts support, and does it match your independent answer?
4. single_correct_option: for multiple choice, is exactly one option defensibly correct? Set true for non-multiple-choice questions.
5. issues: list concrete problems (ambiguous wording, multiple correct options, answer not in the excerpts, wrong key). Empty list when there are none.
6. confidence: your confidence in this judgement, 0 to 1.

Be strict. A question that cannot be answered from the excerpts must fail."""


@dataclass
class VerificationResult:
    passed: bool
    supported: bool
    answer_correct: bool
    single_answer: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    independent_answer: str = ""
    verifier_model: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "supported_by_source": self.supported,
            "answer_is_correct": self.answer_correct,
            "single_correct_option": self.single_answer,
            "confidence": round(self.confidence, 3),
            "issues": self.issues,
            "independent_answer": self.independent_answer[:500],
            "verifier_model": self.verifier_model,
            "error": self.error,
        }


def _render_question(question: dict[str, Any]) -> str:
    lines = [f"Type: {question.get('qtype')}", f"Question: {question.get('stem')}"]
    options = question.get("options")
    if options:
        for index, option in enumerate(options):
            lines.append(f"  {chr(65 + index)}. {option}")
    lines.append(f"Proposed answer: {question.get('answer_key')}")
    if question.get("answer_explanation"):
        lines.append(f"Proposed explanation: {question['answer_explanation']}")
    return "\n".join(lines)


def verify_question(question: dict[str, Any], context: str) -> VerificationResult:
    client = get_client()
    messages = [
        {"role": "system", "content": VERIFIER_SYSTEM},
        {
            "role": "user",
            "content": f"SOURCE EXCERPTS:\n{context}\n\nQUESTION UNDER REVIEW:\n{_render_question(question)}",
        },
    ]

    try:
        payload = client.complete_json(
            messages,
            schema=VERIFICATION_SCHEMA,
            model=settings.verifier_model,
            supports_structured_output=False,
            # A verdict is a few booleans and one short sentence. The old 1600 was
            # reserved against the per-minute budget on every single question.
            max_tokens=600,
            temperature=0.0,
            task="verification",
        )
    except GroqError as exc:
        logger.warning("Verification call failed: %s", exc)
        return VerificationResult(
            passed=False,
            supported=False,
            answer_correct=False,
            single_answer=False,
            confidence=0.0,
            issues=["verifier_unavailable"],
            verifier_model=settings.verifier_model,
            error=str(exc)[:300],
        )

    supported = bool(payload.get("supported_by_source"))
    answer_correct = bool(payload.get("answer_is_correct"))
    single_answer = bool(payload.get("single_correct_option", True))
    confidence = float(payload.get("confidence") or 0.0)
    issues = [str(issue) for issue in payload.get("issues", []) if issue]

    passed = supported and answer_correct and single_answer

    return VerificationResult(
        passed=passed,
        supported=supported,
        answer_correct=answer_correct,
        single_answer=single_answer,
        confidence=confidence,
        issues=issues,
        independent_answer=str(payload.get("independent_answer") or ""),
        verifier_model=settings.verifier_model,
    )


BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "supported_by_source": {"type": "boolean"},
                    "answer_is_correct": {"type": "boolean"},
                    "independent_answer": {"type": "string"},
                    "single_correct_option": {"type": "boolean"},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "index",
                    "supported_by_source",
                    "answer_is_correct",
                    "independent_answer",
                    "single_correct_option",
                    "issues",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

BATCH_VERIFIER_SYSTEM = VERIFIER_SYSTEM.replace(
    "A different model wrote the question below from the given source excerpts.",
    "A different model wrote the questions below from the given source excerpts. "
    "Judge every one of them, independently of each other.",
).replace(
    "Be strict. A question that cannot be answered from the excerpts must fail.",
    "Return one verdict per question, each carrying the index it was given. Judge every "
    "question, even if an earlier one was poor.\n\n"
    "Be strict. A question that cannot be answered from the excerpts must fail.",
)


def _unavailable(reason: str) -> "VerificationResult":
    """Matches the single-question failure path: a verdict we could not obtain must not
    silently reject a question, so the caller keeps it and records why."""
    return VerificationResult(
        passed=False,
        supported=False,
        answer_correct=False,
        single_answer=False,
        confidence=0.0,
        issues=["verifier_unavailable"],
        verifier_model=settings.verifier_model,
        error=reason[:300],
    )


def _result_from(payload: dict[str, Any]) -> VerificationResult:
    supported = bool(payload.get("supported_by_source"))
    answer_correct = bool(payload.get("answer_is_correct"))
    single_answer = bool(payload.get("single_correct_option", True))
    return VerificationResult(
        passed=supported and answer_correct and single_answer,
        supported=supported,
        answer_correct=answer_correct,
        single_answer=single_answer,
        confidence=float(payload.get("confidence") or 0.0),
        issues=[str(issue) for issue in payload.get("issues", []) if issue],
        independent_answer=str(payload.get("independent_answer") or ""),
        verifier_model=settings.verifier_model,
    )


def verify_batch(questions: list[dict[str, Any]], context: str) -> list[VerificationResult]:
    """One review covering every candidate from the same excerpts.

    Candidates in a batch are written from one set of at most five units, so sending
    the excerpts once per question meant paying for the same context up to eight times
    over. On an 8,000 token minute that was the difference between a quiz arriving
    inside one window and spilling into the next.
    """
    if not questions:
        return []
    if len(questions) == 1:
        return [verify_question(questions[0], context)]

    rendered = "\n\n".join(
        f"QUESTION {index}\n{_render_question(question)}"
        for index, question in enumerate(questions)
    )
    messages = [
        {"role": "system", "content": BATCH_VERIFIER_SYSTEM},
        {
            "role": "user",
            "content": f"SOURCE EXCERPTS:\n{context}\n\nQUESTIONS UNDER REVIEW:\n{rendered}",
        },
    ]

    try:
        payload = get_client().complete_json(
            messages,
            schema=BATCH_SCHEMA,
            model=settings.verifier_model,
            supports_structured_output=False,
            # A verdict is a few booleans and a short sentence; the independent answer
            # is the only part that varies much.
            max_tokens=min(4000, 260 + 200 * len(questions)),
            temperature=0.0,
            task="verification",
        )
    except GroqError as exc:
        logger.warning("Batch verification failed: %s", exc)
        return [_unavailable(str(exc)) for _ in questions]

    verdicts = payload.get("verdicts") or []
    by_index: dict[int, dict[str, Any]] = {}
    for verdict in verdicts:
        try:
            by_index[int(verdict.get("index"))] = verdict
        except (TypeError, ValueError):
            continue

    # Positional fallback for a model that returned the right number of verdicts but
    # did not echo the indices.
    if len(by_index) != len(questions) and len(verdicts) == len(questions):
        by_index = dict(enumerate(verdicts))

    results = []
    for index in range(len(questions)):
        verdict = by_index.get(index)
        if verdict is None:
            logger.info("Batch verification returned no verdict for question %d", index)
            results.append(_unavailable("missing_verdict"))
        else:
            results.append(_result_from(verdict))
    return results
