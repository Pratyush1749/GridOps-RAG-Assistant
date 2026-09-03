"""
Enterprise RAG — Admin endpoints.

Routes (mounted at /api/v1):
  GET  /admin/health         — public health-check (no auth required)
  GET  /admin/cache/stats    — cache hit/miss stats (admin only)
  POST /admin/cache/clear    — flush all caches (admin only)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from app.config import settings
from app.middleware.auth import User, require_admin
from app.services.query_cache_service import query_cache

router = APIRouter(prefix="/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# Health-check probes (run concurrently)
# ---------------------------------------------------------------------------


async def _ping_postgres() -> tuple[str, str]:
    try:
        import psycopg2

        conn = psycopg2.connect(settings.database_url, connect_timeout=2)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return "ok", ""
    except Exception as exc:
        logger.trace("Postgres health check failed: {}", exc)
        return "error", str(exc)


async def _ping_qdrant() -> tuple[str, str]:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, timeout=2)
        client.get_collections()
        return "ok", ""
    except Exception as exc:
        logger.trace("Qdrant health check failed: {}", exc)
        return "error", str(exc)


async def _ping_redis() -> tuple[str, str]:
    if not settings.upstash_redis_url or "your-redis" in settings.upstash_redis_url:
        return "ok", "Not configured"
    try:
        from upstash_redis import Redis

        redis = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
        redis.ping()
        return "ok", ""
    except Exception as exc:
        logger.trace("Redis health check failed: {}", exc)
        return "error", str(exc)


async def _ping_openai() -> tuple[str, str]:
    if (not settings.openai_api_key or "your-openai" in settings.openai_api_key) and not getattr(
        settings, "groq_api_key", ""
    ):
        return "ok", "Not configured"
    try:
        from openai import AsyncOpenAI

        if settings.openai_api_key and "your-openai" not in settings.openai_api_key:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            client = AsyncOpenAI(
                api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1"
            )
        await client.models.list()
        return "ok", "Using Groq" if "groq.com" in str(client.base_url) else ""
    except Exception as exc:
        logger.trace("OpenAI health check failed: {}", exc)
        return "error", str(exc)


async def _ping_tavily() -> tuple[str, str]:
    if not settings.tavily_api_key or "your-tavily" in settings.tavily_api_key:
        return "ok", "Not configured"
    try:
        from app.services.web_search import search_web

        search_web("health check")
        return "ok", ""
    except Exception as exc:
        logger.trace("Tavily health check failed: {}", exc)
        return "error", str(exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="System health check",
    description="Probes all downstream services. No authentication required.",
)
async def health_check() -> dict[str, Any]:
    """Check connectivity to Postgres, Qdrant, Redis, OpenAI and Tavily."""
    results = await asyncio.gather(
        _ping_postgres(),
        _ping_qdrant(),
        _ping_redis(),
        _ping_openai(),
        _ping_tavily(),
        return_exceptions=True,
    )

    def _parse(r: Any) -> dict:
        if isinstance(r, Exception):
            return {"status": "error", "message": str(r)}
        return {"status": r[0], "message": r[1]}

    postgres_st = _parse(results[0])
    qdrant_st = _parse(results[1])
    redis_st = _parse(results[2])
    openai_st = _parse(results[3])
    tavily_st = _parse(results[4])

    statuses = [
        postgres_st["status"],
        qdrant_st["status"],
        redis_st["status"],
        openai_st["status"],
        tavily_st["status"],
    ]
    all_ok = all(s == "ok" for s in statuses)

    return {
        "status": "ok" if all_ok else "degraded",
        "postgres": postgres_st,
        "qdrant": qdrant_st,
        "redis": redis_st,
        "openai": openai_st,
        "tavily": tavily_st,
    }


@router.get(
    "/cache/stats",
    summary="Cache hit/miss statistics",
    description="Returns per-cache tier stats. Requires admin role.",
)
async def cache_stats(user: User = Depends(require_admin)) -> dict:
    raw = query_cache.stats()

    def _tier(name: str) -> dict:
        t = raw.get(name, {})
        return {
            "hits": int(t.get("hits", 0)),
            "misses": int(t.get("misses", 0)),
            "sets": int(t.get("sets", 0)),
            "hit_rate": float(t.get("hit_rate", 0.0)),
        }

    return {
        "embedding": _tier("embedding"),
        "rag": _tier("rag_answer"),
        "sql_gen": _tier("sql_gen"),
        "sql_result": _tier("sql_result"),
        "intent_router": _tier("intent"),
    }


@router.post(
    "/cache/clear",
    summary="Clear all caches",
    description="Flushes Redis and in-memory caches. Requires admin role.",
)
async def cache_clear(user: User = Depends(require_admin)) -> dict:
    cleared = query_cache.clear()
    return {"status": "ok", "cleared": cleared}


@router.get(
    "/eval-files",
    summary="List evaluation files",
    description="Returns a list of JSON files in the eval/results directory.",
)
async def list_eval_files() -> dict:
    from pathlib import Path

    results_dir = Path(__file__).parent.parent.parent / "eval" / "results"
    if not results_dir.exists():
        return {"files": []}

    files = [p.name for p in results_dir.glob("*.json") if p.is_file()]
    # Sort newest first by mtime
    files.sort(key=lambda f: (results_dir / f).stat().st_mtime, reverse=True)
    return {"files": files}


@router.get(
    "/eval-file",
    summary="Get evaluation file",
    description="Returns the contents of a specific evaluation JSON file.",
)
async def get_eval_file(name: str) -> dict:
    import json
    from pathlib import Path

    from fastapi import HTTPException

    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = Path(__file__).parent.parent.parent / "eval" / "results" / name
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
