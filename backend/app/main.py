"""
Enterprise RAG — FastAPI application entry point.

All routes are versioned under /api/v1/.
CORS, structured exception handling, and startup/shutdown lifecycle hooks
are registered here so the application is production-ready.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Silence SyntaxWarnings raised while importing third-party/app modules below.
warnings.filterwarnings("ignore", category=SyntaxWarning)

from app.api import admin, auth, documents, query  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.pool import close_pool, init_pool  # noqa: E402
from app.exceptions import register_exception_handlers  # noqa: E402

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared resources on startup, release them on shutdown."""
    logger.info("Starting Enterprise RAG API — version {}", settings.api_version)

    # DB layer (synchronous psycopg2/psycopg everywhere; async pool is inert)
    try:
        await init_pool()
    except Exception as exc:
        logger.warning("DB layer init warning ({}). Continuing.", exc)

    # Auto-run SQL migrations so the schema is always up-to-date
    try:
        import os

        import psycopg2  # noqa: PLC0415

        migrations_dir = os.path.join(os.path.dirname(__file__), "..", "seed", "migrations")
        if os.path.isdir(migrations_dir):
            conn = psycopg2.connect(settings.database_url)
            cur = conn.cursor()
            for filename in sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql")):
                path = os.path.join(migrations_dir, filename)
                with open(path) as fh:
                    cur.execute(fh.read())
            conn.commit()
            cur.close()
            conn.close()
            logger.info("Database migrations applied")
    except Exception as exc:
        logger.warning("Could not run migrations at startup ({}). Continuing.", exc)

    # Warm up the LangGraph (connects to Postgres for the checkpointer).
    # This runs *after* the pool is ready so we get a clean connection.
    try:
        from app.core.graph import get_graph  # noqa: PLC0415

        get_graph()
        logger.info("LangGraph compiled and checkpointer ready")
    except Exception as exc:
        logger.warning(
            "Could not build LangGraph at startup ({}). Will retry on first request.", exc
        )

    yield  # ← application runs here

    logger.info("Shutting down Enterprise RAG API…")
    await close_pool()
    logger.info("PostgreSQL connection pool closed")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        description=settings.app_description,
        version=f"0.1.0-{settings.api_version}",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        contact={
            "name": "Enterprise RAG Team",
        },
        license_info={
            "name": "MIT",
        },
    )

    # ------------------------------------------------------------------
    # CORS — allow the React dev server and any configured origins
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Cache-Hit"],
    )

    # ------------------------------------------------------------------
    # Global exception handlers
    # ------------------------------------------------------------------
    register_exception_handlers(app)

    # ------------------------------------------------------------------
    # Versioned API routers
    # ------------------------------------------------------------------
    v1_prefix = f"/api/{settings.api_version}"

    app.include_router(auth.router, prefix=v1_prefix)
    app.include_router(query.router, prefix=v1_prefix)
    app.include_router(admin.router, prefix=v1_prefix)
    app.include_router(documents.router, prefix=v1_prefix)

    # ------------------------------------------------------------------
    # Root health-check (no auth required, used by load-balancers)
    # ------------------------------------------------------------------
    @app.get("/healthz", tags=["system"], include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
