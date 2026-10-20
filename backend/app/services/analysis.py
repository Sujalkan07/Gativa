"""
Main analysis orchestration service.
Coordinates road network retrieval, traffic data, weather, bottleneck detection,
and recommendation generation into a complete analysis pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
import httpx

from app.core.config import get_settings
from app.core.database import get_database, is_mongodb_connected, get_persistence_mode
from app.core.sqlite_store import (
    save_analysis_sync,
    get_analysis_sync,
    save_traffic_flow_sync,
    get_traffic_flow_sync,
    save_recommendations_sync,
    get_recommendations_sync,
)
from app.data_ingestion.tomtom import fetch_flow_for_point, fetch_incidents_for_bbox
from app.data_ingestion.openweather import fetch_weather
from app.geospatial.road_network import fetch_road_network
from app.recommendations.engine import generate_recommendations
from app.models.schemas import (
    AnalysisResult,
    GeoJSONPolygon,
    TrafficFlowResult,
    TrafficSummary,
    RecommendationsResult,
    DataSourceCoverage,
    TrafficObservation,
)

logger = logging.getLogger(__name__)

MAX_TRAFFIC_SAMPLES = 30  # Max TomTom calls per analysis to stay within rate limits


def _centroid(coords: list[list[float]]) -> tuple[float, float]:
    """Compute centroid of polygon coordinates [lng, lat]."""
    lats = [c[1] for c in coords]
    lngs = [c[0] for c in coords]
    return sum(lats) / len(lats), sum(lngs) / len(lngs)


def _bbox(coords: list[list[float]]) -> tuple[float, float, float, float]:
    """Compute bounding box from polygon coordinates [lng, lat]."""
    lats = [c[1] for c in coords]
    lngs = [c[0] for c in coords]
    return min(lats), min(lngs), max(lats), max(lngs)


async def _reverse_geocode_area_name(lat: float, lng: float, api_key: str) -> Optional[str]:
    """Reverse geocode coordinates using TomTom Search API to get locality name."""
    if not api_key:
        return None
    try:
        url = f"https://api.tomtom.com/search/2/reverseGeocode/{lat},{lng}.json"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params={"key": api_key})
            if resp.status_code == 200:
                data = resp.json()
                addresses = data.get("addresses", [])
                if addresses:
                    addr = addresses[0].get("address", {})
                    sub = addr.get("municipalitySubdivision") or addr.get("streetName") or addr.get("street")
                    city = addr.get("municipality") or addr.get("countrySubdivision")
                    if sub and city:
                        return f"{sub}, {city}"
                    return city or sub
    except Exception as exc:
        logger.debug("Reverse geocoding failed: %s", exc)
    return None


async def run_analysis(polygon: GeoJSONPolygon) -> AnalysisResult:
    """
    Execute the complete Gativa analysis pipeline for a polygon.

    Pipeline:
    1. Validate polygon
    2. Retrieve road network from OSM
    3. Fetch TomTom traffic data for representative segment midpoints
    4. Fetch weather context
    5. Detect traffic bottlenecks
    6. Generate recommendations
    7. Persist to MongoDB
    8. Return structured result
    """
    settings = get_settings()
    analysis_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    logger.info("Starting analysis %s", analysis_id)

    ring = polygon.coordinates[0]
    centroid_lat, centroid_lng = _centroid(ring)
    min_lat, min_lng, max_lat, max_lng = _bbox(ring)

    # Reverse geocode area name asynchronously
    area_name_task = asyncio.create_task(
        _reverse_geocode_area_name(centroid_lat, centroid_lng, settings.tomtom_api_key)
    )

    # Check key configuration warnings (non-fatal)
    key_warnings = settings.validate_api_keys()
    warnings: list[str] = []
    for service_warnings in key_warnings.values():
        warnings.extend(service_warnings)

    # ─── Step 1: Road Network ────────────────────────────────────────────────
    logger.info("Fetching road network...")
    G, segments, road_metrics, bottlenecks, osm_coverage = await fetch_road_network(
        polygon_coords=ring,
        max_area_km2=settings.max_area_km2,
    )

    if road_metrics is None:
        # Critical failure - can't proceed without road network
        result = AnalysisResult(
            analysis_id=analysis_id,
            status="failed",
            polygon=polygon,
            area_km2=0.0,
            created_at=created_at,
            data_sources=[osm_coverage],
            warnings=warnings,
            error_message=osm_coverage.message or "Failed to retrieve road network data.",
        )
        await _persist_analysis(analysis_id, result)
        return result

    area_km2 = road_metrics.area_km2
    data_sources: list[DataSourceCoverage] = [osm_coverage]

    # ─── Step 2: Traffic Data ────────────────────────────────────────────────
    logger.info("Fetching TomTom traffic data...")
    traffic_by_segment: dict[str, TrafficObservation] = {}
    all_traffic_coverages: list[DataSourceCoverage] = []

    if segments:
        # Sample representative segments (midpoints), bounded by MAX_TRAFFIC_SAMPLES
        # Prioritize highways and arterials
        priority_segs = [s for s in segments if s.road_type in ("highway", "arterial")]
        other_segs = [s for s in segments if s.road_type == "local"]
        sample_segs = (priority_segs + other_segs)[:MAX_TRAFFIC_SAMPLES]

        # Fetch traffic in parallel with a semaphore to avoid overwhelming the API
        sem = asyncio.Semaphore(6)

        async def fetch_one(seg):
            async with sem:
                # Use segment true distance midpoint from geometry if available
                if seg.geometry and seg.geometry.coordinates and len(seg.geometry.coordinates) >= 2:
                    coords = seg.geometry.coordinates
                    try:
                        from shapely.geometry import LineString
                        line = LineString([(c[0], c[1]) for c in coords])
                        mid_pt = line.interpolate(0.5, normalized=True)
                        lng_pt, lat_pt = mid_pt.x, mid_pt.y
                    except Exception:
                        mid_idx = len(coords) // 2
                        lng_pt, lat_pt = coords[mid_idx][0], coords[mid_idx][1]
                elif seg.geometry and seg.geometry.coordinates and len(seg.geometry.coordinates) == 1:
                    lng_pt, lat_pt = seg.geometry.coordinates[0][0], seg.geometry.coordinates[0][1]
                else:
                    lat_pt, lng_pt = centroid_lat, centroid_lng
                return await fetch_flow_for_point(lat_pt, lng_pt, seg.segment_id)

        tasks = [fetch_one(seg) for seg in sample_segs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for seg, result in zip(sample_segs, results):
            if isinstance(result, Exception):
                logger.warning("Traffic fetch failed for segment %s: %s", seg.segment_id, result)
                continue
            obs, coverage = result
            if obs:
                traffic_by_segment[seg.segment_id] = obs
                # Annotate segment with traffic
                for s in segments:
                    if s.segment_id == seg.segment_id:
                        s.traffic = obs
            all_traffic_coverages.append(coverage)

        # Aggregate coverage status
        if all_traffic_coverages:
            ok_count = sum(1 for c in all_traffic_coverages if c.status == "ok")
            if ok_count == 0:
                status = all_traffic_coverages[0].status
                msg = all_traffic_coverages[0].message
            elif ok_count == len(all_traffic_coverages):
                status, msg = "ok", None
            else:
                status, msg = "partial", f"{ok_count}/{len(all_traffic_coverages)} traffic samples retrieved"

            data_sources.append(DataSourceCoverage(
                source="tomtom_flow",
                status=status,
                message=msg,
            ))

    # ─── Step 3: Incidents ───────────────────────────────────────────────────
    incidents, incidents_coverage = await fetch_incidents_for_bbox(
        min_lat, min_lng, max_lat, max_lng
    )
    data_sources.append(incidents_coverage)

    # Enhance bottlenecks with traffic observations
    for b in bottlenecks:
        obs = traffic_by_segment.get(b.segment_id)
        if obs:
            b.bottleneck_type = "combined"
            if obs.speed_reduction_ratio is not None:
                b.speed_reduction = obs.speed_reduction_ratio

    # Also create traffic-based bottlenecks for severely congested segments
    for seg_id, obs in traffic_by_segment.items():
        if obs.congestion_level == "severe" and seg_id not in {b.segment_id for b in bottlenecks}:
            seg = next((s for s in segments if s.segment_id == seg_id), None)
            if seg and seg.geometry and seg.geometry.coordinates:
                mid = seg.geometry.coordinates[len(seg.geometry.coordinates) // 2]
                from app.models.schemas import BottleneckCandidate
                bottlenecks.append(BottleneckCandidate(
                    segment_id=seg_id,
                    location_name=seg.name,
                    lat=mid[1],
                    lng=mid[0],
                    bottleneck_type="traffic_observed",
                    severity="high" if (obs.speed_reduction_ratio or 0) > 0.5 else "medium",
                    evidence=[
                        f"TomTom observed speed: {obs.observed_speed_kmh:.0f} km/h" if obs.observed_speed_kmh else "Speed data observed",
                        f"Free-flow speed: {obs.free_flow_speed_kmh:.0f} km/h" if obs.free_flow_speed_kmh else "",
                        f"Speed reduction: {obs.speed_reduction_ratio * 100:.0f}%" if obs.speed_reduction_ratio else "",
                    ],
                    centrality_score=None,
                    speed_reduction=obs.speed_reduction_ratio,
                ))

    road_metrics.potential_bottleneck_count = len(bottlenecks)

    # ─── Step 4: Weather ─────────────────────────────────────────────────────
    logger.info("Fetching weather context...")
    weather, weather_coverage = await fetch_weather(centroid_lat, centroid_lng)
    data_sources.append(weather_coverage)

    # ─── Step 5: Recommendations ─────────────────────────────────────────────
    logger.info("Generating recommendations...")
    recs_result = generate_recommendations(
        analysis_id=analysis_id,
        bottlenecks=bottlenecks,
        traffic_by_segment=traffic_by_segment,
        metrics=road_metrics,
        weather=weather,
    )

    # ─── Compose final result ─────────────────────────────────────────────────
    completed_at = datetime.now(timezone.utc).isoformat()
    try:
        area_name = await area_name_task
    except Exception:
        area_name = None

    # Prioritize segments for frontend visualization: highways & arterials first, then named streets, then by length
    prioritized_segments = sorted(
        segments,
        key=lambda s: (
            0 if s.road_type == "highway" else 1 if s.road_type == "arterial" else 2,
            0 if s.name and not any(gen in s.name for gen in ["Local", "Connecting", "Sector Street"]) else 1,
            -s.length_m,
        ),
    )

    total_eligible = len(segments)
    capped_segments = prioritized_segments[:600]
    omitted = max(0, total_eligible - len(capped_segments))

    road_metrics.total_eligible_segments = total_eligible
    road_metrics.segments_analyzed = total_eligible
    road_metrics.segments_returned = len(capped_segments)
    road_metrics.omitted_segments_count = omitted

    if omitted > 0:
        warnings.append(
            f"Road network truncated: returning {len(capped_segments)} prioritized segments out of {total_eligible} total eligible segments to maintain responsive performance."
        )

    result = AnalysisResult(
        analysis_id=analysis_id,
        status="completed",
        polygon=polygon,
        area_km2=area_km2,
        area_name=area_name,
        created_at=created_at,
        completed_at=completed_at,
        road_network=road_metrics,
        segments=capped_segments,  # Cap with priority preserved (600 segments)
        bottlenecks=bottlenecks,
        weather=weather,
        data_sources=data_sources,
        warnings=warnings + recs_result.data_quality_warnings,
    )

    # Persist
    await _persist_analysis(analysis_id, result)
    await _persist_traffic_flow(analysis_id, capped_segments, incidents, traffic_by_segment)
    await _persist_recommendations(analysis_id, recs_result)

    logger.info(
        "Analysis %s completed: %d segments, %d bottlenecks, %d recommendations",
        analysis_id,
        len(segments),
        len(bottlenecks),
        len(recs_result.recommendations),
    )
    return result


# In-memory fallbacks when MongoDB is offline
_in_memory_analyses: dict[str, dict] = {}
_in_memory_traffic: dict[str, dict] = {}
_in_memory_recommendations: dict[str, dict] = {}


async def _persist_analysis(analysis_id: str, result: AnalysisResult) -> None:
    doc = result.model_dump()
    doc["_id"] = analysis_id
    
    # 1. Determine storage mode and attempt MongoDB if connected
    mongo_saved = False
    if is_mongodb_connected():
        try:
            db = get_database()
            doc["storage_mode"] = "mongodb"
            await db["analyses"].replace_one({"_id": analysis_id}, doc, upsert=True)
            result.storage_mode = "mongodb"
            mongo_saved = True
        except Exception as exc:
            logger.warning("MongoDB write failed for analysis %s: %s", analysis_id, exc)

    if not mongo_saved:
        doc["storage_mode"] = "sqlite"
        result.storage_mode = "sqlite"

    # 2. Always persist locally to durable SQLite store (backend/data/gativa.db)
    try:
        await asyncio.to_thread(save_analysis_sync, analysis_id, doc)
    except Exception as exc:
        logger.error("SQLite write failed for analysis %s: %s", analysis_id, exc)
        if not mongo_saved:
            doc["storage_mode"] = "in_memory"
            result.storage_mode = "in_memory"

    # 3. Cache in memory for fastest lookups
    _in_memory_analyses[analysis_id] = doc


async def _persist_traffic_flow(
    analysis_id: str,
    segments,
    incidents,
    traffic_by_segment: dict,
) -> None:
    doc = {
        "_id": analysis_id,
        "analysis_id": analysis_id,
        "segments": [s.model_dump() for s in segments[:600]],
        "incidents": [i.model_dump() for i in incidents],
        "traffic_map": {k: v.model_dump() for k, v in traffic_by_segment.items()},
    }
    _in_memory_traffic[analysis_id] = doc

    if is_mongodb_connected():
        try:
            db = get_database()
            await db["traffic_flow"].replace_one({"_id": analysis_id}, doc, upsert=True)
        except Exception as exc:
            logger.warning("MongoDB write failed for traffic flow %s: %s", analysis_id, exc)

    try:
        await asyncio.to_thread(save_traffic_flow_sync, analysis_id, doc)
    except Exception as exc:
        logger.error("SQLite write failed for traffic flow %s: %s", analysis_id, exc)


async def _persist_recommendations(
    analysis_id: str,
    recs: RecommendationsResult,
) -> None:
    doc = recs.model_dump()
    doc["_id"] = analysis_id
    _in_memory_recommendations[analysis_id] = doc

    if is_mongodb_connected():
        try:
            db = get_database()
            await db["recommendations"].replace_one({"_id": analysis_id}, doc, upsert=True)
        except Exception as exc:
            logger.warning("MongoDB write failed for recommendations %s: %s", analysis_id, exc)

    try:
        await asyncio.to_thread(save_recommendations_sync, analysis_id, doc)
    except Exception as exc:
        logger.error("SQLite write failed for recommendations %s: %s", analysis_id, exc)


async def get_analysis_by_id(analysis_id: str) -> Optional[AnalysisResult]:
    # 1. Check in-memory cache first
    if analysis_id in _in_memory_analyses:
        data = dict(_in_memory_analyses[analysis_id])
        data.pop("_id", None)
        return AnalysisResult(**data)

    # 2. Try MongoDB if active
    if is_mongodb_connected():
        try:
            db = get_database()
            doc = await db["analyses"].find_one({"_id": analysis_id})
            if doc:
                doc.pop("_id", None)
                _in_memory_analyses[analysis_id] = dict(doc)
                return AnalysisResult(**doc)
        except Exception as exc:
            logger.warning("MongoDB read failed for analysis %s: %s", analysis_id, exc)

    # 3. Try SQLite durable local store
    try:
        doc = await asyncio.to_thread(get_analysis_sync, analysis_id)
        if doc:
            doc.pop("_id", None)
            _in_memory_analyses[analysis_id] = dict(doc)
            return AnalysisResult(**doc)
    except Exception as exc:
        logger.warning("SQLite read failed for analysis %s: %s", analysis_id, exc)

    return None


async def get_traffic_flow_by_id(analysis_id: str) -> Optional[TrafficFlowResult]:
    """Retrieve traffic flow data from MongoDB, SQLite, or in-memory fallback."""
    doc = _in_memory_traffic.get(analysis_id)

    if not doc and is_mongodb_connected():
        try:
            db = get_database()
            doc = await db["traffic_flow"].find_one({"_id": analysis_id})
        except Exception as exc:
            logger.warning("MongoDB read failed for traffic flow %s: %s", analysis_id, exc)

    if not doc:
        try:
            doc = await asyncio.to_thread(get_traffic_flow_sync, analysis_id)
        except Exception as exc:
            logger.warning("SQLite read failed for traffic flow %s: %s", analysis_id, exc)

    if not doc:
        return None

    try:
        from app.models.schemas import RoadSegment, TrafficIncident

        segments = [RoadSegment(**s) for s in doc.get("segments", [])]
        incidents = [TrafficIncident(**i) for i in doc.get("incidents", [])]

        # Compute summary
        obs_speeds = [
            s.traffic.observed_speed_kmh
            for s in segments
            if s.traffic and s.traffic.observed_speed_kmh is not None
        ]
        ff_speeds = [
            s.traffic.free_flow_speed_kmh
            for s in segments
            if s.traffic and s.traffic.free_flow_speed_kmh is not None
        ]
        congestion_counts = {"free_flow": 0, "moderate": 0, "severe": 0, "unknown": 0}
        for s in segments:
            if s.traffic:
                congestion_counts[s.traffic.congestion_level] = congestion_counts.get(s.traffic.congestion_level, 0) + 1

        summary = TrafficSummary(
            avg_observed_speed_kmh=round(sum(obs_speeds) / len(obs_speeds), 1) if obs_speeds else None,
            avg_free_flow_speed_kmh=round(sum(ff_speeds) / len(ff_speeds), 1) if ff_speeds else None,
            congested_segments=congestion_counts.get("severe", 0),
            free_flow_segments=congestion_counts.get("free_flow", 0),
            moderate_segments=congestion_counts.get("moderate", 0),
            unknown_segments=congestion_counts.get("unknown", 0),
            total_observed=sum(1 for s in segments if s.traffic),
        )

        return TrafficFlowResult(
            analysis_id=analysis_id,
            segments=segments,
            summary=summary,
            incidents=incidents,
            data_source=DataSourceCoverage(source="tomtom", status="ok"),
        )
    except Exception as exc:
        logger.error("Failed to build traffic flow for %s: %s", analysis_id, exc)
        return None


async def get_recommendations_by_id(analysis_id: str) -> Optional[RecommendationsResult]:
    doc = _in_memory_recommendations.get(analysis_id)

    if not doc and is_mongodb_connected():
        try:
            db = get_database()
            doc = await db["recommendations"].find_one({"_id": analysis_id})
        except Exception as exc:
            logger.warning("MongoDB read failed for recommendations %s: %s", analysis_id, exc)

    if not doc:
        try:
            doc = await asyncio.to_thread(get_recommendations_sync, analysis_id)
        except Exception as exc:
            logger.warning("SQLite read failed for recommendations %s: %s", analysis_id, exc)

    if not doc:
        return None

    data = dict(doc)
    data.pop("_id", None)
    return RecommendationsResult(**data)

