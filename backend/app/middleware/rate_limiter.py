"""
Rate limiting middleware.

Uses Upstash Redis (sliding-window) when credentials are configured, and falls
back to a thread-safe in-memory store for local / dev environments where
UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN are placeholder values.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import settings

# ---------------------------------------------------------------------------
# Redis client — optional
# ---------------------------------------------------------------------------

_redis_client = None
_redis_checked = False


def _is_redis_configured() -> bool:
    url = settings.upstash_redis_url or ""
    token = settings.upstash_redis_token or ""
    return (
        url.startswith("https://")
        and "upstash.io" in url
        and token not in ("", "your-upstash-redis-token")
    )


def get_redis_client():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    if _is_redis_configured():
        try:
            from upstash_redis import Redis  # noqa: PLC0415

            _redis_client = Redis(
                url=settings.upstash_redis_url,
                token=settings.upstash_redis_token,
            )
        except Exception:
            _redis_client = None
    return _redis_client


# ---------------------------------------------------------------------------
# In-memory fallback (single-process, thread-safe sliding window)
# ---------------------------------------------------------------------------

_mem_lock = threading.Lock()
_mem_store: dict[str, deque] = defaultdict(deque)


def _mem_is_allowed(key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    now = time.time()
    cutoff = now - window_seconds
    with _mem_lock:
        q = _mem_store[key]
        # Evict expired timestamps
        while q and q[0] < cutoff:
            q.popleft()
        count = len(q) + 1  # +1 for current request
        if count <= limit:
            q.append(now)
        allowed = count <= limit
        remaining = max(0, limit - count)
    return allowed, remaining, count


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        client = get_redis_client()
        if client is None:
            # Fallback: in-memory sliding window
            return _mem_is_allowed(key, self.max_requests, self.window_seconds)

        # Upstash Redis sliding window
        now = time.time()
        window_start = now - self.window_seconds

        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, self.window_seconds)
        results = pipe.exec()

        request_count: int = results[2]  # type: ignore[assignment]
        remaining = max(0, self.max_requests - request_count)
        allowed = request_count <= self.max_requests
        return allowed, remaining, request_count


def is_allowed_ip(ip: str, route: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:ip:{ip}:{route}"
    return limiter.is_allowed(key)


def is_allowed_user(
    user_id: str, limit: int = 20, window_seconds: int = 60
) -> tuple[bool, int, int]:
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:user:{user_id}"
    return limiter.is_allowed(key)
