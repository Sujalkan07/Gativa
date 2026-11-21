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

    # ─── Application & Security ───────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        description="Comma-separated list of allowed CORS origins",
    )
    cors_allowed_methods: str = Field(
        default="GET,POST,PUT,DELETE,OPTIONS",
        description="Comma-separated list of allowed HTTP methods for CORS",
    )
    cors_allowed_headers: str = Field(
        default="Content-Type,Authorization,X-API-Key,X-Proxy-Secret,X-Forwarded-User,X-Correlation-ID,Accept",
        description="Comma-separated list of allowed HTTP headers for CORS",
    )
    max_area_km2: float = Field(default=50.0, description="Maximum polygon area in km²")
    environment: str = Field(default="development")

    # Security & Authentication Boundaries
    api_key: str = Field(default="", description="Secret API key for direct bearer / header authentication")
    proxy_secret: str = Field(default="", description="Shared secret for trusted reverse-proxy authentication")
    trusted_proxy_header: str = Field(default="x-forwarded-user", description="Header containing identity from trusted reverse proxy")
    trusted_proxy_secret_header: str = Field(default="x-proxy-secret", description="Header containing reverse-proxy shared secret")
    require_auth_in_dev: bool = Field(default=False, description="Whether to enforce auth in development mode")

    # Server Network Binding
    server_host: str = Field(default="127.0.0.1", description="Default network bind address (loopback)")
    allow_external_binding: bool = Field(default=False, description="Explicit approval to bind to 0.0.0.0 or ::")

    # Concurrency and Rate Limits
    rate_limit_per_minute: int = Field(default=60, description="Max requests per minute per client")
    max_concurrent_analyses: int = Field(default=2, description="Max concurrent analysis jobs per instance")
    max_concurrent_simulations: int = Field(default=2, description="Max concurrent simulation preparations")
    max_active_sessions: int = Field(default=4, description="Max concurrently running simulation sessions")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_methods_list(self) -> list[str]:
        return [m.strip() for m in self.cors_allowed_methods.split(",") if m.strip()]

    @property
    def cors_headers_list(self) -> list[str]:
        return [h.strip() for h in self.cors_allowed_headers.split(",") if h.strip()]

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
