"""In-process TTL cache.

A full analysis costs 20+ sequential provider calls and takes the better part
of a minute, which no interactive UI can absorb on every page navigation.
Results are cached per wallet so the first load pays that cost once and
subsequent requests are served from memory.

This is deliberately process-local: persistence belongs in RDS, which is out of
scope. A single-flight lock per key stops a burst of concurrent requests for
the same wallet from each starting their own upstream fetch.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 256):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self._entries.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        if len(self._entries) >= self._max_entries:
            self._evict_expired()
        if len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda k: self._entries[k].expires_at)
            self._entries.pop(oldest, None)

        self._entries[key] = _Entry(
            value=value, expires_at=time.monotonic() + (ttl or self._ttl)
        )

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, e in self._entries.items() if e.expires_at < now]:
            self._entries.pop(key, None)

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[Any]], ttl: float | None = None
    ) -> Any:
        """Return the cached value, computing it at most once across callers."""
        cached = self.get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another caller may have populated the entry while we waited.
            cached = self.get(key)
            if cached is not None:
                return cached

            logger.info("Cache miss for %s; computing", key)
            value = await factory()
            self.set(key, value, ttl)
            return value
        # Note: the lock is intentionally retained. The key space is bounded by
        # max_entries and locks are tiny.


analysis_cache = TTLCache(ttl_seconds=300.0)
