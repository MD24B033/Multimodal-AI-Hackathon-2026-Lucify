"""Reservation sizing.

The app throttles itself with a token bucket. Booking `prompt + max_completion_tokens`
held back roughly twice what a page of vision actually spends, which is most of why
ingestion ran at about half the rate its allowance permitted.
"""
import pytest

from app.llm import sizing


@pytest.fixture(autouse=True)
def fresh():
    """Each test gets its own history; the sizer is process-wide."""
    sizing._sizer = sizing.CompletionSizer()


def test_a_cold_task_uses_its_seed():
    assert sizing.expected_completion("vision", 850) == sizing.SEEDS["vision"]


def test_an_unknown_task_falls_back_to_the_default_seed():
    assert sizing.expected_completion("something_new", 4000) == sizing.DEFAULT_SEED


def test_the_ceiling_always_wins():
    """A caller that asked for at most 200 tokens must never reserve more."""
    for value in (50, 900, 1200):
        sizing.observe_completion("vision", value)
    assert sizing.expected_completion("vision", 200) == 200


def test_the_floor_protects_against_a_degenerate_estimate():
    for _ in range(6):
        sizing.observe_completion("tiny", 1)
    assert sizing.expected_completion("tiny", 800) == sizing.FLOOR


def test_observation_replaces_the_seed_once_there_is_enough_of_it():
    for value in [100, 110, 120, 130, 140, 150]:
        sizing.observe_completion("vision", value)
    estimate = sizing.expected_completion("vision", 850)
    assert estimate != sizing.SEEDS["vision"]
    assert 100 <= estimate <= 150


def test_the_estimate_sits_above_the_median_but_below_the_worst_case():
    samples = [100, 150, 200, 250, 300, 400, 700]
    for value in samples:
        sizing.observe_completion("vision", value)
    estimate = sizing.expected_completion("vision", 850)
    assert estimate > 250, "an estimate at the median would under-reserve most calls"
    assert estimate < 700, "reserving the worst case is what this replaces"


def test_zero_length_completions_are_ignored():
    for value in [0, 0, 0, 0, 0, 0]:
        sizing.observe_completion("vision", value)
    assert sizing.expected_completion("vision", 850) == sizing.SEEDS["vision"]


def test_only_recent_completions_count():
    """A task whose replies get shorter should stop reserving for the old ones."""
    for _ in range(sizing.HISTORY):
        sizing.observe_completion("chat", 800)
    for _ in range(sizing.HISTORY):
        sizing.observe_completion("chat", 100)
    assert sizing.expected_completion("chat", 2000) <= 150


def test_a_page_of_vision_reserves_less_than_the_old_ceiling():
    """The measured shape: ~920 prompt tokens, 850 allowed, ~190 typically written."""
    for value in [174, 200, 250, 150, 300, 190]:
        sizing.observe_completion("vision", value)
    reserved = 920 + sizing.expected_completion("vision", 850)
    assert reserved < 920 + 850
    # and still comfortably above what such a call actually costs
    assert reserved > 920
