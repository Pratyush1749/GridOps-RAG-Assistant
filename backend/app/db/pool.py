"""
Enterprise RAG — DB layer (intentionally inert).

This module used to expose a psycopg3 async connection pool, but nothing in the
codebase depends on it: every DB access is synchronous — `psycopg2` in the route
handlers / `SQLService` / migrations, and sync `psycopg` in the LangGraph
checkpointer. On Windows the async pool's background worker also cannot run on the
default `ProactorEventLoop` and spams reconnect errors, so the pool is disabled.

`init_pool()` / `close_pool()` remain as no-ops so the lifespan call sites are
unchanged. `get_db_conn()` raises if anything ever tries to use the removed pool.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from loguru import logger

_DISABLED_MSG = "Async DB pool is disabled; use a synchronous psycopg2 connection instead."


async def init_pool() -> None:
    """No-op. The async pool is not used anywhere in this project."""
    logger.info("Async DB pool disabled (unused; sync psycopg2/psycopg is used everywhere)")


async def close_pool() -> None:
    """No-op — kept so the shutdown call site stays valid."""
    return None


@asynccontextmanager
async def _acquire() -> AsyncGenerator[None, None]:
    raise RuntimeError(_DISABLED_MSG)
    yield  # pragma: no cover - unreachable, keeps this an async generator


async def get_db_conn() -> AsyncGenerator[None, None]:
    """Kept for import compatibility; fails loudly if wired to a route."""
    raise RuntimeError(_DISABLED_MSG)
    yield  # pragma: no cover
