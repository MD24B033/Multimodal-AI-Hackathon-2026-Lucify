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
