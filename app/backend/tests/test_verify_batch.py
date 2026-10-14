"""Batch verification.

Reviewing a batch in one call is only worth it if a malformed or partial reply cannot
silently reject good questions. These cover the paths that decide that.
"""
import pytest

from app.assessment import verifier


def question(stem: str):
    return {
        "qtype": "mcq",
        "stem": stem,
        "options": ["a", "b", "c", "d"],
        "answer_key": "a",
        "answer_explanation": "because",
    }


def verdict(index: int, ok: bool = True):
    return {
        "index": index,
        "supported_by_source": ok,
        "answer_is_correct": ok,
        "independent_answer": "a",
        "single_correct_option": True,
        "issues": [] if ok else ["answer not in the excerpts"],
        "confidence": 0.9,
    }


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def complete_json(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture
def fake(monkeypatch):
    def install(payload=None, error=None):
        client = FakeClient(payload, error)
        monkeypatch.setattr(verifier, "get_client", lambda: client)
        return client

    return install


def test_one_call_covers_the_whole_batch(fake):
    client = fake({"verdicts": [verdict(0), verdict(1), verdict(2)]})
    results = verifier.verify_batch([question("q1"), question("q2"), question("q3")], "excerpts")
    assert client.calls == 1, "the point of the batch is a single call"
    assert [r.passed for r in results] == [True, True, True]


def test_verdicts_are_matched_by_index_not_position(fake):
    fake({"verdicts": [verdict(2, False), verdict(0, True), verdict(1, True)]})
    results = verifier.verify_batch([question("q1"), question("q2"), question("q3")], "excerpts")
    assert [r.passed for r in results] == [True, True, False]


def test_positional_fallback_when_indices_are_missing(fake):
    verdicts = [verdict(0), verdict(1, False)]
    for item in verdicts:
        item.pop("index")
    fake({"verdicts": verdicts})
    results = verifier.verify_batch([question("q1"), question("q2")], "excerpts")
    assert [r.passed for r in results] == [True, False]


def test_a_missing_verdict_does_not_reject_the_question(fake):
    """The caller keeps a question whose verdict carries an error, matching the
    single-question path. Dropping it silently would quietly shrink the quiz."""
    fake({"verdicts": [verdict(0)]})
    results = verifier.verify_batch([question("q1"), question("q2")], "excerpts")
    assert results[0].passed is True
    assert results[1].passed is False
    assert results[1].error == "missing_verdict"


def test_a_failed_call_marks_every_question_unavailable_rather_than_failed(fake):
    fake(error=verifier.GroqError("429 rate limited"))
    results = verifier.verify_batch([question("q1"), question("q2")], "excerpts")
    assert all(r.error and "429" in r.error for r in results)
    assert all(r.issues == ["verifier_unavailable"] for r in results)


def test_a_single_question_uses_the_single_question_path(monkeypatch):
    seen = {}

    def fake_single(q, context):
        seen["called"] = True
        return verifier.VerificationResult(True, True, True, True, 1.0)

    monkeypatch.setattr(verifier, "verify_question", fake_single)
    results = verifier.verify_batch([question("only")], "excerpts")
    assert seen.get("called") is True
    assert len(results) == 1


def test_empty_batch_costs_nothing(fake):
    client = fake({"verdicts": []})
    assert verifier.verify_batch([], "excerpts") == []
    assert client.calls == 0


def test_the_reservation_grows_with_the_batch_but_stays_bounded(fake):
    client = fake({"verdicts": [verdict(i) for i in range(8)]})
    verifier.verify_batch([question(f"q{i}") for i in range(8)], "excerpts")
    assert client.last_kwargs["max_tokens"] <= 4000
    # one call's reservation must stay well under a single minute's 8,000 budget
    assert client.last_kwargs["max_tokens"] < 8000


def test_the_excerpts_are_sent_once(fake):
    client = fake({"verdicts": [verdict(0), verdict(1), verdict(2)]})
    verifier.verify_batch([question("q1"), question("q2"), question("q3")], "SOME EXCERPT TEXT")
    body = client.last_messages[-1]["content"]
    assert body.count("SOME EXCERPT TEXT") == 1
