"""Per-user daily token budget tracked in Redis, with in-memory fallback."""

from __future__ import annotations

import datetime
import threading

from app.config import settings

# ---------------------------------------------------------------------------
# Redis client — optional (reuse the same check as the rate limiter)
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
# In-memory fallback
# ---------------------------------------------------------------------------

_mem_lock = threading.Lock()
_mem_budgets: dict[str, int] = {}  # key → tokens_used


def _mem_key(user_id: str) -> str:
    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    return f"token_budget:{user_id}:{today}"


class TokenBudget:
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens

    def _key(self, user_id: str) -> str:
        return _mem_key(user_id)

    def check_budget(self, user_id: str, estimated_tokens: int) -> tuple[bool, int]:
        client = get_redis_client()
        key = self._key(user_id)
        if client is None:
            with _mem_lock:
                used = _mem_budgets.get(key, 0)
            remaining = self.max_tokens - used
            return estimated_tokens <= remaining, remaining

        used_str = client.get(key)
        used = int(used_str) if used_str is not None else 0
        remaining = self.max_tokens - used
        ok = estimated_tokens <= remaining
        return ok, remaining

    def consume(self, user_id: str, actual_tokens: int) -> dict:
        client = get_redis_client()
        key = self._key(user_id)
        if client is None:
            with _mem_lock:
                current = _mem_budgets.get(key, 0) + actual_tokens
                _mem_budgets[key] = current
            remaining = max(0, self.max_tokens - current)
            return {
                "used": current,
                "limit": self.max_tokens,
                "remaining": remaining,
                "tokens_charged": actual_tokens,
            }

        used = client.incrby(key, actual_tokens)
        # Set TTL to seconds-until-midnight on first write
        ttl = client.ttl(key)
        if ttl == -1:
            now = datetime.datetime.now(datetime.UTC)
            midnight = (now + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            seconds_until_midnight = int((midnight - now).total_seconds())
            client.expire(key, seconds_until_midnight)

        remaining = max(0, self.max_tokens - used)
        return {
            "used": used,
            "limit": self.max_tokens,
            "remaining": remaining,
            "tokens_charged": actual_tokens,
        }


_budget = TokenBudget(max_tokens=settings.max_tokens_per_user_daily)


def check_budget(user_id: str, estimated_tokens: int) -> tuple[bool, int]:
    return _budget.check_budget(user_id, estimated_tokens)


def consume_budget(user_id: str, actual_tokens: int) -> dict:
    return _budget.consume(user_id, actual_tokens)
