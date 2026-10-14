"""The shared token budget, against a fake Upstash.

The behaviour that matters is giving change: a reservation assumes the completion
runs to max_tokens, and on an 8,000 token minute an unreconciled reservation pushes
the next question into the following window.
"""
import pytest

from app.upstash import SharedTokenBudget


class FakeUpstash:
    """Just enough of the REST client: INCRBY/DECRBY against one counter."""

    def __init__(self):
        self.values: dict[str, int] = {}
        self.failing = False

    def pipeline(self, commands):
        if self.failing:
            raise RuntimeError("upstash unreachable")
        results = []
        for command in commands:
            results.append(self.command(*command))
        return results

    def command(self, name, key, *args):
        if self.failing:
            raise RuntimeError("upstash unreachable")
        if name == "INCRBY":
            self.values[key] = self.values.get(key, 0) + int(args[0])
            return self.values[key]
        if name == "DECRBY":
            self.values[key] = self.values.get(key, 0) - int(args[0])
            return self.values[key]
        if name == "EXPIRE":
            return 1
        raise AssertionError(f"unexpected command {name}")

    @property
    def used(self):
        return sum(self.values.values())


@pytest.fixture
def budget():
    client = FakeUpstash()
    return client, SharedTokenBudget(client, tokens_per_minute=8000)


def test_consumption_accumulates(budget):
    client, shared = budget
    assert shared.try_consume(3000)[0] is True
    assert shared.try_consume(3000)[0] is True
    assert client.used == 6000


def test_a_request_over_the_limit_is_refused_and_not_charged(budget):
    client, shared = budget
    shared.try_consume(6000)
    allowed, wait = shared.try_consume(4000)
    assert allowed is False
    assert client.used == 6000, "a refused request must not stay booked"
    assert 0 < wait <= 60


def test_refund_returns_the_unspent_reservation(budget):
    client, shared = budget
    shared.try_consume(4000)      # reserved, assuming max_tokens
    shared.refund(4000 - 1800)    # actually spent 1800
    assert client.used == 1800

    # which is what leaves room for the next question inside the same minute
    assert shared.try_consume(4000)[0] is True


def test_refund_ignores_nonsense(budget):
    client, shared = budget
    shared.try_consume(1000)
    shared.refund(0)
    shared.refund(-500)
    assert client.used == 1000


def test_an_unreachable_budget_does_not_block_the_request(budget):
    client, shared = budget
    client.failing = True
    allowed, wait = shared.try_consume(1000)
    assert allowed is True, "a coordination outage must not take the app down"
    assert wait == 0.0
    shared.refund(500)  # must not raise either


def test_each_minute_gets_its_own_window(budget, monkeypatch):
    client, shared = budget
    monkeypatch.setattr("app.upstash.time.time", lambda: 60.0)
    shared.try_consume(8000)
    assert shared.try_consume(1000)[0] is False
    monkeypatch.setattr("app.upstash.time.time", lambda: 121.0)
    assert shared.try_consume(1000)[0] is True
