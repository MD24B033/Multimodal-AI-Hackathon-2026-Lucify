from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.llm import timing
from app.llm.rate_limit import CircuitBreaker, RateLimiter

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class GroqError(RuntimeError):
    pass


class GroqUnavailable(GroqError):
    pass


class GroqDailyQuotaExhausted(GroqError):
    def __init__(self, message: str, retry_after_seconds: float = 0.0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


_DAILY_LIMIT = re.compile(
    r"tokens per day \(TPD\): Limit (\d+), Used (\d+)", re.IGNORECASE
)


def daily_quota_error(body: str, retry_after: float) -> GroqDailyQuotaExhausted | None:
    match = _DAILY_LIMIT.search(body or "")
    if match is None:
        return None
    limit, used = int(match.group(1)), int(match.group(2))
    wait = f" Resets in about {retry_after / 60:.0f} minutes." if retry_after else ""
    return GroqDailyQuotaExhausted(
        f"Daily token quota exhausted: {used:,} of {limit:,} tokens used today.{wait} "
        f"Ingestion and evaluation are the heavy consumers. Upgrade the Groq tier or wait for reset.",
        retry_after_seconds=retry_after,
    )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    cached: bool = False
    task: str = "other"
    raw: dict[str, Any] = field(default_factory=dict)

    def json(self) -> Any:
        return parse_json(self.text)


def parse_json(text: str) -> Any:
    candidate = text.strip()
    if not candidate:
        raise GroqError("Empty response while expecting JSON")
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise GroqError(f"Could not parse JSON from model output: {text[:300]}")


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)", re.IGNORECASE)
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    parts = _DURATION_PART.findall(text)
    if not parts:
        return None

    total = 0.0
    for amount, unit in parts:
        total += float(amount) * _DURATION_UNITS[unit.lower()]
    return total


def _with_schema_instruction(
    messages: list[dict[str, Any]], schema: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if schema is None:
        instruction = "Respond with a single valid JSON object and nothing else."
    else:
        instruction = (
            "Respond with a single valid JSON object and nothing else. "
            "It must conform to this JSON schema:\n"
            f"{json.dumps(schema, separators=(',', ':'))}"
        )

    adjusted = [dict(message) for message in messages]
    for message in reversed(adjusted):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            message["content"] = f"{message['content']}\n\n{instruction}"
            return adjusted

    adjusted.append({"role": "user", "content": instruction})
    return adjusted


def estimate_tokens(payload: Any) -> int:
    if isinstance(payload, str):
        return max(1, len(payload) // 4)
    if isinstance(payload, list):
        total = 0
        for message in payload:
            content = message.get("content") if isinstance(message, dict) else message
            if isinstance(content, str):
                total += len(content) // 4
            elif isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        total += len(part.get("text", "")) // 4
                    else:
                        total += 800
            total += 4
        return max(1, total)
    return max(1, len(str(payload)) // 4)


class ResponseCache:
    def __init__(self):
        self._lock = threading.Lock()

    def _fingerprint(self, model: str, payload: dict[str, Any]) -> str:
        material = json.dumps({"model": model, "payload": payload}, sort_keys=True, default=str)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, model: str, payload: dict[str, Any]) -> Completion | None:
        from app.db.database import session_scope
        from app.db.models import LLMCache

        key = self._fingerprint(model, payload)
        try:
            with session_scope() as session:
                row = session.get(LLMCache, key)
                if row is None:
                    return None
                return Completion(
                    text=row.response.get("text", ""),
                    model=row.model,
                    usage=Usage(row.prompt_tokens, row.completion_tokens),
                    cached=True,
                    raw=row.response,
                )
        except Exception:
            logger.debug("LLM cache lookup failed", exc_info=True)
            return None

    def put(self, model: str, payload: dict[str, Any], completion: Completion) -> None:
        from sqlalchemy.dialects.postgresql import insert

        from app.db.database import session_scope
        from app.db.models import LLMCache

        key = self._fingerprint(model, payload)
        try:
            with self._lock, session_scope() as session:
                statement = insert(LLMCache).values(
                    key=key,
                    model=model,
                    task=completion.task,
                    response={"text": completion.text},
                    prompt_tokens=completion.usage.prompt_tokens,
                    completion_tokens=completion.usage.completion_tokens,
                )
                session.execute(statement.on_conflict_do_nothing(index_elements=[LLMCache.key]))
        except Exception:
            logger.debug("LLM cache write failed", exc_info=True)


class GroqClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.groq_api_key
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")
        self.limiter = RateLimiter(settings.tokens_per_minute, settings.requests_per_minute)
        self.breaker = CircuitBreaker(
            settings.circuit_breaker_threshold, settings.circuit_breaker_cooldown_seconds
        )
        self.shared_budget = _build_shared_budget()
        self.cache = ResponseCache()
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def _post(
        self, path: str, *, estimated_tokens: int, interactive: bool = False, **kwargs
    ) -> httpx.Response:
        if not self.api_key:
            raise GroqError("GROQ_API_KEY is not configured")

        tripped = self.breaker.failure_reason()
        if tripped is not None:
            raise GroqUnavailable(f"Upstream looks unavailable, not retrying: {tripped}")

        last_error: Exception | None = None
        for attempt in range(settings.max_retries):
            with timing.stage("local_bucket_ms"):
                self.limiter.acquire(estimated_tokens, interactive=interactive)
            with timing.stage("shared_budget_ms"):
                self._await_shared_budget(estimated_tokens)
            try:
                with timing.stage("provider_ms"):
                    response = self._client.post(f"{self.base_url}{path}", **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                self.breaker.record_success()
                return response

            retry_after = self._retry_after_seconds(response)

            if response.status_code == 429:
                exhausted = daily_quota_error(response.text, retry_after)
                if exhausted is not None:
                    self.breaker.record_success()
                    raise exhausted

            last_error = GroqError(f"{response.status_code}: {response.text[:400]}")
            if response.status_code not in RETRYABLE_STATUS:
                self.breaker.record_success()
                raise last_error

            if retry_after:
                self.limiter.back_off(retry_after)
            self._sleep_backoff(attempt, retry_after)

        self.breaker.record_failure(str(last_error))
        raise GroqUnavailable(
            f"Groq request failed after {settings.max_retries} attempts: {last_error}"
        )

    def _await_shared_budget(self, tokens: int) -> None:
        """Every process pointing at the same Upstash database draws from one budget,
        so the API and the evaluation harness cannot each assume the whole allowance."""
        if self.shared_budget is None:
            return
        for _ in range(12):
            allowed, wait = self.shared_budget.try_consume(tokens)
            if allowed:
                return
            time.sleep(min(max(wait, 0.5), 10.0))
        logger.warning("Shared token budget stayed exhausted; proceeding and letting the API arbitrate")

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            value = response.headers.get(header)
            if value:
                parsed = parse_duration(value)
                if parsed is not None:
                    return parsed
        return 0.0

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: float = 0.0) -> None:
        delay = max(retry_after, min(2**attempt, 30))
        delay = min(delay, settings.max_backoff_seconds) + random.uniform(0, 0.75)
        time.sleep(delay)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1600,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        use_cache: bool = True,
        reasoning_effort: str | None = None,
        interactive: bool = False,
        task: str = "other",
    ) -> Completion:
        model = model or settings.generation_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": response_schema, "strict": True},
            }
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        if use_cache and temperature <= 0.3:
            hit = self.cache.get(model, payload)
            if hit is not None:
                return hit

        prompt_estimate = estimate_tokens(messages)
        if prompt_estimate + max_tokens > settings.tokens_per_minute:
            logger.warning(
                "Request budget %d (prompt %d + max_tokens %d) exceeds the %d/min limit; "
                "it will be throttled",
                prompt_estimate + max_tokens,
                prompt_estimate,
                max_tokens,
                settings.tokens_per_minute,
            )
        # Groq admits a request against max_completion_tokens, not actual usage, so
        # reserving less than that guarantees a 429 and a wasted backoff.
        estimated = prompt_estimate + max_tokens
        try:
            response = self._post(
                "/chat/completions",
                estimated_tokens=estimated,
                interactive=interactive,
                json=payload,
            )
        except GroqError as exc:
            if "json_validate_failed" not in str(exc) or max_tokens >= 16000:
                raise
            logger.info("Structured output truncated at %d tokens, retrying with more headroom", max_tokens)
            return self.complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=min(16000, max_tokens * 2),
                response_schema=response_schema,
                json_mode=json_mode,
                use_cache=use_cache,
                reasoning_effort=reasoning_effort or "low",
                interactive=interactive,
                task=task,
            )
        body = response.json()
        choice = body["choices"][0]["message"]
        text = choice.get("content") or ""
        usage_body = body.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_body.get("prompt_tokens", 0)),
            completion_tokens=int(usage_body.get("completion_tokens", 0)),
        )
        self.limiter.reconcile(estimated, usage.total or estimated)

        completion = Completion(text=text, model=model, usage=usage, task=task, raw=body)
        if use_cache and temperature <= 0.3 and text:
            self.cache.put(model, payload, completion)
        return completion

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
        supports_structured_output: bool = True,
        **kwargs,
    ) -> Any:
        if schema is not None and supports_structured_output:
            completion = self.complete(messages, model=model, response_schema=schema, **kwargs)
        else:
            completion = self.complete(
                _with_schema_instruction(messages, schema), model=model, json_mode=True, **kwargs
            )
        return completion.json()

    def describe_image(
        self,
        image_data_url: str,
        instruction: str,
        *,
        model: str | None = None,
        max_tokens: int = 700,
        task: str = "vision",
    ) -> Completion:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ]
        return self.complete(
            messages,
            model=model or settings.vision_model,
            temperature=0.1,
            max_tokens=max_tokens,
            task=task,
        )

    def transcribe(
        self,
        audio_path: Path,
        *,
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        model = model or settings.transcription_model
        data = {
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        size_tokens = max(200, int(audio_path.stat().st_size / 8000))
        with audio_path.open("rb") as handle:
            response = self._post(
                "/audio/transcriptions",
                estimated_tokens=min(size_tokens, settings.tokens_per_minute // 2),
                files={"file": (audio_path.name, handle, "application/octet-stream")},
                data=data,
            )
        return response.json()

    def synthesize_speech(self, text: str, *, voice: str | None = None, model: str | None = None) -> bytes:
        payload = {
            "model": model or settings.tts_model,
            "voice": voice or settings.tts_voice,
            "input": text,
            "response_format": "wav",
        }
        response = self._post("/audio/speech", estimated_tokens=estimate_tokens(text), json=payload)
        return response.content


def _build_shared_budget():
    if not settings.share_token_budget:
        return None
    try:
        from app.upstash import SharedTokenBudget, get_upstash

        client = get_upstash()
        if client is None:
            return None
        logger.info("Token budget shared across processes via Upstash")
        return SharedTokenBudget(client, settings.tokens_per_minute)
    except Exception:
        logger.debug("Could not build the shared token budget", exc_info=True)
        return None


_client: GroqClient | None = None
_client_lock = threading.Lock()


def get_client() -> GroqClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = GroqClient()
    return _client
