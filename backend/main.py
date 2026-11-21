"""
Gativa Backend — FastAPI application entry point
"""
"""
Gativa Backend — FastAPI application entry point
"""
import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.core.sqlite_store import init_sqlite_db
from app.core.security import check_rate_limit, sanitize_exception_detail
from app.api import health, analyses, simulations, geocoding

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    init_sqlite_db()
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="Gativa API",
    description="Smart Traffic Analysis and Infrastructure Recommendation API",
    version="1.0.0",
    lifespan=lifespan,
)


class SecurityAndCorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware providing correlation IDs, request rate-limiting, and payload size bounds.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. Correlation ID
        cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = cid

        # 2. Rate limiting for non-health endpoints
        path = request.url.path
        if not path.startswith("/api/health") and not path in ("/", "/docs", "/openapi.json"):
            await check_rate_limit(request)

        # 3. Payload size bound check (5MB ceiling)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 5 * 1024 * 1024:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request payload exceeds 5MB size limit", "correlation_id": cid},
                headers={"X-Correlation-ID": cid},
            )

        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response


app.add_middleware(SecurityAndCorrelationMiddleware)

# CORS — Restrict methods and headers to actual application contracts; prevent wildcard with credentials
cors_origins = settings.cors_origins_list
if "*" in cors_origins:
    logger.warning("CORS wildcard origin detected. Disabling credentials to prevent credential exposure.")
    allow_credentials = False
else:
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=settings.cors_methods_list,
    allow_headers=settings.cors_headers_list,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler that logs privately and returns safe sanitized errors with correlation ID."""
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.exception("Unhandled server exception [Ref: %s] on %s %s: %s", cid, request.method, request.url.path, exc)
    sanitized_msg = sanitize_exception_detail(exc, correlation_id=cid)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": sanitized_msg, "correlation_id": cid},
        headers={"X-Correlation-ID": cid},
    )


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint welcoming the user and providing dashboard and API documentation links."""
    return {
        "service": "Gativa Smart Traffic Optimization API",
        "status": "online",
        "version": "1.0.0",
        "dashboard_url": "http://localhost:5173",
        "docs_url": "http://localhost:8000/docs",
        "health_check": "http://localhost:8000/api/health",
    }


# Routers
app.include_router(health.router, prefix="/api")
app.include_router(analyses.router, prefix="/api")
app.include_router(simulations.router, prefix="/api")
app.include_router(geocoding.router, prefix="/api")
