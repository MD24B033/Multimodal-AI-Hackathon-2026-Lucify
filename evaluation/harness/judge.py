from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Any

import httpx

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class JudgeError(RuntimeError):
    pass


class SharedWindow:
    """Optional: when UPSTASH_REDIS_REST_* are set, the harness draws from the same
    per-minute window as the running app instead of assuming it owns the whole limit."""

    def __init__(self, url: str, token: str, limit: int):
        self.url = url.strip().strip('"').rstrip("/")
        self.token = token.strip().strip('"')
        self.limit = limit
        self._client = httpx.Client(
            timeout=15.0, headers={"Authorization": f"Bearer {self.token}"}
        )

    def try_consume(self, tokens: int) -> tuple[bool, float]:
        key = f"lucify:tokens:{int(time.time() // 60)}"
        try:
            response = self._client.post(
                f"{self.url}/pipeline",
                json=[["INCRBY", key, str(tokens)], ["EXPIRE", key, "120"]],
            )
            if response.status_code != 200:
                return True, 0.0
            used = int(response.json()[0]["result"])
        except Exception:
            return True, 0.0

        remaining = 60 - (time.time() % 60)
        if used > self.limit:
            try:
                self._client.post(self.url, json=["DECRBY", key, str(tokens)])
            except Exception:
                pass
            return False, remaining
        return True, remaining


class TokenBudget:
    def __init__(self, tokens_per_minute: int):
        self.capacity = float(tokens_per_minute)
        self.available = float(tokens_per_minute)
        self.rate = tokens_per_minute / 60.0
        self.updated = time.monotonic()
        self._condition = threading.Condition()

    def spend(self, amount: float) -> None:
        amount = min(amount, self.capacity)
        with self._condition:
            while True:
                now = time.monotonic()
                self.available = min(
                    self.capacity, self.available + (now - self.updated) * self.rate
                )
                self.updated = now
                if self.available >= amount:
                    self.available -= amount
                    return
                self._condition.wait(timeout=(amount - self.available) / self.rate + 0.05)


class GroqJudge:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
        tokens_per_minute: int = 8000,
        max_retries: int = 5,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not self.api_key:
            raise JudgeError("GROQ_API_KEY is not set")
        self.base_url = base_url.rstrip("/")
        self.budget = TokenBudget(tokens_per_minute)
        self.shared = None
        upstash_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
        upstash_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
        if upstash_url and upstash_token:
            shared_limit = int(os.environ.get("SHARED_TOKENS_PER_MINUTE", "8000"))
            self.shared = SharedWindow(upstash_url, upstash_token, shared_limit)
        self.max_retries = max_retries
        self._client = httpx.Client(
            timeout=180.0, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.calls = 0
        self.tokens_used = 0

    def close(self) -> None:
        self._client.close()

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.2,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "reasoning_effort": "low",
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema, "strict": True},
            }

        estimate = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 400
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            self.budget.spend(estimate)
            if self.shared is not None:
                for _ in range(12):
                    allowed, wait = self.shared.try_consume(estimate)
                    if allowed:
                        break
                    time.sleep(min(max(wait, 0.5), 10.0))
            try:
                response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(min(2**attempt, 20) + random.uniform(0, 0.5))
                continue

            if response.status_code == 200:
                body = response.json()
                usage = body.get("usage") or {}
                self.calls += 1
                self.tokens_used += int(usage.get("total_tokens", estimate))
                return body["choices"][0]["message"].get("content") or ""

            last_error = JudgeError(f"{response.status_code}: {response.text[:250]}")
            if response.status_code not in RETRYABLE:
                raise last_error
            time.sleep(min(2**attempt, 20) + random.uniform(0, 0.5))

        raise JudgeError(f"Judge call failed after {self.max_retries} attempts: {last_error}")

    def complete_json(self, messages: list[dict[str, Any]], **kwargs) -> Any:
        raw = self.complete(messages, **kwargs)
        return parse_json(raw)


def parse_json(text: str) -> Any:
    candidate = text.strip()
    if not candidate:
        raise JudgeError("Empty judge response")
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise JudgeError(f"Could not parse judge JSON: {text[:200]}")
