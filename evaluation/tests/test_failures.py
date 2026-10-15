"""A provider outage must never be reported as system behaviour.

A run in which every call failed on quota still produced a report reading
"correct refusal rate 100%, false refusal rate 100%" with nothing to say the run was
invalid. These make that impossible.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.client import Answer  # noqa: E402
from harness.metrics import (  # noqa: E402
    Prediction,
    failure_metrics,
    latency_metrics,
    refusal_metrics,
    retrieval_metrics,
)
from harness.testset import TestCase  # noqa: E402

UNITS = {
    "u1": {"id": "u1", "source_id": "s1", "page_no": 5, "slide_no": None,
           "start_time_s": None, "text": "text"},
}


def answer(status="grounded", failure=None, retrieved=("u1",), latency=1000):
    return Answer(
        question="q",
        text="an answer",
        grounding_status=status,
        coverage=0.8,
        citations=[{"unit_id": u} for u in retrieved],
        retrieved_unit_ids=list(retrieved),
        cited_unit_ids=list(retrieved),
        retrieved_labels=[],
        margin=0.05,
        latency_ms=latency,
        failure=failure,
    )


def case(behavior="answerable", truth=("u1",)):
    return TestCase(
        question="q",
        expected_behavior=behavior,
        reference_answer="r",
        ground_truth_unit_ids=list(truth),
        ground_truth_locator="loc",
    )


def test_a_quota_failure_is_not_a_refusal():
    failed = answer(status="refused", failure="daily_quota_exhausted")
    assert failed.failed is True
    assert failed.refused is False, "an outage is not a decision about evidence"


def test_failed_cases_do_not_create_false_refusals():
    """The exact shape of the invalid run: every answerable case failed on quota."""
    predictions = [
        Prediction(case=case(), answer=answer(status="refused", failure="daily_quota_exhausted"))
        for _ in range(8)
    ]
    metrics = refusal_metrics(predictions)
    assert metrics["false_refusal_rate"] is None, "with nothing usable there is no rate"
    assert metrics["off_material_cases"] == 0


def test_a_genuine_refusal_still_counts():
    predictions = [
        Prediction(case=case("off_material", ()), answer=answer(status="refused")),
        Prediction(case=case(), answer=answer()),
    ]
    metrics = refusal_metrics(predictions)
    assert metrics["correct_refusal_rate"] == 1.0
    assert metrics["false_refusal_rate"] == 0.0


def test_failures_are_counted_and_named():
    predictions = [
        Prediction(case=case(), answer=answer(failure="daily_quota_exhausted")),
        Prediction(case=case(), answer=answer(failure="provider_unavailable")),
        Prediction(case=case(), answer=answer()),
    ]
    metrics = failure_metrics(predictions)
    assert metrics["failed_cases"] == 2
    assert metrics["scored_cases"] == 1
    assert metrics["failure_reasons"] == {
        "daily_quota_exhausted": 1,
        "provider_unavailable": 1,
    }


def test_retrieval_ignores_failed_cases():
    """Retrieval ran, but the case produced no answer, so it cannot be scored as one."""
    predictions = [
        Prediction(case=case(), answer=answer(failure="daily_quota_exhausted")),
        Prediction(case=case(), answer=answer()),
    ]
    metrics = retrieval_metrics(predictions, UNITS)
    assert metrics["answerable_cases"] == 1


def test_latency_excludes_failed_calls():
    """A call that spent sixty seconds waiting for a quota that never came is not a
    latency measurement."""
    predictions = [
        Prediction(case=case(), answer=answer(failure="daily_quota_exhausted", latency=59000)),
        Prediction(case=case(), answer=answer(latency=1200)),
    ]
    assert latency_metrics(predictions)["latency_median_ms"] == 1200


def test_the_sentinel_text_is_recognised_without_app_support():
    """Older builds reported no availability block; the message text is the fallback."""
    from harness.client import StudyCompanionClient

    payload = {
        "message": {
            "content": "**Daily token quota exhausted: 199,000 of 200,000 tokens used today.**",
            "grounding_status": "refused",
            "coverage": 0.8,
            "citations": [],
            "retrieved_unit_ids": [],
            "latency_ms": 300,
        }
    }

    client = StudyCompanionClient.__new__(StudyCompanionClient)
    client._request = lambda *a, **k: payload  # type: ignore[attr-defined]
    result = client.ask("session", "q")
    assert result.failed is True
    assert result.failure == "daily_quota_exhausted"
    assert result.refused is False
