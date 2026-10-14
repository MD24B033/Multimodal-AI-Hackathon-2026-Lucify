from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class UpstashError(RuntimeError):
    pass


class UpstashRest:
    """Upstash's REST API speaks commands over HTTP. There is no persistent connection,
    so SUBSCRIBE is unavailable and anything live has to be polled."""

    def __init__(self, url: str, token: str, timeout: float = 15.0):
        self.url = url.strip().strip('"').rstrip("/")
        self.token = token.strip().strip('"')
        if not self.url or not self.token:
            raise UpstashError("Upstash URL and token are both required")
        self._client = httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {self.token}"}
        )

    def close(self) -> None:
        self._client.close()

    def command(self, *args: Any) -> Any:
        response = self._client.post(self.url, json=[str(arg) for arg in args])
        if response.status_code != 200:
            raise UpstashError(f"{response.status_code}: {response.text[:200]}")
        return response.json().get("result")

    def pipeline(self, commands: list[list[Any]]) -> list[Any]:
        payload = [[str(part) for part in command] for command in commands]
        response = self._client.post(f"{self.url}/pipeline", json=payload)
        if response.status_code != 200:
            raise UpstashError(f"{response.status_code}: {response.text[:200]}")
        return [entry.get("result") for entry in response.json()]

    def ping(self) -> bool:
        try:
            self.command("SET", "lucify:health", "1", "EX", "60")
            return True
        except Exception:
            return False


_client: UpstashRest | None = None
_lock = threading.Lock()


def get_upstash() -> UpstashRest | None:
    global _client
    if not settings.upstash_url or not settings.upstash_token:
        return None
    if _client is None:
        with _lock:
            if _client is None:
                try:
                    _client = UpstashRest(settings.upstash_url, settings.upstash_token)
                except UpstashError:
                    logger.warning("Upstash credentials present but unusable", exc_info=True)
                    return None
    return _client


class SharedTokenBudget:
    """A fixed-window token counter shared by every process that points at the same
    Upstash database. Without this, the API and the evaluation harness each believe
    they own the whole per-minute budget and together trip the provider's limit."""

    def __init__(self, client: UpstashRest, tokens_per_minute: int, namespace: str = "lucify"):
        self.client = client
        self.limit = tokens_per_minute
        self.namespace = namespace

    def _key(self) -> str:
        return f"{self.namespace}:tokens:{int(time.time() // 60)}"

    def try_consume(self, tokens: int) -> tuple[bool, float]:
        """Returns (allowed, seconds_until_window_resets)."""
        key = self._key()
        try:
            used, _ = self.client.pipeline([["INCRBY", key, tokens], ["EXPIRE", key, 120]])
        except Exception:
            logger.debug("Shared budget check failed, allowing locally", exc_info=True)
            return True, 0.0

        remaining_window = 60 - (time.time() % 60)
        if int(used) > self.limit:
            try:
                self.client.command("DECRBY", key, tokens)
            except Exception:
                pass
            return False, remaining_window
        return True, remaining_window

    def refund(self, tokens: int) -> None:
        """Give back the difference between what a call reserved and what it spent.

        A reservation has to assume the completion runs to max_tokens, so a chat turn
        books around 4,000 tokens and typically spends half that. Without this the
        unspent half stays booked for the rest of the minute, and on an 8,000 token
        minute that is enough to push the next question into the following window --
        which is most of what the 58 second evaluation median was measuring.
        """
        if tokens <= 0:
            return
        try:
            self.client.command("DECRBY", self._key(), tokens)
        except Exception:
            logger.debug("Could not refund unused tokens", exc_info=True)

    def usage(self) -> int:
        try:
            value = self.client.command("GET", self._key())
            return int(value) if value else 0
        except Exception:
            return 0
