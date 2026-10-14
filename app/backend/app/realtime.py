from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
TICK_SECONDS = 0.25

_shutdown = threading.Event()


def begin_shutdown() -> None:
    """Progress streams outlive the request that opened them, so they have to be told
    to stop or the server cannot exit."""
    _shutdown.set()


def resume_after_shutdown() -> None:
    _shutdown.clear()


def shutting_down() -> bool:
    return _shutdown.is_set()


def install_shutdown_signals() -> None:
    """Uvicorn waits for in-flight requests before it runs lifespan shutdown, and an
    event stream is in flight for as long as a browser holds it. Hearing the signal
    ourselves lets the streams close instead of pinning the server."""
    import signal

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous = signal.getsignal(signum)
        except (ValueError, OSError):
            continue

        def handler(received, frame, _previous=previous):
            begin_shutdown()
            if callable(_previous):
                _previous(received, frame)

        try:
            signal.signal(signum, handler)
        except (ValueError, OSError):
            continue


class _Pump:
    """Reads a channel once on behalf of every listener watching it. Upstash bills per
    command, so a second browser on the same ingestion must not double the traffic."""

    def __init__(self, channel: str):
        self.channel = channel
        self.listeners: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def attach(self) -> queue.Queue:
        listener: queue.Queue = queue.Queue(maxsize=256)
        with self.lock:
            self.listeners.append(listener)
            if self.thread is None or not self.thread.is_alive():
                self.start()
                self.thread = threading.Thread(
                    target=self._run, name=f"pump-{self.channel}"[:40], daemon=True
                )
                self.thread.start()
        return listener

    def detach(self, listener: queue.Queue) -> None:
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def fan_out(self, event: dict[str, Any]) -> None:
        with self.lock:
            listeners = list(self.listeners)
        for listener in listeners:
            try:
                listener.put_nowait(event)
            except queue.Full:
                continue

    def start(self) -> None:
        """Hook for subclasses that need to position a cursor before reading."""

    def stop(self) -> None:
        """Hook for subclasses holding a connection."""

    def poll(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def idle_interval(self, current: float) -> float:
        return current

    def _run(self) -> None:
        interval = TICK_SECONDS
        try:
            while not shutting_down():
                with self.lock:
                    if not self.listeners:
                        self.thread = None
                        return
                try:
                    events = self.poll()
                except Exception:
                    logger.debug("Progress poll failed for %s", self.channel, exc_info=True)
                    events = []

                if events:
                    interval = TICK_SECONDS
                    for event in events:
                        self.fan_out(event)
                else:
                    interval = self.idle_interval(interval)

                waited = 0.0
                while waited < interval and not shutting_down():
                    time.sleep(TICK_SECONDS)
                    waited += TICK_SECONDS
        finally:
            self.stop()


class InProcessBroker:
    name = "in-process"

    def __init__(self):
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._latest[channel] = payload
            listeners = list(self._subscribers.get(channel, []))
        for listener in listeners:
            try:
                listener.put_nowait(payload)
            except queue.Full:
                continue

    def latest(self, channel: str) -> dict[str, Any] | None:
        with self._lock:
            return self._latest.get(channel)

    def attach(self, channel: str) -> queue.Queue:
        listener: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.setdefault(channel, []).append(listener)
        return listener

    def detach(self, channel: str, listener: queue.Queue) -> None:
        with self._lock:
            remaining = self._subscribers.get(channel, [])
            if listener in remaining:
                remaining.remove(listener)


class _RedisPump(_Pump):
    def __init__(self, channel: str, client):
        super().__init__(channel)
        self._client = client
        self._pubsub = None

    def start(self) -> None:
        self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        self._pubsub.subscribe(self.channel)

    def stop(self) -> None:
        try:
            if self._pubsub is not None:
                self._pubsub.close()
        except Exception:
            pass
        self._pubsub = None

    def poll(self) -> list[dict[str, Any]]:
        if self._pubsub is None:
            return []
        events = []
        while True:
            message = self._pubsub.get_message(timeout=0.01)
            if not message:
                break
            data = message.get("data")
            if not data:
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                continue
        return events


class RedisBroker:
    name = "redis"

    def __init__(self, url: str):
        import redis

        self._redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
        self._redis.ping()
        self._pumps: dict[str, _RedisPump] = {}
        self._lock = threading.Lock()

    def _key(self, channel: str) -> str:
        return f"progress:{channel}"

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, default=str)
        try:
            pipeline = self._redis.pipeline()
            pipeline.set(self._key(channel), encoded, ex=settings.realtime_state_ttl_seconds)
            pipeline.publish(channel, encoded)
            pipeline.execute()
        except Exception:
            logger.debug("Redis publish failed for %s", channel, exc_info=True)

    def latest(self, channel: str) -> dict[str, Any] | None:
        try:
            stored = self._redis.get(self._key(channel))
            return json.loads(stored) if stored else None
        except Exception:
            logger.debug("Redis read failed for %s", channel, exc_info=True)
            return None

    def _pump(self, channel: str) -> _RedisPump:
        with self._lock:
            pump = self._pumps.get(channel)
            if pump is None:
                pump = _RedisPump(channel, self._redis)
                self._pumps[channel] = pump
            return pump

    def attach(self, channel: str) -> queue.Queue:
        return self._pump(channel).attach()

    def detach(self, channel: str, listener: queue.Queue) -> None:
        self._pump(channel).detach(listener)


class _UpstashPump(_Pump):
    def __init__(self, channel: str, broker: "UpstashBroker"):
        super().__init__(channel)
        self.broker = broker
        self.cursor = "0"

    def start(self) -> None:
        self.cursor = self.broker.newest_id(self.channel)

    def poll(self) -> list[dict[str, Any]]:
        events, self.cursor = self.broker.read_since(self.channel, self.cursor)
        return events

    def idle_interval(self, current: float) -> float:
        floor = max(settings.upstash_poll_seconds, TICK_SECONDS)
        return min(max(current * 1.5, floor), settings.upstash_idle_poll_seconds)


class UpstashBroker:
    """Upstash speaks Redis over HTTP, which rules out SUBSCRIBE. Events go into a capped
    stream and are read forward from a cursor, so each poll costs one command and returns
    only what is new."""

    name = "upstash"
    KEEP = 100

    def __init__(self, client):
        self._client = client
        self._pumps: dict[str, _UpstashPump] = {}
        self._lock = threading.Lock()

    def _key(self, channel: str) -> str:
        return f"stream:{channel}"

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        key = self._key(channel)
        try:
            self._client.pipeline(
                [
                    ["XADD", key, "MAXLEN", "~", self.KEEP, "*", "d", json.dumps(payload, default=str)],
                    ["EXPIRE", key, settings.realtime_state_ttl_seconds],
                ]
            )
        except Exception:
            logger.debug("Upstash publish failed for %s", channel, exc_info=True)

    @staticmethod
    def _decode(entry: Any) -> dict[str, Any] | None:
        try:
            _entry_id, fields = entry
            pairs = dict(zip(fields[::2], fields[1::2]))
            return json.loads(pairs["d"])
        except Exception:
            return None

    def newest_id(self, channel: str) -> str:
        try:
            rows = self._client.command("XREVRANGE", self._key(channel), "+", "-", "COUNT", 1)
        except Exception:
            return "0"
        return str(rows[0][0]) if rows else "0"

    def read_since(self, channel: str, cursor: str) -> tuple[list[dict[str, Any]], str]:
        start = "-" if cursor == "0" else f"({cursor}"
        rows = self._client.command("XRANGE", self._key(channel), start, "+", "COUNT", self.KEEP)
        if not rows:
            return [], cursor

        events = []
        for row in rows:
            decoded = self._decode(row)
            if decoded is not None:
                events.append(decoded)
        return events, str(rows[-1][0])

    def latest(self, channel: str) -> dict[str, Any] | None:
        try:
            rows = self._client.command("XREVRANGE", self._key(channel), "+", "-", "COUNT", 1)
        except Exception:
            return None
        return self._decode(rows[0]) if rows else None

    def _pump(self, channel: str) -> _UpstashPump:
        with self._lock:
            pump = self._pumps.get(channel)
            if pump is None:
                pump = _UpstashPump(channel, self)
                self._pumps[channel] = pump
            return pump

    def attach(self, channel: str) -> queue.Queue:
        return self._pump(channel).attach()

    def detach(self, channel: str, listener: queue.Queue) -> None:
        self._pump(channel).detach(listener)


_broker: InProcessBroker | RedisBroker | UpstashBroker | None = None
_broker_lock = threading.Lock()


def get_broker():
    global _broker
    if _broker is None:
        with _broker_lock:
            if _broker is None:
                _broker = _build_broker()
    return _broker


def _build_broker():
    if settings.use_upstash_for_events and settings.upstash_url:
        from app.upstash import get_upstash

        client = get_upstash()
        if client is not None and client.ping():
            logger.info(
                "Realtime progress using Upstash streams (polled every %ss, idling to %ss)",
                settings.upstash_poll_seconds,
                settings.upstash_idle_poll_seconds,
            )
            return UpstashBroker(client)
        logger.warning("Upstash configured but unreachable, falling back")

    if settings.redis_url:
        try:
            broker = RedisBroker(settings.redis_url)
            logger.info("Realtime progress using Redis at %s", settings.redis_url)
            return broker
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s), falling back to in-process progress events", exc
            )
    return InProcessBroker()


def reset_broker() -> None:
    global _broker
    with _broker_lock:
        _broker = None


def broker_name() -> str:
    return get_broker().name


def source_channel(source_id) -> str:
    return f"ingestion:{source_id}"


def course_channel(course_id) -> str:
    return f"course:{course_id}"


def ingestion_feed_channel() -> str:
    """Every job reports here as well, so the dock can show ingestion from any page
    without knowing which course is busy."""
    return "ingestion:feed"


def publish_progress(channel: str, payload: dict[str, Any]) -> None:
    enriched = {**payload, "at": time.time()}
    get_broker().publish(channel, enriched)


def subscribe(channel: str) -> Iterator[dict[str, Any]]:
    """Blocking iteration over a channel, for scripts and tests. An empty dict is a
    heartbeat rather than an event."""
    broker = get_broker()
    listener = broker.attach(channel)
    try:
        waited = 0.0
        while not shutting_down():
            try:
                yield listener.get(timeout=TICK_SECONDS)
                waited = 0.0
            except queue.Empty:
                waited += TICK_SECONDS
                if waited >= HEARTBEAT_SECONDS:
                    waited = 0.0
                    yield {}
    finally:
        broker.detach(channel, listener)


async def sse_stream(channel: str, request=None, include_latest: bool = True) -> AsyncIterator[str]:
    """Server-sent events for one channel. Ends when the browser goes away, when the
    work reports it is finished, or when the stream has been open long enough that the
    browser may as well reconnect."""
    broker = get_broker()
    listener = broker.attach(channel)
    started = time.monotonic()
    waited = 0.0

    try:
        yield f"retry: {int(settings.sse_retry_ms)}\n\n"

        if include_latest:
            snapshot = broker.latest(channel)
            if snapshot:
                yield f"data: {json.dumps(snapshot, default=str)}\n\n"

        while True:
            if shutting_down():
                return
            if request is not None and await request.is_disconnected():
                return
            if time.monotonic() - started > settings.sse_max_seconds:
                return

            try:
                payload = listener.get_nowait()
            except queue.Empty:
                await asyncio.sleep(TICK_SECONDS)
                waited += TICK_SECONDS
                if waited >= HEARTBEAT_SECONDS:
                    waited = 0.0
                    yield ": heartbeat\n\n"
                continue

            waited = 0.0
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            if payload.get("terminal"):
                return
    finally:
        broker.detach(channel, listener)
