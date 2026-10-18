"""OpenWeather Current Weather API adapter."""
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone
import httpx

from app.core.config import get_settings
from app.models.schemas import WeatherContext, DataSourceCoverage

logger = logging.getLogger(__name__)

OPENWEATHER_BASE = "https://api.openweathermap.org/data/2.5/weather"
TIMEOUT = 10.0


async def fetch_weather(
    lat: float,
    lng: float,
) -> tuple[Optional[WeatherContext], DataSourceCoverage]:
    """
    Fetch current weather conditions for a geographic point from OpenWeather.
    Returns (weather_context, coverage).
    """
    settings = get_settings()
    if not settings.openweather_api_key:
        return None, DataSourceCoverage(
            source="openweather",
            status="unavailable",
            message="OPENWEATHER_API_KEY not configured. Set it in backend/.env",
        )

    params = {
        "lat": lat,
        "lon": lng,
        "appid": settings.openweather_api_key,
        "units": "metric",  # Celsius, m/s
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(OPENWEATHER_BASE, params=params)

        if resp.status_code == 401:
            return None, DataSourceCoverage(
                source="openweather",
                status="error",
                message="OpenWeather API key is invalid or not yet active. "
                "Keys can take up to 2 hours to activate after creation.",
            )
        if resp.status_code == 429:
            return None, DataSourceCoverage(
                source="openweather",
                status="error",
                message="OpenWeather API rate limit exceeded. Free tier allows 60 calls/min.",
            )
        if resp.status_code != 200:
            return None, DataSourceCoverage(
                source="openweather",
                status="error",
                message=f"OpenWeather API returned HTTP {resp.status_code}",
            )

        data = resp.json()
        main = data.get("main", {})
        weather_list = data.get("weather", [{}])
        wind = data.get("wind", {})
        rain = data.get("rain", {})
        snow = data.get("snow", {})

        condition = weather_list[0].get("description") if weather_list else None
        temp = main.get("temp")
        wind_speed_ms = wind.get("speed")
        wind_speed_kmh = wind_speed_ms * 3.6 if wind_speed_ms is not None else None
        precip_mm = rain.get("1h", 0) + snow.get("1h", 0)

        ts = datetime.fromtimestamp(data.get("dt", 0), tz=timezone.utc).isoformat()

        weather = WeatherContext(
            temperature_c=round(temp, 1) if temp is not None else None,
            condition=condition,
            precipitation_mm=round(precip_mm, 2) if precip_mm else None,
            wind_speed_kmh=round(wind_speed_kmh, 1) if wind_speed_kmh is not None else None,
            timestamp=ts,
            source="openweather",
        )
        return weather, DataSourceCoverage(source="openweather", status="ok", timestamp=ts)

    except httpx.TimeoutException:
        return None, DataSourceCoverage(
            source="openweather",
            status="error",
            message="OpenWeather API request timed out",
        )
    except Exception as exc:
        logger.exception("OpenWeather fetch failed for point (%s, %s)", lat, lng)
        return None, DataSourceCoverage(
            source="openweather",
            status="error",
            message=f"Unexpected error fetching weather data: {exc}",
        )
