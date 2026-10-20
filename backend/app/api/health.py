"""Health check and API status endpoint."""
from fastapi import APIRouter
from app.core.config import get_settings
from app.core.sqlite_store import get_sqlite_status

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Health check endpoint confirming API status, persistent storage, and configured providers."""
    settings = get_settings()
    key_status = {
        "google_maps": bool(settings.google_maps_api_key),
        "tomtom": bool(settings.tomtom_api_key),
        "openweather": bool(settings.openweather_api_key),
    }
    warnings = list(settings.validate_api_keys())

    db_status = get_sqlite_status(include_internals=False)
    overall_status = "healthy"
    if db_status.get("status") != "healthy":
        overall_status = "degraded"
        warnings.append(
            db_status.get("message") or "SQLite persistent storage is currently degraded or unavailable"
        )

    return {
        "status": overall_status,
        "service": "Gativa API",
        "version": "1.0.0",
        "configured_providers": key_status,
        "database": db_status,
        "warnings": warnings,
    }
