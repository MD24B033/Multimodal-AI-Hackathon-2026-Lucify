"""Per-request stage timings.

A single number for "latency" hides the only thing worth knowing on a free tier:
whether the time went on work or on waiting for quota. The evaluation run reported a
58 second median while the same question answered in 3.6 seconds with the bucket
free, so the breakdown is the measurement, not a detail.

Timings are collected per request through a context variable, so concurrent requests
cannot mix, and a stage that is never reached simply does not appear.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

_stages: ContextVar[dict[str, float] | None] = ContextVar("llm_stage_timings", default=None)


@contextmanager
def capture():
    """Starts a fresh collection for one request and yields the dict it fills."""
    collected: dict[str, float] = {}
    token = _stages.set(collected)
    try:
        yield collected
    finally:
        _stages.reset(token)


@contextmanager
def stage(name: str):
    """Adds the elapsed milliseconds to `name`, accumulating across repeat visits —
    a retried provider call should read as the total time that call cost."""
    started = time.perf_counter()
    try:
        yield
    finally:
        collected = _stages.get()
        if collected is not None:
            elapsed = (time.perf_counter() - started) * 1000
            collected[name] = round(collected.get(name, 0.0) + elapsed, 1)


def record(name: str, milliseconds: float) -> None:
    collected = _stages.get()
    if collected is not None:
        collected[name] = round(collected.get(name, 0.0) + milliseconds, 1)


def collected() -> dict[str, float]:
    return dict(_stages.get() or {})
