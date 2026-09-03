"""
Enterprise RAG — Authentication endpoints.

Routes (mounted at /api/v1):
  POST /auth/register   — create a new user account
  POST /auth/login      — obtain a JWT access token
"""

from __future__ import annotations

import psycopg2
from fastapi import APIRouter, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.middleware.auth import create_access_token, hash_password, verify_password
from app.middleware.rate_limiter import is_allowed_ip

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, description="Unique username")
    password: str = Field(..., min_length=8, max_length=128, description="Account password")

    @field_validator("username")
    @classmethod
    def username_no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Username must not contain spaces")
        return v.lower().strip()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalise_username(cls, v: str) -> str:
        return v.lower().strip()


class TokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    username: str
    is_admin: bool = False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_db_conn():
    return psycopg2.connect(settings.database_url)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(request: Request, body: RegisterRequest) -> TokenResponse:
    """Create a new user and return a JWT access token."""
    client_ip = request.client.host if request.client else "unknown"
    allowed, _, _ = is_allowed_ip(
        client_ip,
        "/auth/register",
        limit=settings.auth_register_rate_limit_per_hour,
        window_seconds=3600,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    password_hash = hash_password(body.password)
    conn = _get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (body.username, password_hash),
        )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        ) from None
    finally:
        cur.close()
        conn.close()

    token = create_access_token(body.username)
    logger.info("New user registered: {} from IP {}", body.username, client_ip)
    return TokenResponse(token=token, username=body.username)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and obtain a JWT token",
)
async def login(request: Request, body: LoginRequest) -> TokenResponse:
    """Authenticate a user and return a JWT access token."""
    client_ip = request.client.host if request.client else "unknown"
    allowed, _, _ = is_allowed_ip(
        client_ip,
        "/auth/login",
        limit=settings.auth_login_rate_limit_per_min,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT password_hash, is_admin FROM users WHERE username = %s",
        (body.username,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None or not verify_password(body.password, row[0]):
        logger.warning("Failed login attempt for username: {} from IP {}", body.username, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    is_admin: bool = bool(row[1])
    token = create_access_token(body.username, is_admin=is_admin)
    logger.info("User {} logged in successfully from IP {}", body.username, client_ip)
    return TokenResponse(token=token, username=body.username, is_admin=is_admin)
