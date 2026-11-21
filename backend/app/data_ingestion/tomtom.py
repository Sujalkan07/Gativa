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

TIMEOUT = 7.0


# Mapping of TomTom iconCategory integers to readable string identifiers
ICON_CATEGORY_MAP: dict[int, str] = {
    0: "unknown",
    1: "accident",
    2: "fog",
    3: "dangerous_conditions",
    4: "rain",
    5: "ice",
    6: "jam",
    7: "lane_closed",
    8: "road_closed",
    9: "road_works",
    10: "wind",
    11: "flooding",
    14: "broken_down_vehicle",
}

# Mapping of TomTom magnitudeOfDelay integers to severity labels
MAGNITUDE_OF_DELAY_MAP: dict[int, str] = {
    0: "unknown",
    1: "minor",
    2: "moderate",
    3: "major",
    4: "undefined",
}


def _classify_congestion(
    observed: Optional[float],
    freeflow: Optional[float],
    road_closure: bool = False,
) -> str:
    if road_closure:
        return "closed"
    if observed is None or freeflow is None or freeflow <= 0:
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
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[TrafficObservation], DataSourceCoverage]:
    """
    Fetch traffic flow data for a single geographic point from TomTom.
    Supports optional shared httpx.AsyncClient for high-performance HTTP connection pooling.
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
        if client is not None:
            resp = await client.get(TOMTOM_FLOW_BASE, params=params)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                resp = await c.get(TOMTOM_FLOW_BASE, params=params)

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
        if not isinstance(data, dict):
            return None, DataSourceCoverage(
                source="tomtom_flow",
                status="error",
                message="TomTom API returned malformed response structure",
            )

        fd = data.get("flowSegmentData", {})
        observed = fd.get("currentSpeed")
        freeflow = fd.get("freeFlowSpeed")
        road_closure = bool(fd.get("roadClosure", False))

        # Validate speed values
        if observed is None or not isinstance(observed, (int, float)) or observed < 0 or observed > 250:
            if not (road_closure and observed == 0):
                return None, DataSourceCoverage(
                    source="tomtom_flow",
                    status="partial",
                    message="TomTom returned missing or invalid speed data for this location",
                )

        # Do not arbitrarily fallback freeflow to observed; maintain data integrity
        if freeflow is not None and (not isinstance(freeflow, (int, float)) or freeflow <= 0 or freeflow > 250):
            freeflow = None

        reduction = None
        if road_closure:
            reduction = 1.0
        elif observed is not None and freeflow is not None and freeflow > 0:
            reduction = max(0.0, min(1.0, 1.0 - (float(observed) / float(freeflow))))

        # Parse Travel Time & Delay
        cur_tt_raw = fd.get("currentTravelTime")
        ff_tt_raw = fd.get("freeFlowTravelTime")
        cur_tt_sec: Optional[float] = None
        ff_tt_sec: Optional[float] = None
        delay_seconds: Optional[float] = None
        delay_percentage: Optional[float] = None

        if cur_tt_raw is not None and isinstance(cur_tt_raw, (int, float)) and cur_tt_raw >= 0:
            cur_tt_sec = float(cur_tt_raw)
        if ff_tt_raw is not None and isinstance(ff_tt_raw, (int, float)) and ff_tt_raw >= 0:
            ff_tt_sec = float(ff_tt_raw)

        if cur_tt_sec is not None and ff_tt_sec is not None:
            # delay_seconds = currentTravelTime - freeFlowTravelTime
            raw_delay = cur_tt_sec - ff_tt_sec
            delay_seconds = max(0.0, round(raw_delay, 1))
            if ff_tt_sec > 0:
                # delay_percentage = (delay_seconds / freeFlowTravelTime) * 100
                delay_percentage = round((delay_seconds / ff_tt_sec) * 100.0, 1)
            elif delay_seconds == 0:
                delay_percentage = 0.0

        # Parse Confidence (0.0 to 1.0)
        conf_raw = fd.get("confidence")
        confidence: Optional[float] = None
        if conf_raw is not None and isinstance(conf_raw, (int, float)):
            confidence = max(0.0, min(1.0, float(conf_raw)))

        # Parse Road Fragment Coordinates
        parsed_coords: Optional[list[list[float]]] = None
        raw_coords = fd.get("coordinates")
        if isinstance(raw_coords, dict):
            raw_list = raw_coords.get("coordinate") or raw_coords.get("coordinates", [])
            if isinstance(raw_list, list):
                parsed_coords = []
                for pt in raw_list:
                    if isinstance(pt, dict):
                        plat = pt.get("latitude") if "latitude" in pt else pt.get("lat")
                        plon = pt.get("longitude") if "longitude" in pt else pt.get("lng") or pt.get("lon")
                        if plat is not None and plon is not None:
                            parsed_coords.append([round(float(plon), 6), round(float(plat), 6)])
                    elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        parsed_coords.append([round(float(pt[0]), 6), round(float(pt[1]), 6)])
        elif isinstance(raw_coords, list):
            parsed_coords = []
            for pt in raw_coords:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    parsed_coords.append([round(float(pt[0]), 6), round(float(pt[1]), 6)])

        # Provider observation timestamp: only use when genuinely supplied by provider
        provider_ts = fd.get("timestamp") or fd.get("observationTime")
        is_stale = False
        if provider_ts:
            try:
                obs_dt = datetime.fromisoformat(str(provider_ts).replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - obs_dt).total_seconds()
                if age_seconds > 3600:
                    is_stale = True
            except Exception:
                provider_ts = None

        retrieval_ts = datetime.now(timezone.utc).isoformat()
        obs = TrafficObservation(
            segment_id=segment_id,
            observed_speed_kmh=float(observed) if observed is not None else None,
            free_flow_speed_kmh=float(freeflow) if freeflow is not None else None,
            speed_reduction_ratio=reduction,
            congestion_level=_classify_congestion(observed, freeflow, road_closure=road_closure),
            has_incident=False,
            observation_timestamp=provider_ts,
            retrieval_timestamp=retrieval_ts,
            is_stale=is_stale,
            source="tomtom",
            current_travel_time_seconds=cur_tt_sec,
            free_flow_travel_time_seconds=ff_tt_sec,
            delay_seconds=delay_seconds,
            delay_percentage=delay_percentage,
            confidence=confidence,
            road_closure=road_closure,
            frc=str(fd.get("frc")) if fd.get("frc") else None,
            coordinates=parsed_coords,
            openlr=str(fd.get("openlr") or fd.get("openLr")) if (fd.get("openlr") or fd.get("openLr")) else None,
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
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[list[TrafficIncident], DataSourceCoverage]:
    """
    Fetch traffic incidents for a bounding box from TomTom Incident Details API v5.
    Correctly constructs bbox parameter in minLon,minLat,maxLon,maxLat coordinate order.
    Preserves Point and LineString geometries and complete incident properties.
    """
    settings = get_settings()
    if not settings.tomtom_api_key:
        return [], DataSourceCoverage(
            source="tomtom_incidents",
            status="unavailable",
            message="TOMTOM_API_KEY not configured",
        )

    # TomTom incidents v5 uses bbox: minLon,minLat,maxLon,maxLat
    min_lon = min_lng
    max_lon = max_lng
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    params = {
        "key": settings.tomtom_api_key,
        "bbox": bbox,
        "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,probabilityOfOccurrence,numberOfReports,lastReportTime,aci{probabilityOfOccurrence,numberOfReports,lastReportTime}}}}",
        "language": "en-GB",
        "t": "1111",
        "timeValidityFilter": "present",
    }

    try:
        if client is not None:
            resp = await client.get(TOMTOM_INCIDENTS_BASE, params=params)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                resp = await c.get(TOMTOM_INCIDENTS_BASE, params=params)

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
            geom_type = geom.get("type", "Point")
            raw_coords = geom.get("coordinates", [])

            # Extract full geometry and a representative point
            lat_pt, lng_pt = 0.0, 0.0
            parsed_geometry: Optional[dict[str, Any]] = None

            if geom_type == "Point" and raw_coords:
                if len(raw_coords) >= 2:
                    lng_pt = float(raw_coords[0])
                    lat_pt = float(raw_coords[1])
                    parsed_geometry = {"type": "Point", "coordinates": [lng_pt, lat_pt]}
            elif geom_type == "LineString" and raw_coords:
                # LineString coordinates are a list of [lng, lat]
                coords_list: list[list[float]] = []
                for pt in raw_coords:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        coords_list.append([float(pt[0]), float(pt[1])])
                if coords_list:
                    parsed_geometry = {"type": "LineString", "coordinates": coords_list}
                    # Representative point is midpoint of line
                    mid_pt = coords_list[len(coords_list) // 2]
                    lng_pt = mid_pt[0]
                    lat_pt = mid_pt[1]
            elif raw_coords:
                # Handle generic coordinate sequence fallback
                if isinstance(raw_coords[0], (list, tuple)):
                    coords_list = [[float(c[0]), float(c[1])] for c in raw_coords if len(c) >= 2]
                    if coords_list:
                        parsed_geometry = {"type": "LineString", "coordinates": coords_list}
                        lng_pt, lat_pt = coords_list[len(coords_list) // 2][0], coords_list[len(coords_list) // 2][1]
                elif len(raw_coords) >= 2:
                    lng_pt, lat_pt = float(raw_coords[0]), float(raw_coords[1])
                    parsed_geometry = {"type": "Point", "coordinates": [lng_pt, lat_pt]}

            # Events
            events_raw = props.get("events", [])
            events_list: list[dict[str, Any]] = []
            event_codes: list[int] = []
            event_descriptions: list[str] = []

            for ev in events_raw:
                if isinstance(ev, dict):
                    events_list.append(ev)
                    if "code" in ev and ev["code"] is not None:
                        try:
                            event_codes.append(int(ev["code"]))
                        except (ValueError, TypeError):
                            pass
                    if ev.get("description"):
                        event_descriptions.append(str(ev["description"]))

            description = event_descriptions[0] if event_descriptions else None

            # Icon category and magnitude
            raw_icon = props.get("iconCategory")
            icon_cat_int: Optional[int] = None
            if raw_icon is not None:
                try:
                    icon_cat_int = int(raw_icon)
                except (ValueError, TypeError):
                    pass
            icon_cat_name = ICON_CATEGORY_MAP.get(icon_cat_int, "unknown") if icon_cat_int is not None else "unknown"

            raw_mag = props.get("magnitudeOfDelay")
            mag_int: Optional[int] = None
            if raw_mag is not None:
                try:
                    mag_int = int(raw_mag)
                except (ValueError, TypeError):
                    pass
            severity_label = MAGNITUDE_OF_DELAY_MAP.get(mag_int, "unknown") if mag_int is not None else "unknown"

            # Length and delay
            length_val = props.get("length")
            delay_val = props.get("delay")
            length_m = float(length_val) if length_val is not None and isinstance(length_val, (int, float)) else None
            delay_sec = float(delay_val) if delay_val is not None and isinstance(delay_val, (int, float)) else None

            # Road numbers
            road_numbers_raw = props.get("roadNumbers", [])
            road_numbers = [str(rn) for rn in road_numbers_raw] if isinstance(road_numbers_raw, list) else []

            # ACI fallback fields
            aci = props.get("aci", {}) or {}
            prob = props.get("probabilityOfOccurrence") or aci.get("probabilityOfOccurrence")
            num_reports = props.get("numberOfReports") or aci.get("numberOfReports")
            last_report = props.get("lastReportTime") or aci.get("lastReportTime")

            incidents.append(TrafficIncident(
                incident_id=str(props.get("id", f"inc_{len(incidents)}")),
                type=icon_cat_name,
                description=description,
                lat=lat_pt,
                lng=lng_pt,
                severity=str(props.get("magnitudeOfDelay", severity_label)),
                affected_segment_ids=[],
                icon_category=icon_cat_int,
                icon_category_name=icon_cat_name,
                magnitude_of_delay=mag_int,
                severity_label=severity_label,
                events=events_list,
                event_codes=event_codes,
                event_descriptions=event_descriptions,
                start_time=props.get("startTime"),
                end_time=props.get("endTime"),
                from_location=props.get("from"),
                to_location=props.get("to"),
                length_m=length_m,
                delay_seconds=delay_sec,
                road_numbers=road_numbers,
                time_validity=props.get("timeValidity"),
                probability_of_occurrence=str(prob) if prob is not None else None,
                number_of_reports=int(num_reports) if num_reports is not None else None,
                last_report_time=str(last_report) if last_report is not None else None,
                geometry=parsed_geometry,
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
