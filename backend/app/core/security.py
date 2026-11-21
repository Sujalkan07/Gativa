"""
Security, authentication, rate limiting, and exception sanitization for Gativa.
Enforces private/single-tenant reverse proxy and API-key security boundaries.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import defaultdict
from typing import Optional
from fastapi import Request, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

from app.core.config import get_settings

logger = logging.getLogger(__name__)

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

# In-memory sliding window rate limiter: client_id -> list of timestamps
_rate_limit_lock = asyncio.Lock()
_client_request_history: dict[str, list[float]] = defaultdict(list)

# Global concurrency semaphores initialized lazily to respect asyncio loop
_analysis_semaphore: Optional[asyncio.Semaphore] = None
_simulation_semaphore: Optional[asyncio.Semaphore] = None


def get_analysis_semaphore() -> asyncio.Semaphore:
    global _analysis_semaphore
    if _analysis_semaphore is None:
        settings = get_settings()
        _analysis_semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)
    return _analysis_semaphore


def get_simulation_semaphore() -> asyncio.Semaphore:
    global _simulation_semaphore
    if _simulation_semaphore is None:
        settings = get_settings()
        _simulation_semaphore = asyncio.Semaphore(settings.max_concurrent_simulations)
    return _simulation_semaphore


async def get_current_user(request: Request) -> str:
    """
    Authenticate callers against the intended single-instance private deployment model.

    In development (default):
        Allows seamless local loopback development as 'dev-user' unless require_auth_in_dev is set.

    In production:
        Requires one of:
        1. Trusted reverse proxy with verified proxy secret header (rejects spoofed forwarded headers).
        2. Direct API Key authentication via X-API-Key or Authorization Bearer header.
        Fails safely (closed) if production security is misconfigured.
    """
    settings = get_settings()
    is_dev = settings.environment.lower() == "development"

    # Development bypass if enabled
    if is_dev and not settings.require_auth_in_dev:
        return request.headers.get("x-forwarded-user", "dev-user")

    # Production safety check: Ensure credentials are configured
    has_proxy_secret = bool(settings.proxy_secret and settings.proxy_secret.strip())
    has_api_key = bool(settings.api_key and settings.api_key.strip())

    if not has_proxy_secret and not has_api_key:
        logger.error("Production authentication failed closed: Neither API_KEY nor PROXY_SECRET is configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Production authentication boundary is unconfigured.",
        )

    # 1. Reverse-Proxy Boundary check
    if has_proxy_secret:
        proxy_secret_val = request.headers.get(settings.trusted_proxy_secret_header.lower())
        if proxy_secret_val and proxy_secret_val == settings.proxy_secret:
            # Verified proxy: trust identity header
            identity = request.headers.get(settings.trusted_proxy_header.lower())
            if identity and identity.strip():
                return identity.strip()
            return "proxy-authenticated-user"
        elif request.headers.get(settings.trusted_proxy_header.lower()):
            # Untrusted caller attempted to supply x-forwarded-user without valid proxy secret!
            logger.warning(
                "Security alert: Client %s attempted to spoof %s header without valid proxy secret.",
                request.client.host if request.client else "unknown",
                settings.trusted_proxy_header,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid reverse-proxy security credentials.",
            )

    # 2. Direct API Key check (X-API-Key or Authorization: Bearer <key>)
    if has_api_key:
        client_api_key = request.headers.get("x-api-key")
        if not client_api_key:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                client_api_key = auth_header[7:].strip()

        if client_api_key and client_api_key == settings.api_key:
            return "api-key-user"

    # Unauthorized
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials required. Supply a valid API key or access through authenticated proxy.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def check_rate_limit(request: Request) -> None:
    """
    Sliding window in-memory rate limiter per client IP / forwarded user.
    """
    settings = get_settings()
    client_id = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else "unknown")
    )
    now = time.time()
    window_seconds = 60.0
    limit = settings.rate_limit_per_minute

    async with _rate_limit_lock:
        history = _client_request_history[client_id]
        # Prune timestamps outside window
        _client_request_history[client_id] = [t for t in history if now - t < window_seconds]
        if len(_client_request_history[client_id]) >= limit:
            logger.warning("Rate limit exceeded for client %s (%d requests in 60s)", client_id, limit)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Request rate limit exceeded. Please wait before retrying.",
                headers={"Retry-After": "60"},
            )
        _client_request_history[client_id].append(now)


def sanitize_exception_detail(exc: Exception, correlation_id: Optional[str] = None) -> str:
    """
    Sanitize internal exception details to prevent leaking file paths, keys, or stack traces.
    """
    cid_str = f" [Ref: {correlation_id}]" if correlation_id else ""
    raw = str(exc)

    # Check for known safe validation errors
    if isinstance(exc, (ValueError, KeyError)) and not any(k in raw.lower() for k in ["path", "file", "key=", "uri", "password", "token"]):
        return f"{raw}{cid_str}"

    # Redact common sensitive patterns
    sanitized = raw
    # Redact Windows / POSIX file paths
    sanitized = re.sub(r"[a-zA-Z]:\\[^\s'\"]+", "[redacted-path]", sanitized)
    sanitized = re.sub(r"/(?:Users|home|root|var|tmp|etc)/[^\s'\"]+", "[redacted-path]", sanitized)
    # Redact query params / keys
    sanitized = re.sub(r"(key|token|password|secret)=[^\s&'\"]+", r"\1=[redacted]", sanitized, flags=re.IGNORECASE)
    # Redact MongoDB / Database URIs
    sanitized = re.sub(r"mongodb(?:\+srv)?://[^\s'\"]+", "mongodb://[redacted-credentials]", sanitized)

    # If the exception is severe or internal, return a safe message
    if any(term in sanitized.lower() for term in ["traceback", "syntaxerror", "operationalerror", "driver", "socket"]):
        return f"An internal server error occurred while processing the request.{cid_str}"

    return f"{sanitized}{cid_str}"
