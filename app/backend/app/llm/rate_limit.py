import threading
import time
from dataclasses import dataclass


@dataclass
class BucketState:
    capacity: float
    available: float
    refill_per_second: float
    updated_at: float


class TokenBucket:
    def __init__(self, capacity: int, refill_per_minute: int | None = None):
        refill = refill_per_minute if refill_per_minute is not None else capacity
        self._state = BucketState(
            capacity=float(capacity),
            available=float(capacity),
            refill_per_second=refill / 60.0,
            updated_at=time.monotonic(),
        )
        self._condition = threading.Condition()

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._state.updated_at
        if elapsed <= 0:
            return
        self._state.available = min(
            self._state.capacity,
            self._state.available + elapsed * self._state.refill_per_second,
        )
        self._state.updated_at = now

    def acquire(self, amount: float, timeout: float = 300.0) -> None:
        amount = min(float(amount), self._state.capacity)
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                self._refill_locked()
                if self._state.available >= amount:
                    self._state.available -= amount
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for rate limit capacity")
                deficit = amount - self._state.available
                wait = min(remaining, deficit / self._state.refill_per_second + 0.05)
                self._condition.wait(timeout=wait)

    def release(self, amount: float) -> None:
        with self._condition:
            self._refill_locked()
            self._state.available = min(self._state.capacity, self._state.available + max(0.0, amount))
            self._condition.notify_all()

    def penalise(self, seconds: float) -> None:
        with self._condition:
            self._refill_locked()
            self._state.available = max(
                0.0, self._state.available - seconds * self._state.refill_per_second
            )

    @property
    def available(self) -> float:
        with self._condition:
            self._refill_locked()
            return self._state.available


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown_seconds: float):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._last_error: str = ""
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_error = error
            if self._consecutive_failures >= self.threshold and self._opened_at is None:
                self._opened_at = time.monotonic()

    def failure_reason(self) -> str | None:
        with self._lock:
            if self._opened_at is None:
                return None
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self._opened_at = None
                self._consecutive_failures = 0
                return None
            return (
                f"{self._consecutive_failures} consecutive upstream failures; "
                f"last error: {self._last_error[:200]}"
            )

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures


class RateLimiter:
    """Token buckets per model, requests shared.

    Groq meters tokens per model, so one bucket for all of them throttled the app to a
    fraction of its real allowance whenever two model families were in play at once.
    Requests stay on a single bucket: that limit is generous and per account.
    """

    def __init__(self, tokens_per_minute: int, requests_per_minute: int):
        self.tokens_per_minute = tokens_per_minute
        self._buckets: dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()
        self.requests = TokenBucket(requests_per_minute)
        self._priority_gate = threading.Condition()
        self._waiting_interactive = 0

    def bucket(self, model: str | None = None) -> TokenBucket:
        key = model or "default"
        with self._buckets_lock:
            existing = self._buckets.get(key)
            if existing is None:
                existing = TokenBucket(self.tokens_per_minute)
                self._buckets[key] = existing
            return existing

    @property
    def tokens(self) -> TokenBucket:
        """The default bucket, for callers that do not name a model."""
        return self.bucket(None)

    def _enter_batch(self) -> None:
        with self._priority_gate:
            while self._waiting_interactive > 0:
                self._priority_gate.wait(timeout=0.5)

    def _enter_interactive(self) -> None:
        with self._priority_gate:
            self._waiting_interactive += 1

    def _leave_interactive(self) -> None:
        with self._priority_gate:
            self._waiting_interactive = max(0, self._waiting_interactive - 1)
            self._priority_gate.notify_all()

    def acquire(
        self, estimated_tokens: int, interactive: bool = False, model: str | None = None
    ) -> None:
        tokens = self.bucket(model)
        if interactive:
            self._enter_interactive()
            try:
                self.requests.acquire(1)
                tokens.acquire(estimated_tokens)
            finally:
                self._leave_interactive()
            return

        self._enter_batch()
        self.requests.acquire(1)
        tokens.acquire(estimated_tokens)

    def reconcile(
        self, estimated_tokens: int, actual_tokens: int, model: str | None = None
    ) -> None:
        tokens = self.bucket(model)
        delta = estimated_tokens - actual_tokens
        if delta > 0:
            tokens.release(delta)
        elif delta < 0:
            tokens.acquire(-delta, timeout=120.0)

    def back_off(self, seconds: float, model: str | None = None) -> None:
        self.bucket(model).penalise(seconds)
