"""Metric arithmetic, on synthetic predictions.

The point of these is that each metric measures the property its name claims.
Retrieval metrics were previously computed from the answer's citations, which made
"source_hit_rate" a citation metric: a case counted as a retrieval miss whenever the
model cited a neighbouring passage, and no test caught it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.client import Answer  # noqa: E402
from harness.metrics import Prediction, locator_of, refusal_metrics, retrieval_metrics  # noqa: E402
from harness.testset import TestCase  # noqa: E402

UNITS = {
    "u1": {"id": "u1", "source_id": "s1", "page_no": 5, "slide_no": None, "start_time_s": None,
           "text": "What this book is about."},
    "u2": {"id": "u2", "source_id": "s1", "page_no": 5, "slide_no": None, "start_time_s": None,
           "text": "A principle-oriented approach."},
    "u3": {"id": "u3", "source_id": "s1", "page_no": 6, "slide_no": None, "start_time_s": None,
           "text": "Mathematical requirements."},
}


def answer(retrieved, cited, status="grounded"):
    return Answer(
        question="q",
        text="an answer",
        grounding_status=status,
        coverage=0.8,
        citations=[{"unit_id": unit_id} for unit_id in cited],
        retrieved_unit_ids=list(retrieved),
        cited_unit_ids=list(cited),
        retrieved_labels=[],
        margin=0.05,
        latency_ms=1200,
    )


def case(truth, behavior="answerable", category="direct"):
    return TestCase(
        question="q",
        expected_behavior=behavior,
        reference_answer="r",
        ground_truth_unit_ids=list(truth),
        ground_truth_locator="loc",
        category=category,
    )


def test_retrieval_counts_the_context_not_the_citation():
    """The ground-truth passage was retrieved; the model cited its neighbour. That is
    a citation miss and a retrieval hit, and the two must not be conflated."""
    prediction = Prediction(case=case(["u1"]), answer=answer(["u3", "u1"], ["u3"]))
    metrics = retrieval_metrics([prediction], UNITS)
    assert metrics["source_hit_rate"] == 1.0
    assert metrics["citation_hit_rate"] == 0.0
    assert metrics["mean_reciprocal_rank"] == 0.5  # ground truth sits second


def test_locator_hit_accepts_a_sibling_chunk_from_the_right_page():
    """u2 is the other half of page 5. A learner clicking it lands in the right place,
    so it counts at locator level and not at unit level."""
    prediction = Prediction(case=case(["u1"]), answer=answer(["u2", "u3"], ["u2"]))
    metrics = retrieval_metrics([prediction], UNITS)
    assert metrics["source_hit_rate"] == 0.0
    assert metrics["locator_hit_rate"] == 1.0


def test_locator_of_separates_pages_slides_and_timestamps():
    assert locator_of(UNITS["u1"]) != locator_of(UNITS["u3"])
    assert locator_of(UNITS["u1"]) == locator_of(dict(UNITS["u1"]))


def test_precision_at_k_uses_the_whole_retrieved_set():
    prediction = Prediction(case=case(["u1"]), answer=answer(["u1", "u2", "u3"], ["u1"]))
    metrics = retrieval_metrics([prediction], UNITS)
    assert metrics["source_precision_at_k"] == round(1 / 3, 4)
    assert metrics["citation_precision"] == 1.0


def test_refusal_metrics_separate_the_two_error_directions():
    predictions = [
        Prediction(case=case(["u1"]), answer=answer(["u1"], ["u1"])),
        Prediction(case=case([], "off_material"), answer=answer([], [], "refused")),
        Prediction(case=case([], "off_material"), answer=answer(["u3"], ["u3"])),
    ]
    metrics = refusal_metrics(predictions)
    assert metrics["correct_refusal_rate"] == 0.5
    assert metrics["false_refusal_rate"] == 0.0
    assert metrics["off_material_cases"] == 2


def test_ambiguous_cases_are_counted_separately():
    predictions = [
        Prediction(case=case([], "ambiguous", "ambiguous"), answer=answer([], [], "refused")),
        Prediction(case=case(["u1"]), answer=answer(["u1"], ["u1"])),
        Prediction(case=case([], "off_material"), answer=answer([], [], "refused")),
    ]
    metrics = refusal_metrics(predictions)
    assert metrics["ambiguous_cases"] == 1
    assert metrics["ambiguous_handled"] == 1.0
    # an ambiguous question is not an answerable one, so it cannot be a false refusal
    assert metrics["false_refusal_rate"] == 0.0


def test_a_case_with_no_ground_truth_is_not_scored_for_retrieval():
    predictions = [Prediction(case=case([]), answer=answer(["u1"], ["u1"]))]
    assert retrieval_metrics(predictions, UNITS) == {}
