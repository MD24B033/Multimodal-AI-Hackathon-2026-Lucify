"""Each model gets its own token budget.

Groq meters tokens per model — gpt-oss-120b and qwen3.8-27b each carry 8,000 a minute —
but the app metered every model through one bucket, so an ingest calling the vision model
for pages and the text model for the topic map competed with itself for half the
allowance it actually had.
"""
import pytest

from app.llm.rate_limit import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(tokens_per_minute=8000, requests_per_minute=600)


def test_each_model_starts_with_a_full_allowance(limiter):
    limiter.acquire(7000, model="vision-model")
    # The text model's budget is untouched by the vision model's spending.
    limiter.acquire(7000, model="text-model")


def test_one_model_draining_does_not_block_another(limiter):
    vision = limiter.bucket("vision-model")
    text = limiter.bucket("text-model")
    limiter.acquire(8000, model="vision-model")
    assert vision is not text
    assert text._state.available == pytest.approx(8000, abs=1)


def test_the_same_model_shares_one_bucket(limiter):
    first = limiter.bucket("qwen")
    second = limiter.bucket("qwen")
    assert first is second


def test_reconcile_returns_tokens_to_the_right_model(limiter):
    limiter.acquire(4000, model="vision-model")
    before_text = limiter.bucket("text-model")._state.available
    limiter.reconcile(4000, 1200, model="vision-model")
    # Reserved 4,000 and spent 1,200, so only the 1,200 stays spent.
    assert limiter.bucket("vision-model")._state.available == pytest.approx(6800, abs=2)
    assert limiter.bucket("text-model")._state.available == pytest.approx(before_text, abs=1)


def test_a_backoff_penalises_only_the_model_that_earned_it(limiter):
    limiter.back_off(30, model="vision-model")
    assert limiter.bucket("text-model")._state.available == pytest.approx(8000, abs=1)


def test_callers_without_a_model_share_one_default_bucket(limiter):
    assert limiter.bucket(None) is limiter.tokens
    assert limiter.bucket(None) is limiter.bucket(None)
