"""Calibration measurement for the learner model.

The published run reported a 24.4% mean calibration error. These fix the property
that number was conflating: an estimate the model has no evidence for is not the
same as an estimate that is wrong.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.personalization import (  # noqa: E402
    SimulatedLearner,
    calibration_on_evidence,
    irt_probability,
)


def learner(ability):
    return SimulatedLearner(
        name="test", persona="novice", arm="adaptive", ability=ability, learning_rate=0.3
    )


def row(topic_id, mastery, attempts):
    return {"topic_id": topic_id, "mastery": mastery, "attempts": attempts, "kind": "subtopic"}


def test_untouched_topics_do_not_count_as_calibration_error():
    """An advanced learner questioned on one topic of three: the model is right where
    it has evidence and silent elsewhere, which must not read as a 0.48 error."""
    strong = {"t1": 1.0, "t2": 1.0, "t3": 1.0}
    rows = [
        row("t1", round(irt_probability(1.0, 0.0), 4), 4),  # practised, model agrees
        row("t2", 0.25, 0),                                  # never asked: prior
        row("t3", 0.25, 0),                                  # never asked: prior
    ]
    result = calibration_on_evidence(rows, learner(strong))
    assert result["calibration_error_on_evidence"] < 0.01
    assert result["topics_practised"] == 1
    assert result["topics_total"] == 3
    assert result["evidence_coverage"] == round(1 / 3, 4)


def test_a_genuinely_wrong_estimate_still_counts():
    rows = [row("t1", 0.9, 5)]
    result = calibration_on_evidence(rows, learner({"t1": -2.0}))
    # truly weak learner, model says 0.9 -- that is a real calibration failure
    assert result["calibration_error_on_evidence"] > 0.4


def test_no_evidence_reports_none_rather_than_zero():
    """Zero would read as perfect calibration. There is simply nothing to score."""
    result = calibration_on_evidence([row("t1", 0.25, 0)], learner({"t1": 0.5}))
    assert result["calibration_error_on_evidence"] is None
    assert result["evidence_coverage"] == 0.0


def test_coverage_is_reported_so_the_number_can_be_read_in_context():
    rows = [row("t1", 0.6, 2), row("t2", 0.6, 1), row("t3", 0.25, 0), row("t4", 0.25, 0)]
    result = calibration_on_evidence(rows, learner({"t1": 0.0, "t2": 0.0}))
    assert result["evidence_coverage"] == 0.5
    assert result["topics_practised"] == 2
