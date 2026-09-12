"""
Unit smoke test — the cheapest possible "does the app work at all?" check.

Chain being verified:

    Can the application import?
            v
    Can FastAPI construct the app object?
            v
    Does GET /healthz return 200 {"status": "ok"}?

No database, no Docker, no network, no API keys.

Note: ``TestClient(app)`` is used WITHOUT the ``with`` context-manager form on
purpose — that keeps FastAPI's ``lifespan`` (DB pool init + migrations + LangGraph
build) from running, so this test stays offline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_application_imports() -> None:
    """The whole backend package tree imports without side effects."""
    import app.main  # noqa: F401  (import is the assertion)
    from app.config import settings

    assert settings.api_version == "v1"
    assert settings.app_title  # non-empty


def test_fastapi_app_object_is_built() -> None:
    """`create_app()` produced a usable FastAPI instance with routes mounted."""
    from app.main import app

    route_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/healthz" in route_paths


def test_healthz_returns_ok() -> None:
    """GET /healthz -> 200 -> {"status": "ok"}  (liveness probe)."""
    from app.main import app

    client = TestClient(app)  # no `with` => lifespan/DB not triggered
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
