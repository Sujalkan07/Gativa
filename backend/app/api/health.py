"""Health check and API status endpoint."""
from fastapi import APIRouter
from app.core.config import get_settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Health check endpoint confirming API status and configured providers."""
    settings = get_settings()
    key_status = {
        "google_maps": bool(settings.google_maps_api_key),
        "tomtom": bool(settings.tomtom_api_key),
        "openweather": bool(settings.openweather_api_key),
    }
    warnings = settings.validate_api_keys()

    return {
        "status": "healthy",
        "service": "Gativa API",
        "version": "1.0.0",
        "configured_providers": key_status,
        "warnings": warnings,
    }
