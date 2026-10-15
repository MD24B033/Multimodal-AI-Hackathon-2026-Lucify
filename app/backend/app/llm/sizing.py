"""How many tokens to reserve for a call that has not happened yet.

Reserving `prompt + max_completion_tokens` throttled the app to roughly half its real
throughput. Measured against the provider, two identical 21-token replies decremented
the remaining-tokens header by the same amount whether max_completion_tokens was 50 or
3,000:

    max_tokens=50    -> remaining 7931, actual 21
    max_tokens=3000  -> remaining 7979, actual 21

So the ceiling is charged on what a call spends, not on what it was allowed to spend,
and a page of vision booking 1,770 tokens to spend 919 was paying twice for the same
work. Reservations are now sized from what calls of that kind have actually cost, and
the existing reconcile step settles the difference the moment the real figure is known.

The estimate is an upper-middle percentile rather than a worst case. The bucket is our
own throttle, not the provider's admission test, and `reconcile` charges the shortfall
the instant the real usage is known, so an under-estimate costs a top-up on a bucket
that refills continuously. Reserving for the longest reply ever seen would simply
reinstate the problem this module exists to remove.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque

# Seeds for a cold process, from the measured distribution of each task. They are
# replaced by observation as soon as a few calls of that kind have been made.
SEEDS: dict[str, int] = {
    # Roughly the 75th percentile of each task's measured completions.
    "vision": 300,
    "keyframe": 300,
    "figure": 300,
    "chat": 320,
    "verification": 140,
    "question_generation": 800,
    "notes": 1200,
    "report": 600,
    "session_summary": 130,
    "grading": 200,
}
DEFAULT_SEED = 400
FLOOR = 128
HISTORY = 24


class CompletionSizer:
    """Tracks what completions of each kind actually cost."""

    def __init__(self) -> None:
        self._seen: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=HISTORY))
        self._lock = threading.Lock()

    def observe(self, task: str, completion_tokens: int) -> None:
        if completion_tokens > 0:
            with self._lock:
                self._seen[task].append(int(completion_tokens))

    def expected(self, task: str, ceiling: int) -> int:
        """A high percentile of recent completions for this task, bounded by the
        ceiling the caller already set."""
        with self._lock:
            samples = sorted(self._seen.get(task, ()))

        if len(samples) >= 5:
            index = min(len(samples) - 1, int(round(0.75 * (len(samples) - 1))))
            estimate = samples[index]
        else:
            estimate = SEEDS.get(task, DEFAULT_SEED)

        return max(FLOOR, min(ceiling, estimate))


_sizer = CompletionSizer()


def expected_completion(task: str, ceiling: int) -> int:
    return _sizer.expected(task, ceiling)


def observe_completion(task: str, completion_tokens: int) -> None:
    _sizer.observe(task, completion_tokens)
