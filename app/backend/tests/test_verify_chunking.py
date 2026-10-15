"""Verification batches must fit the verifier's own input ceiling.

Batching every candidate into one call built a request the model refused outright:

    413: Request too large for model qwen/qwen3.8-27b ... (ITPM): Limit 7000, Requested 7032

and because a 413 is not retryable, every question in that batch came back unverified.
"""
import pytest

from app.assessment import verifier
from app.config import settings


def question(stem_words: int = 20):
    return {
        "qtype": "mcq",
        "stem": "word " * stem_words,
        "options": ["alpha", "beta", "gamma", "delta"],
        "answer_key": "alpha",
        "answer_explanation": "because " * 10,
    }


def verdict(index: int):
    return {
        "index": index,
        "supported_by_source": True,
        "answer_is_correct": True,
        "independent_answer": "alpha",
        "single_correct_option": True,
        "issues": [],
        "confidence": 0.9,
    }


class RecordingClient:
    def __init__(self):
        self.requests = []

    def complete_json(self, messages, **kwargs):
        body = messages[-1]["content"]
        self.requests.append(body)
        if "QUESTIONS UNDER REVIEW" not in body:
            # A chunk of one takes the single-question path, which reads a flat verdict.
            flat = verdict(0)
            flat.pop("index")
            return flat
        count = sum(1 for n in range(50) if ("QUESTION " + str(n)) in body)
        return {"verdicts": [verdict(i) for i in range(count)]}


@pytest.fixture
def client(monkeypatch):
    recording = RecordingClient()
    monkeypatch.setattr(verifier, "get_client", lambda: recording)
    return recording


def test_a_small_batch_still_takes_one_call(client):
    verifier.verify_batch([question() for _ in range(3)], "short context")
    assert len(client.requests) == 1


def test_a_large_context_forces_the_batch_to_split(client):
    """The excerpts dominate the request, so fewer questions fit per call."""
    context = "excerpt text " * 1200  # roughly 3,600 tokens
    results = verifier.verify_batch([question(60) for _ in range(8)], context)
    assert len(client.requests) > 1, "one call would exceed the verifier's input ceiling"
    assert len(results) == 8
    assert all(result is not None for result in results)


def test_every_call_stays_inside_the_input_budget(client):
    context = "excerpt text " * 900
    verifier.verify_batch([question(40) for _ in range(10)], context)
    for body in client.requests:
        assert len(body) // 4 < settings.verifier_input_budget


def test_each_question_gets_exactly_one_verdict_across_chunks(client):
    context = "excerpt text " * 1200
    questions = [question(60) for _ in range(7)]
    results = verifier.verify_batch(questions, context)
    assert len(results) == len(questions)
    assert all(result.passed for result in results)


def test_chunking_never_drops_a_question(client):
    context = "excerpt " * 4000  # context alone blows the budget
    questions = [question(30) for _ in range(4)]
    results = verifier.verify_batch(questions, context)
    assert len(results) == 4


def test_413_is_not_retried():
    """Retrying a request that cannot fit only burns the backoff budget."""
    from app.llm.groq_client import RETRYABLE_STATUS

    assert 413 not in RETRYABLE_STATUS
