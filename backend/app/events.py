"""Event bus for pushing live updates (new signals, new articles) to dashboard clients.

* RedisBus: worker and API are separate processes/containers (production).
* InMemoryBus: single process (embedded worker, tests).
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Protocol

from app.config import get_settings

log = logging.getLogger(__name__)
CHANNEL = "newsalpha:events"


class EventBus(Protocol):
    def publish(self, event: str, data: dict) -> None: ...

    def subscribe(self) -> AsyncIterator[dict]: ...


class InMemoryBus:
    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def publish(self, event: str, data: dict) -> None:
        msg = {"event": event, "data": data}
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            # publish() is called from scheduler threads; hand off to each subscriber's loop
            loop.call_soon_threadsafe(q.put_nowait, msg)

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        entry = (asyncio.get_running_loop(), q)
        with self._lock:
            self._subs.add(entry)
        try:
            while True:
                yield await q.get()
        finally:
            with self._lock:
                self._subs.discard(entry)


class RedisBus:
    def __init__(self, url: str) -> None:
        import redis

        self.url = url
        self._sync = redis.Redis.from_url(url)

    def publish(self, event: str, data: dict) -> None:
        try:
            self._sync.publish(CHANNEL, json.dumps({"event": event, "data": data}, default=str))
        except Exception as exc:  # never let a dashboard push break the pipeline
            log.warning("redis publish failed: %s", exc)

    async def subscribe(self) -> AsyncIterator[dict]:
        import redis.asyncio as aioredis

        client = aioredis.Redis.from_url(self.url)
        pubsub = client.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await client.aclose()


@lru_cache
def get_bus() -> EventBus:
    url = get_settings().redis_url
    return RedisBus(url) if url else InMemoryBus()
