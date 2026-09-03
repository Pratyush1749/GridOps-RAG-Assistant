"""
Enterprise RAG — Query endpoints.

Routes (mounted at /api/v1):
  POST /query                  — ask a RAG / SQL / hybrid question
  POST /query/sql/execute      — approve or reject a pending SQL query
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from langgraph.types import Command
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.core.graph import graph
from app.exceptions import (
    BudgetExceededError,
    ContentBlockedError,
    InjectionBlockedError,
    RateLimitError,
)
from app.middleware.auth import User, get_current_user
from app.middleware.rate_limiter import is_allowed_user
from app.models import (
    ChatResponse,
    PendingSQLBlock,
    QueryRequest,
    ResponseMetadata,
    RetrievedChunkPreview,
)
from app.security.content_moderation import moderate_and_redact
from app.security.input_guard import check_input_safe
from app.security.input_restructuring import count_tokens, restructure_input
from app.security.token_budget import check_budget, consume_budget

router = APIRouter(prefix="/query", tags=["Query"])


def _estimate_tokens(question: str) -> int:
    return count_tokens(question) + settings.reserved_output_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_security_checks(question: str, username: str) -> str:
    """
    Run all input-side security layers and return the sanitised question.

    Raises domain exceptions (caught by global handlers) on any violation.
    """
    # Layer 1 — per-user sliding-window rate limit
    allowed, _, _ = is_allowed_user(
        username,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitError()

    # Layer 2 — per-user daily token budget
    estimated = _estimate_tokens(question)
    ok, remaining = check_budget(username, estimated)
    if not ok:
        raise BudgetExceededError(remaining=remaining, estimated=estimated)

    # Layer 3 — input restructuring (truncate / summarise if too long)
    restructured, _ = restructure_input(question)

    # Layer 4 — LLM-Guard prompt injection / toxicity scan
    guard_allowed, guard_reason = check_input_safe(restructured)
    if not guard_allowed:
        raise InjectionBlockedError(detail=f"Input rejected: {guard_reason}")

    # Layer 5 — content moderation + PII redaction
    mod_allowed, moderated, mod_reason = moderate_and_redact(restructured)
    if not mod_allowed:
        raise ContentBlockedError(detail=f"Content blocked: {mod_reason}")

    return moderated


def _build_response(result: dict[str, Any]) -> ChatResponse:
    """Map a graph result dict into a validated ChatResponse.

    Only fields declared in GraphState (app/core/state.py) survive LangGraph's
    state merge - any key a node returns that isn't in that TypedDict (e.g. a
    raw "metadata" / "cache_hit" dict, which is what earlier code here read)
    is silently dropped, not merged and not raised. That meant every response
    through this endpoint always carried the ResponseMetadata *default*
    (route="rag", empty retrieved_chunks) regardless of actual intent - only
    caught by driving the real HTTP API (eval --mode api) rather than the
    service layer directly. Metadata is reconstructed here from the
    individual fields GraphState does declare.
    """
    intent = result.get("intent") or "rag"
    cache_hit = bool(result.get("rag_cache_hit") or result.get("sql_cache_hit") or False)
    chunk_previews = [
        RetrievedChunkPreview(**c) if isinstance(c, dict) else c
        for c in (result.get("chunk_previews") or [])
    ]
    metadata = ResponseMetadata(
        route=intent,
        retrieved_chunks=chunk_previews,
        cache_hit=cache_hit,
        reflection_iterations=result.get("reflection_iterations") or 0,
        refined_question=result.get("refined_question"),
    )
    return ChatResponse(
        answer=result.get("final_answer", ""),
        sources=result.get("sources", []),
        confidence=result.get("confidence", 0.0) or 0.0,
        cache_hit=cache_hit,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ChatResponse,
    summary="Submit a question to the RAG / SQL pipeline",
)
async def query(
    body: QueryRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Run the full Enterprise RAG pipeline:

    1. Security checks (rate limit → token budget → restructure → LLM-Guard → moderation)
    2. Intent routing (rag / sql / hybrid)
    3. Retrieval + generation
    4. Output moderation + PII redaction
    5. Token budget consumption

    Returns a `ChatResponse`. If a SQL query requires human approval the
    `pending_sql` field will be populated instead of `answer`.
    """
    logger.info("Received query from user {}: {}", user.username, body.question)
    sanitised = await run_in_threadpool(_run_security_checks, body.question, user.username)

    flags = {
        "top_k": body.top_k,
        "search_mode": body.search_mode,
        "enable_rerank": body.enable_rerank,
        "enable_hyde": body.enable_hyde,
        "enable_crag": body.enable_crag,
        "enable_self_reflective": body.enable_self_reflective,
    }
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await run_in_threadpool(
            graph.invoke,
            {"question": sanitised, "user_id": user.username, "flags": flags},
            config,
        )
    except Exception as exc:  # noqa: BLE001 - never 500 the chat; return a readable message
        logger.exception("Pipeline failed for user {}", user.username)
        return ChatResponse(
            answer=f"The pipeline hit an error while answering: {exc}",
            sources=[],
            confidence=0.0,
        )

    # SQL approval required — surface the pending block
    if "__interrupt__" in result:
        intr = result["__interrupt__"][0].value
        return ChatResponse(
            answer="",
            sources=[],
            confidence=0.0,
            pending_sql=PendingSQLBlock(
                sql=intr.get("sql", ""),
                query_id=thread_id,
                explanation=intr.get("explanation", ""),
            ),
        )

    response = _build_response(result)

    # Output moderation — redact PII before returning to client
    out_ok, redacted, _ = moderate_and_redact(response.answer)
    if not out_ok:
        raise HTTPException(status_code=500, detail="Output blocked by moderation policy")
    response.answer = redacted

    # Consume token budget only after a successful call
    estimated = _estimate_tokens(body.question)
    consume_budget(user.username, estimated)

    return response


class SqlExecuteRequest(BaseModel):
    """Minimal model for resuming a SQL approval thread."""

    query_id: str
    approved: bool


@router.post(
    "/sql/execute",
    response_model=ChatResponse,
    summary="Approve or reject a pending SQL query",
)
async def execute_sql(
    body: SqlExecuteRequest,
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Resume a paused graph thread after the user has reviewed the generated SQL.
    Set `approved: true` to execute, `approved: false` to cancel.
    """
    config = {"configurable": {"thread_id": body.query_id}}
    result = await run_in_threadpool(
        graph.invoke,
        Command(resume={"approved": body.approved}),
        config,
    )
    return _build_response(result)
