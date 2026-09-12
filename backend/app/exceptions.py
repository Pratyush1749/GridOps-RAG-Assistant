"""
Enterprise RAG — Custom exceptions and global FastAPI exception handlers.
All error responses are returned as structured JSON: {"detail": "...", "code": "..."}.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when a per-user or per-IP rate limit is exceeded."""

    def __init__(self, detail: str = "Rate limit exceeded") -> None:
        self.detail = detail
        super().__init__(detail)


class ContentBlockedError(Exception):
    """Raised when content moderation blocks input or output."""

    def __init__(self, detail: str = "Content blocked by moderation policy") -> None:
        self.detail = detail
        super().__init__(detail)


class InjectionBlockedError(Exception):
    """Raised when the LLM-Guard input scanner detects a prompt injection."""

    def __init__(self, detail: str = "Prompt injection detected") -> None:
        self.detail = detail
        super().__init__(detail)


class BudgetExceededError(Exception):
    """Raised when a user's daily token budget is exhausted."""

    def __init__(self, remaining: int, estimated: int) -> None:
        self.remaining = remaining
        self.estimated = estimated
        self.detail = (
            f"Daily token budget exceeded — {remaining} tokens remaining, "
            f"this request needs ~{estimated} tokens."
        )
        super().__init__(self.detail)


class DocumentNotFoundError(Exception):
    """Raised when a requested document ID does not exist."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.detail = f"Document '{doc_id}' not found."
        super().__init__(self.detail)


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI application."""

    @app.exception_handler(RateLimitError)
    async def _rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": exc.detail, "code": "RATE_LIMIT_EXCEEDED"},
        )

    @app.exception_handler(ContentBlockedError)
    async def _content_blocked_handler(request: Request, exc: ContentBlockedError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.detail, "code": "CONTENT_BLOCKED"},
        )

    @app.exception_handler(InjectionBlockedError)
    async def _injection_blocked_handler(
        request: Request, exc: InjectionBlockedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": exc.detail, "code": "INJECTION_BLOCKED"},
        )

    @app.exception_handler(BudgetExceededError)
    async def _budget_exceeded_handler(request: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": exc.detail,
                "code": "BUDGET_EXCEEDED",
                "remaining_tokens": exc.remaining,
                "estimated_tokens": exc.estimated,
            },
        )

    @app.exception_handler(DocumentNotFoundError)
    async def _doc_not_found_handler(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.detail, "code": "DOCUMENT_NOT_FOUND"},
        )
