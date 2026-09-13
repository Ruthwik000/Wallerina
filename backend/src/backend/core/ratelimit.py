"""Per-client rate limiting for the expensive endpoints.

The routes below each cost real money or real CPU: model calls, Monte Carlo
runs and full wallet scans against Alchemy. A sliding one-minute window per
client address stops a single caller from running those bills up.

The window lives in process memory, so each API task enforces it separately and
N tasks allow up to N times the limit in total. A rate-based rule on the load
balancer (AWS WAF) is the place for a hard global limit.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable

LIMITED_ROUTES: list[tuple[str, re.Pattern[str]]] = [
    ("GET", re.compile(r"^/api/recommendation/[^/]+$")),
    ("GET", re.compile(r"^/api/analysis/[^/]+$")),
    ("GET", re.compile(r"^/api/history/[^/]+/(performance|risk)$")),
    ("POST", re.compile(r"^/api/chat$")),
    ("POST", re.compile(r"^/api/simulate(/scenarios)?$")),
    ("GET", re.compile(r"^/api/auth/nonce$")),
    ("POST", re.compile(r"^/api/auth/verify$")),
    ("POST", re.compile(r"^/api/execution/[^/]+/(plan|quote)$")),
]

# Idle clients are forgotten once this many are tracked.
PRUNE_ABOVE = 10_000


def is_limited(method: str, path: str) -> bool:
    return any(method == route_method and pattern.match(path) for route_method, pattern in LIMITED_ROUTES)


def client_key(request, trust_proxy_headers: bool) -> str:
    """The caller's address.

    Behind a load balancer every connection comes from the balancer and the
    caller is named in X-Forwarded-For. Only the rightmost entry can be
    trusted: the balancer appends it, while anything to its left was sent by
    the client and could be forged to dodge the limit.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int) -> float | None:
        """Record a request. None if allowed, otherwise seconds until one would be."""
        now = self.clock()

        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= PRUNE_ABOVE:
                self._prune(now)
            hits = self._hits[key] = deque()

        while hits and now - hits[0] >= self.window:
            hits.popleft()

        if len(hits) >= limit:
            return self.window - (now - hits[0])

        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()

    def _prune(self, now: float) -> None:
        idle = [key for key, hits in self._hits.items() if not hits or now - hits[-1] >= self.window]
        for key in idle:
            del self._hits[key]
