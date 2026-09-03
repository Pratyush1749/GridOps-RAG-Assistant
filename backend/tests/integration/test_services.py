"""
Integration test — can the backend actually reach its dependencies?

    PostgreSQL  ->  SELECT 1
    Qdrant      ->  get_collections()
    Backend     ->  GET /api/v1/admin/health   (the app talking to both)

Requires the infra containers to be up:

    docker compose up -d postgres qdrant

Each check SKIPs (rather than fails) with a readable reason when its service is
unreachable, so a partial environment still produces a useful report.
Connection targets come from ``app.config.settings`` (i.e. from ``.env``).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_postgres_accepts_select_1() -> None:
    """A real connection to PostgreSQL can run `SELECT 1`."""
    import psycopg2

    from app.config import settings

    try:
        conn = psycopg2.connect(settings.database_url, connect_timeout=3)
    except Exception as exc:  # noqa: BLE001 - any driver/network error => skip
        pytest.skip(f"PostgreSQL not reachable at {settings.database_url!r}: {exc}")

    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.close()


def test_qdrant_lists_collections() -> None:
    """Qdrant answers a `get_collections()` call."""
    from qdrant_client import QdrantClient

    from app.config import settings

    try:
        client = QdrantClient(url=settings.qdrant_url, timeout=3)
        result = client.get_collections()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url!r}: {exc}")

    assert hasattr(result, "collections")


def test_backend_admin_health_reports_dependencies() -> None:
    """`/api/v1/admin/health` returns 200 and a per-dependency status map.

    The handler probes Postgres/Qdrant/Redis/OpenAI/Tavily itself and always
    returns 200 (overall "ok" or "degraded"), so this asserts the shape and
    records the live snapshot rather than requiring every dependency to be green.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)  # no `with` => rely on the endpoint's own probes
    resp = client.get("/api/v1/admin/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in {"ok", "degraded"}
    for dependency in ("postgres", "qdrant", "redis", "openai", "tavily"):
        assert dependency in body, f"missing '{dependency}' in health payload"
