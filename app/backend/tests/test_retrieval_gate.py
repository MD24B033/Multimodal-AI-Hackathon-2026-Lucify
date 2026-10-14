"""The refusal gate, at the level that does not need a database.

These guard the signal the gate is built on. The numbers in the parametrised cases
are real: they come from running the evaluation development set through retrieval
(evaluation/datasets/dev.json), so a regression here means the gate has stopped
separating answerable questions from off-material ones the way it was measured to.
"""
import pytest

from app.config import settings
from app.retrieval.hybrid import coverage_margin


def test_margin_is_zero_without_enough_scores():
    assert coverage_margin([]) == 0.0
    assert coverage_margin([0.81]) == 0.0


def test_margin_ignores_missing_scores():
    # Lexical-only hits carry no cosine; they must not drag the mean down to zero.
    assert coverage_margin([0.80, 0.0, 0.70]) == pytest.approx(0.10)


def test_margin_is_the_gap_to_the_rest():
    assert coverage_margin([0.90, 0.70, 0.70, 0.70]) == pytest.approx(0.20)


def test_a_flat_set_has_no_margin():
    assert coverage_margin([0.75, 0.75, 0.75]) == pytest.approx(0.0)


def test_order_does_not_matter():
    assert coverage_margin([0.70, 0.88, 0.74]) == pytest.approx(
        coverage_margin([0.88, 0.74, 0.70])
    )


# (margin, is_answerable) measured on the development set.
MEASURED = [
    (0.130, True),    # "What is the point of an activation function"
    (0.058, True),    # single-layer diagram, z2
    (0.050, True),    # Network class initialisation
    (0.048, True),    # sigmoid neurons fix
    (0.035, True),    # eyeballing the graph
    (0.030, True),    # dropout
    (0.038, False),   # vanishing gradients in RNNs
    (0.033, False),   # convolutional weight sharing
    (0.024, False),   # batch normalisation
    (0.021, False),   # big-O of backpropagation
    (0.012, False),   # LSTM gates
    (0.006, False),   # "What does it compute?" - no referent at all
]


@pytest.mark.parametrize("margin,answerable", MEASURED)
def test_threshold_keeps_answerable_questions_and_catches_the_worst(margin, answerable):
    passes = margin >= settings.grounding_margin
    if answerable:
        assert passes, (
            f"margin {margin} would refuse an answerable question at threshold "
            f"{settings.grounding_margin}"
        )
    elif margin < 0.028:
        assert not passes


def test_threshold_is_below_every_answerable_dev_case():
    """The gate is calibrated to cost no answers on the development set. If someone
    raises it, this says what they are trading away."""
    worst_answerable = min(margin for margin, answerable in MEASURED if answerable)
    assert settings.grounding_margin <= worst_answerable
