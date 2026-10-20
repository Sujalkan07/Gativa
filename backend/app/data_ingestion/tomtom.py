"""TomTom Traffic Flow and Incidents API adapter."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional
import httpx

from app.core.config import get_settings
from app.models.schemas import TrafficObservation, TrafficIncident, DataSourceCoverage

logger = logging.getLogger(__name__)

TOMTOM_FLOW_BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TOMTOM_INCIDENTS_BASE = "https://api.tomtom.com/traffic/services/5/incidentDetails"

TIMEOUT = 15.0


def _classify_congestion(
    observed: Optional[float], freeflow: Optional[float]
) -> str:
    if observed is None or freeflow is None or freeflow == 0:
        return "unknown"
    ratio = observed / freeflow
    if ratio >= 0.75:
        return "free_flow"
    elif ratio >= 0.5:
        return "moderate"
    else:
        return "severe"


async def fetch_flow_for_point(
    lat: float,
    lng: float,
    segment_id: str,
) -> tuple[Optional[TrafficObservation], DataSourceCoverage]:
    """
    Fetch traffic flow data for a single geographic point from TomTom.
    Returns (observation, coverage).
    """
    settings = get_settings()
    if not settings.tomtom_api_key:
        return None, DataSourceCoverage(
            source="tomtom_flow",
            status="unavailable",
            message="TOMTOM_API_KEY not configured. Set it in backend/.env",
        )

    params = {
        "key": settings.tomtom_api_key,
        "point": f"{lat},{lng}",
        "unit": "KMPH",
        "openLr": "false",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(TOMTOM_FLOW_BASE, params=params)

        if resp.status_code == 403:
            return None, DataSourceCoverage(
                source="tomtom_flow",
                status="error",
                message="TomTom API key invalid or lacks Traffic Flow permission. "
                "Check your key at developer.tomtom.com.",
            )
        if resp.status_code == 429:
            return None, DataSourceCoverage(
                source="tomtom_flow",
                status="error",
                message="TomTom API rate limit exceeded. Retry after a short delay.",
            )
        if resp.status_code != 200:
            return None, DataSourceCoverage(
                source="tomtom_flow",
                status="error",
                message=f"TomTom API returned HTTP {resp.status_code}",
            )

        data = resp.json()
        fd = data.get("flowSegmentData", {})
        observed = fd.get("currentSpeed")
        freeflow = fd.get("freeFlowSpeed")

        if observed is None:
            return None, DataSourceCoverage(
                source="tomtom_flow",
                status="partial",
                message="TomTom returned no speed data for this location",
            )

        reduction = None
        if observed is not None and freeflow and freeflow > 0:
            reduction = 1.0 - (observed / freeflow)

        now_ts = datetime.now(timezone.utc).isoformat()
        obs = TrafficObservation(
            segment_id=segment_id,
            observed_speed_kmh=float(observed) if observed is not None else None,
            free_flow_speed_kmh=float(freeflow) if freeflow is not None else None,
            speed_reduction_ratio=reduction,
            congestion_level=_classify_congestion(observed, freeflow),
            has_incident=False,
            observation_timestamp=now_ts,
            source="tomtom",
        )
        return obs, DataSourceCoverage(source="tomtom_flow", status="ok")

    except httpx.TimeoutException:
        return None, DataSourceCoverage(
            source="tomtom_flow",
            status="error",
            message="TomTom API request timed out",
        )
    except Exception as exc:
        logger.exception("TomTom flow fetch failed for point (%s, %s)", lat, lng)
        return None, DataSourceCoverage(
            source="tomtom_flow",
            status="error",
            message=f"Unexpected error fetching TomTom flow data: {exc}",
        )


async def fetch_incidents_for_bbox(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
) -> tuple[list[TrafficIncident], DataSourceCoverage]:
    """Fetch traffic incidents for a bounding box from TomTom."""
    settings = get_settings()
    if not settings.tomtom_api_key:
        return [], DataSourceCoverage(
            source="tomtom_incidents",
            status="unavailable",
            message="TOMTOM_API_KEY not configured",
        )

    # TomTom incidents v5 uses bbox: minLat,minLon,maxLat,maxLon
    bbox = f"{min_lat},{min_lng},{max_lat},{max_lng}"
    params = {
        "key": settings.tomtom_api_key,
        "bbox": bbox,
        "fields": "{incidents{type,geometry{coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,aci{probabilityOfOccurrence,numberOfReports,lastReportTime}}}}",
        "language": "en-GB",
        "t": "1111",
        "timeValidityFilter": "present",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(TOMTOM_INCIDENTS_BASE, params=params)

        if resp.status_code not in (200, 206):
            return [], DataSourceCoverage(
                source="tomtom_incidents",
                status="error",
                message=f"TomTom incidents API returned HTTP {resp.status_code}",
            )

        data = resp.json()
        incidents_raw = data.get("incidents", [])
        incidents: list[TrafficIncident] = []

        for inc in incidents_raw:
            props = inc.get("properties", {})
            geom = inc.get("geometry", {})
            coords = geom.get("coordinates", [])

            # Get a representative point
            lat_pt, lng_pt = 0.0, 0.0
            if coords:
                first = coords[0] if isinstance(coords[0], list) else coords
                if len(first) >= 2:
                    lng_pt, lat_pt = float(first[0]), float(first[1])

            events = props.get("events", [])
            description = events[0].get("description") if events else None

            incidents.append(TrafficIncident(
                incident_id=str(props.get("id", f"inc_{len(incidents)}")),
                type=str(props.get("iconCategory", "unknown")),
                description=description,
                lat=lat_pt,
                lng=lng_pt,
                severity=str(props.get("magnitudeOfDelay", "unknown")),
                affected_segment_ids=[],
            ))

        return incidents, DataSourceCoverage(source="tomtom_incidents", status="ok")

    except httpx.TimeoutException:
        return [], DataSourceCoverage(
            source="tomtom_incidents",
            status="error",
            message="TomTom incidents API request timed out",
        )
    except Exception as exc:
        logger.exception("TomTom incidents fetch failed")
        return [], DataSourceCoverage(
            source="tomtom_incidents",
            status="error",
            message=f"Unexpected error: {exc}",
        )
