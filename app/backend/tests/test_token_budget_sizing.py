"""Reservation sizing.

Groq admits a request against prompt + max_completion_tokens, not against what the
model actually writes, so every ceiling in the config is booked against an 8,000 token
minute on every call. These pin the ceilings to what was measured, so raising one is a
deliberate act with a number attached rather than a guess.
"""
from app.assessment.generator import _budget_for
from app.config import settings

# Measured over 228 vision calls on the demo corpus (the llm_cache table).
VISION_COMPLETION_MEDIAN = 174
VISION_COMPLETION_P95 = 536
VISION_COMPLETION_MAX = 712


def test_page_descriptions_have_headroom_above_the_longest_measured():
    assert settings.page_image_max_tokens > VISION_COMPLETION_MAX


def test_page_descriptions_do_not_book_wildly_more_than_they_use():
    """Three times the p95 would be reserving a third of a minute's budget per page."""
    assert settings.page_image_max_tokens < 3 * VISION_COMPLETION_P95


def test_a_single_page_call_cannot_consume_a_whole_minute():
    # ~920 prompt tokens for an image plus its instruction, as measured.
    assert 920 + settings.page_image_max_tokens < settings.tokens_per_minute


def test_quiz_budget_scales_with_the_questions_asked_for():
    assert _budget_for(2, ["mcq"]) < _budget_for(6, ["mcq"])


def test_quiz_budget_stays_inside_one_minute():
    """A generation call that cannot fit in a minute can never be admitted, and the
    batched path asks for every target at once."""
    assert _budget_for(12, ["mcq"]) <= settings.generation_max_tokens
    assert _budget_for(12, ["mcq"]) < settings.tokens_per_minute


def test_short_answer_costs_less_to_reserve_than_multiple_choice():
    assert _budget_for(4, ["short_answer"]) < _budget_for(4, ["mcq"])
