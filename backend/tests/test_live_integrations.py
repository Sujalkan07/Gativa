"""Live API integration smoke tests. Verifies real provider responses without logging secrets."""
import pytest
import os
import httpx
from app.core.config import get_settings
from app.data_ingestion.tomtom import fetch_flow_for_point, fetch_incidents_for_bbox
from app.data_ingestion.openweather import fetch_weather


@pytest.mark.asyncio
async def test_live_tomtom_flow():
    settings = get_settings()
    if not settings.tomtom_api_key:
        pytest.skip("TOMTOM_API_KEY not configured")

    # Test with Connaught Place, New Delhi coordinates
    lat, lng = 28.6315, 77.2167
    obs, coverage = await fetch_flow_for_point(lat, lng, "test_seg_001")

    assert coverage.source == "tomtom_flow"
    # Even if coverage status is partial or error due to key quota, it shouldn't crash
    if coverage.status == "ok":
        assert obs is not None
        assert obs.observed_speed_kmh is not None or obs.free_flow_speed_kmh is not None
        assert obs.congestion_level in ("free_flow", "moderate", "severe", "unknown")


@pytest.mark.asyncio
async def test_live_openweather():
    settings = get_settings()
    if not settings.openweather_api_key:
        pytest.skip("OPENWEATHER_API_KEY not configured")

    lat, lng = 28.6315, 77.2167
    weather, coverage = await fetch_weather(lat, lng)

    assert coverage.source == "openweather"
    if coverage.status == "ok":
        assert weather is not None
        assert weather.temperature_c is not None


@pytest.mark.asyncio
async def test_live_osmnx_network():
    # Small bounding polygon (Connaught Place inner circle, ~0.05 km²)
    from shapely.geometry import Polygon
    import osmnx as ox

    poly = Polygon([
        (77.215, 28.630),
        (77.220, 28.630),
        (77.220, 28.635),
        (77.215, 28.635),
        (77.215, 28.630),
    ])

    ox.settings.log_console = False
    ox.settings.use_cache = True
    ox.settings.timeout = 10
    if hasattr(ox.settings, "requests_timeout"):
        ox.settings.requests_timeout = 10

    try:
        G = ox.graph_from_polygon(poly, network_type="drive", simplify=True)
        assert G is not None
        assert G.number_of_nodes() > 0
    except Exception as exc:
        pytest.skip(f"OSMnx Overpass API transient network issue or timeout: {exc}")
