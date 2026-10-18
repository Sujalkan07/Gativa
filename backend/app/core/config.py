"""Application configuration using pydantic-settings."""
from functools import lru_cache
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── API Keys ────────────────────────────────────────────────────────────
    google_maps_api_key: str = Field(default="", description="Google Maps Platform API key")
    tomtom_api_key: str = Field(default="", description="TomTom Traffic API key")
    openweather_api_key: str = Field(default="", description="OpenWeather API key")

    # ─── Database ─────────────────────────────────────────────────────────────
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    database_name: str = Field(default="gativa")

    # ─── Application ──────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )
    max_area_km2: float = Field(default=50.0, description="Maximum polygon area in km²")
    environment: str = Field(default="development")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_api_keys(self) -> dict[str, list[str]]:
        """
        Returns a dict of service → list of warnings about missing/invalid keys.
        Does NOT raise — allows partial operation with degraded data sources.
        """
        warnings: dict[str, list[str]] = {}

        if not self.tomtom_api_key:
            warnings["tomtom"] = [
                "TOMTOM_API_KEY is not configured. Traffic flow data will be unavailable. "
                "Get a key at https://developer.tomtom.com/"
            ]

        if not self.openweather_api_key:
            warnings["openweather"] = [
                "OPENWEATHER_API_KEY is not configured. Weather context will be unavailable. "
                "Get a key at https://home.openweathermap.org/api_keys"
            ]

        # Note: Mapping has been migrated to OpenStreetMap / CARTO / Leaflet and OSMnx.
        # Google Maps is no longer required.
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
