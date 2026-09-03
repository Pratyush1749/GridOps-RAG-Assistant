from __future__ import annotations

import os
from abc import ABC, abstractmethod

from app.config import settings
from app.models import ChatResponse, RetrievedChunk
from app.services.rag_service import run_rag_with_trace


class SkippedIntent(Exception):
    pass


class Invoker(ABC):
    @abstractmethod
    def invoke(
        self, question: str, flags: dict, intent: str
    ) -> tuple[ChatResponse, list[RetrievedChunk]]: ...


class ServiceInvoker(Invoker):
    """Calls the RAG service layer in-process.

    Fast and dependency-light (no running server needed), but it can only
    exercise the document-retrieval path: `sql` and `hybrid` goldens need the
    LangGraph HITL approval flow, which only exists behind the API. Use
    ApiInvoker (--mode api) to score those.
    """

    SUPPORTED_INTENTS = {"rag", "web_fallback"}

    def invoke(
        self, question: str, flags: dict, intent: str
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        if intent not in self.SUPPORTED_INTENTS:
            raise SkippedIntent(f"intent={intent} not supported in service mode")

        if intent == "web_fallback" and not settings.tavily_api_key:
            raise SkippedIntent("tavily_unset: TAVILY_API_KEY not configured")

        # run_rag_with_trace() calls _retrieve/_generate directly and never
        # consults the RAG answer cache, so eval always measures a cold path.
        return run_rag_with_trace(question, flags)


class ApiInvoker(Invoker):
    """Drives the real HTTP API, including the Text2SQL human-approval flow.

    This exercises everything ServiceInvoker cannot: the FastAPI security
    pipeline (rate limit, token budget, L1 regex guard), intent routing through
    LangGraph, and the `interrupt()` SQL approval gate — which it auto-approves
    so `sql` / `hybrid` goldens can be scored unattended.

    Requires a running server (`python scripts/serve.py`) and a seeded user.
    Credentials come from EVAL_API_USERNAME / EVAL_API_PASSWORD, defaulting to
    the demo admin created by scripts/seed_db.py.
    """

    SUPPORTED_INTENTS = {"rag", "web_fallback", "sql", "hybrid"}

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 180,
    ) -> None:
        self.base_url = (base_url or os.getenv("EVAL_API_URL", "http://localhost:8000")).rstrip("/")
        self.prefix = f"/api/{settings.api_version}"
        self.username = username or os.getenv("EVAL_API_USERNAME", "admin@demo.local")
        self.password = password or os.getenv("EVAL_API_PASSWORD", "admin123")
        self.timeout = timeout
        self._token: str | None = None

    # -- auth ---------------------------------------------------------------

    def _login(self) -> str:
        import requests

        url = f"{self.base_url}{self.prefix}/auth/login"
        try:
            resp = requests.post(
                url,
                json={"username": self.username, "password": self.password},
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - network/DNS/refused
            raise SkippedIntent(f"api_unreachable: {url} ({exc})") from exc

        if resp.status_code != 200:
            raise SkippedIntent(
                f"api_login_failed: {resp.status_code} for user {self.username!r} "
                f"(set EVAL_API_USERNAME / EVAL_API_PASSWORD, or run scripts/seed_db.py)"
            )
        return resp.json()["token"]

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self._token = self._login()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    # -- invocation ---------------------------------------------------------

    def invoke(
        self, question: str, flags: dict, intent: str
    ) -> tuple[ChatResponse, list[RetrievedChunk]]:
        import requests

        if intent == "web_fallback" and not settings.tavily_api_key:
            raise SkippedIntent("tavily_unset: TAVILY_API_KEY not configured")

        body: dict = {"question": question}
        for key in (
            "search_mode",
            "top_k",
            "enable_rerank",
            "enable_hyde",
            "enable_crag",
            "enable_self_reflective",
        ):
            if key in flags:
                body[key] = flags[key]

        resp = requests.post(
            f"{self.base_url}{self.prefix}/query",
            json=body,
            headers=self._headers(),
            timeout=self.timeout,
        )

        # The L1 Pydantic guard rejects injection probes before the pipeline
        # runs. That is the correct behaviour for a security golden, so surface
        # it as a real (scoreable) refusal rather than an error.
        if resp.status_code == 422:
            blocked = ChatResponse(
                answer="Request blocked by input validation (HTTP 422).",
                sources=[],
                confidence=0.0,
            )
            blocked.metadata.route = "blocked"
            return blocked, []

        if resp.status_code != 200:
            raise RuntimeError(f"api_error {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()

        # Text2SQL pauses on interrupt() for human approval. Auto-approve so
        # sql/hybrid goldens can be scored without a human in the loop.
        pending = payload.get("pending_sql")
        if pending:
            approve = requests.post(
                f"{self.base_url}{self.prefix}/query/sql/execute",
                json={"query_id": pending["query_id"], "approved": True},
                headers=self._headers(),
                timeout=self.timeout,
            )
            if approve.status_code != 200:
                raise RuntimeError(
                    f"sql_approve_failed {approve.status_code}: {approve.text[:300]}"
                )
            payload = approve.json()

        response = ChatResponse(**payload)
        chunks = [
            RetrievedChunk(text=c.text, source=c.source, score=c.score)
            for c in response.metadata.retrieved_chunks
        ]
        return response, chunks
