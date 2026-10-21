"""
Location Geocoding & Search API router for Gativa.
Provides forward geocoding across cities, neighborhoods, landmarks, roads, and addresses.
Integrates TomTom Search API when available, falling back seamlessly to OpenStreetMap Nominatim
with compliant User-Agent identification and in-memory LRU caching.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional
import httpx
from fastapi import APIRouter, Query, status

from app.core.config import get_settings
from app.models.schemas import GeocodingResult, GeocodingSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/geocoding", tags=["Geocoding & Location Search"])

settings = get_settings()

# In-memory LRU-style cache: query_str -> (timestamp, GeocodingSearchResponse)
_CACHE: dict[str, tuple[float, GeocodingSearchResponse]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour
_MAX_CACHE_SIZE = 200


def _get_cached_results(query: str) -> Optional[GeocodingSearchResponse]:
    now = time.time()
    cached = _CACHE.get(query.lower().strip())
    if cached:
        cached_time, response = cached
        if now - cached_time < _CACHE_TTL_SECONDS:
            return response
        else:
            _CACHE.pop(query.lower().strip(), None)
    return None


def _set_cached_results(query: str, response: GeocodingSearchResponse) -> None:
    if len(_CACHE) >= _MAX_CACHE_SIZE:
        # Evict oldest entry
        oldest_key = min(_CACHE.keys(), key=lambda k: _CACHE[k][0], default=None)
        if oldest_key:
            _CACHE.pop(oldest_key, None)
    _CACHE[query.lower().strip()] = (time.time(), response)


async def _search_tomtom(query: str, limit: int, api_key: str) -> list[GeocodingResult]:
    """Query TomTom Search API v2."""
    url = f"https://api.tomtom.com/search/2/search/{httpx.URL(query).raw_path.decode('utf-8') if hasattr(httpx.URL(query), 'raw_path') else query}.json"
    params = {
        "key": api_key,
        "limit": min(limit, 10),
        "language": "en-US",
        "idxSet": "Geo,Addr,POI,Str,XStr",
    }
    async with httpx.AsyncClient(timeout=4.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning("TomTom search returned HTTP %d: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json()
        raw_results = data.get("results", [])

        results: list[GeocodingResult] = []
        for item in raw_results:
            pos = item.get("position", {})
            lat = pos.get("lat")
            lng = pos.get("lon")
            if lat is None or lng is None:
                continue

            address = item.get("address", {})
            poi = item.get("poi", {})
            name = poi.get("name") or address.get("streetName") or address.get("freeformAddress") or query
            freeform = address.get("freeformAddress", "")
            municipality = address.get("municipality", "")
            country = address.get("country", "")

            # Construct clean secondary description
            parts = [p for p in [municipality, address.get("countrySubdivision"), country] if p and p.lower() not in name.lower()]
            secondary = ", ".join(parts) if parts else freeform

            # Viewport bounding box: [min_lat, min_lng, max_lat, max_lng]
            viewport = item.get("viewport", {})
            bbox = None
            if viewport:
                btm = viewport.get("btmRightPoint", {})
                top = viewport.get("topLeftPoint", {})
                if "lat" in btm and "lon" in btm and "lat" in top and "lon" in top:
                    bbox = [float(btm["lat"]), float(top["lon"]), float(top["lat"]), float(btm["lon"])]

            results.append(
                GeocodingResult(
                    place_id=str(item.get("id") or f"tt_{lat}_{lng}"),
                    name=name,
                    display_name=freeform or f"{name}, {secondary}",
                    secondary_text=secondary or None,
                    lat=round(float(lat), 6),
                    lng=round(float(lng), 6),
                    bounding_box=bbox,
                    category=item.get("type"),
                    type=item.get("entityType"),
                    provider="tomtom",
                )
            )
        return results


async def _search_nominatim(query: str, limit: int) -> list[GeocodingResult]:
    """Query OpenStreetMap Nominatim geocoding service with compliant User-Agent."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": min(limit, 10),
    }
    headers = {
        "User-Agent": "Gativa-Traffic-Platform/1.0 (https://github.com/Sujalkan07/Gativa; info@gativa.ai)",
        "Accept-Language": "en",
    }
    async with httpx.AsyncClient(timeout=4.5) as client:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            logger.warning("Nominatim search returned HTTP %d: %s", resp.status_code, resp.text[:200])
            return []

        raw_results = resp.json()
        if not isinstance(raw_results, list):
            return []

        results: list[GeocodingResult] = []
        for item in raw_results:
            try:
                lat = float(item["lat"])
                lng = float(item["lon"])
            except (KeyError, ValueError, TypeError):
                continue

            display_name = item.get("display_name", "")
            parts = [p.strip() for p in display_name.split(",") if p.strip()]
            name = item.get("name") or (parts[0] if parts else query)
            secondary = ", ".join(parts[1:]) if len(parts) > 1 else None

            # Nominatim boundingbox: [min_lat, max_lat, min_lon, max_lon]
            raw_bbox = item.get("boundingbox")
            bbox = None
            if raw_bbox and len(raw_bbox) == 4:
                try:
                    # Convert to [min_lat, min_lng, max_lat, max_lng]
                    bbox = [float(raw_bbox[0]), float(raw_bbox[2]), float(raw_bbox[1]), float(raw_bbox[3])]
                except (ValueError, TypeError):
                    bbox = None

            results.append(
                GeocodingResult(
                    place_id=str(item.get("place_id") or f"osm_{lat}_{lng}"),
                    name=name,
                    display_name=display_name,
                    secondary_text=secondary,
                    lat=round(lat, 6),
                    lng=round(lng, 6),
                    bounding_box=bbox,
                    category=item.get("category"),
                    type=item.get("type"),
                    provider="openstreetmap",
                )
            )
        return results


@router.get(
    "/search",
    response_model=GeocodingSearchResponse,
    summary="Search geographic places, cities, landmarks, and roads",
)
async def search_locations(
    q: str = Query(..., min_length=2, description="Place, city, road, or address search query"),
    limit: int = Query(6, ge=1, le=10, description="Maximum number of suggestions to return"),
):
    query_clean = q.strip()
    if len(query_clean) < 2:
        return GeocodingSearchResponse(query=query_clean, count=0, results=[], provider="none")

    # Check cache
    cached = _get_cached_results(query_clean)
    if cached:
        return cached

    results: list[GeocodingResult] = []
    active_provider = "openstreetmap"

    # 1. Try TomTom if key configured
    if settings.tomtom_api_key:
        try:
            results = await _search_tomtom(query_clean, limit, settings.tomtom_api_key)
            if results:
                active_provider = "tomtom"
        except Exception as exc:
            logger.warning("TomTom geocoding failed, falling back to OSM: %s", exc)

    # 2. Fall back to OSM Nominatim if no TomTom results
    if not results:
        try:
            results = await _search_nominatim(query_clean, limit)
            active_provider = "openstreetmap"
        except Exception as exc:
            logger.error("OSM Nominatim geocoding error: %s", exc)
            results = []

    response = GeocodingSearchResponse(
        query=query_clean,
        count=len(results),
        results=results,
        provider=active_provider,
    )

    if results:
        _set_cached_results(query_clean, response)

    return response
