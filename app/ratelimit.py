"""Small in-memory sliding-window limiter for login and OTP attempts.

It is per process. With more than one replica the effective limit is multiplied by the replica count;
move the counters to Redis (see 12_STORAGE_MATRIX) before relying on it as a hard control.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.errors import ApiError

_hits: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "rate_limited")
    q.append(now)


def reset() -> None:
    _hits.clear()
