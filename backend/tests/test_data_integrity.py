"""
Comprehensive unit and regression tests for Gativa Phase 1:
Backend Data Accuracy, API Extraction, and Data Integrity.

Tests cover:
- TomTom Flow Segment Data parsing (all newly extracted fields)
- Missing and invalid API fields and absence of arbitrary fallbacks
- Travel-time delay calculations (positive, zero, faster-than-free-flow, missing)
- Confidence preservation as independent data quality metric
- Road closure explicit classification and handling
- TomTom Incident Details parsing (Point & LineString geometries, full properties, event codes, delays)
- Asymmetric bounding-box coordinate order validation (minLon,minLat,maxLon,maxLat)
- Spatial road segment matching (proximity, bearing/angle rejection, FRC mismatch rejection)
- Incident-to-road network matching (Point and LineString multi-segment overlap)
- Truthful sampling coverage metrics vs request success rate
- Summary calculations (road-length weighted vs segment arithmetic means, zero speed vs unavailable)
- Backwards compatibility with legacy database records
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.models.schemas import (
    TrafficObservation,
    TrafficIncident,
    TrafficSummary,
    RoadSegment,
    GeoJSONLineString,
    DataSourceCoverage,
)
from app.data_ingestion.tomtom import (
    fetch_flow_for_point,
    fetch_incidents_for_bbox,
    _classify_congestion,
    TOMTOM_FLOW_BASE,
    TOMTOM_INCIDENTS_BASE,
)
from app.geospatial.spatial_matching import (
    validate_flow_match,
    match_incidents_to_segments,
    _lat_lon_distance_meters,
    _compute_linestring_bearing,
    _bearing_difference_degrees,
)
from app.services.analysis import build_traffic_summary


@pytest.fixture(autouse=True)
def mock_tomtom_api_key(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "tomtom_api_key", "test_mock_tomtom_key")


# ─── 1. TomTom Flow Segment Data Parsing & Extended Fields ───────────────────

@pytest.mark.asyncio
async def test_tomtom_flow_parsing_all_extended_fields(monkeypatch):
    """Verify complete extraction of flow fields: travel times, confidence, closure, frc, geometry, openlr."""
    mock_response_data = {
        "flowSegmentData": {
            "frc": "FRC1",
            "currentSpeed": 36,
            "freeFlowSpeed": 50,
            "currentTravelTime": 140,
            "freeFlowTravelTime": 90,
            "confidence": 0.85,
            "roadClosure": False,
            "coordinates": {
                "coordinate": [
                    {"latitude": 28.6315, "longitude": 77.2167},
                    {"latitude": 28.6325, "longitude": 77.2177},
                ]
            },
            "openlr": "C3...==",
            "timestamp": "2026-11-21T07:00:00Z",
        }
    }

    async def mock_get(self, url, params=None, **kwargs):
        req = httpx.Request("GET", str(url), params=params)
        return httpx.Response(200, json=mock_response_data, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    obs, cov = await fetch_flow_for_point(28.6315, 77.2167, "seg_cp_01")
    assert cov.status == "ok"
    assert obs is not None
    assert obs.segment_id == "seg_cp_01"
    assert obs.observed_speed_kmh == 36.0
    assert obs.free_flow_speed_kmh == 50.0
    assert obs.current_travel_time_seconds == 140.0
    assert obs.free_flow_travel_time_seconds == 90.0
    # Delay: 140 - 90 = 50s; Percentage: (50 / 90) * 100 = 55.6%
    assert obs.delay_seconds == 50.0
    assert obs.delay_percentage == 55.6
    assert obs.confidence == 0.85
    assert obs.road_closure is False
    assert obs.frc == "FRC1"
    assert obs.coordinates == [[77.2167, 28.6315], [77.2177, 28.6325]]
    assert obs.openlr == "C3...=="
    assert obs.congestion_level == "free_flow"  # 36 / 50 = 0.72 (SCI B: >= 0.70)


@pytest.mark.asyncio
async def test_tomtom_flow_missing_and_invalid_fields(monkeypatch):
    """Verify safe handling of missing fields, absence of arbitrary fallbacks, and speed boundary checks."""
    # Free-flow speed missing: must NOT fabricate freeflow = observed
    mock_data = {
        "flowSegmentData": {
            "currentSpeed": 45,
            # freeFlowSpeed omitted
            "currentTravelTime": 80,
            # freeFlowTravelTime omitted
        }
    }

    async def mock_get(self, url, params=None, **kwargs):
        req = httpx.Request("GET", str(url), params=params)
        return httpx.Response(200, json=mock_data, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    obs, cov = await fetch_flow_for_point(28.63, 77.21, "seg_missing")
    assert cov.status == "ok"
    assert obs is not None
    assert obs.observed_speed_kmh == 45.0
    assert obs.free_flow_speed_kmh is None  # Integrity: no arbitrary fallback
    assert obs.speed_reduction_ratio is None
    assert obs.congestion_level == "unknown"
    assert obs.delay_seconds is None
    assert obs.delay_percentage is None
    assert obs.road_closure is False


@pytest.mark.asyncio
async def test_travel_time_delay_variations(monkeypatch):
    """Test travel time delay calculations across zero, faster-than-free-flow, and normal conditions."""
    cases = [
        # (cur_tt, ff_tt, expected_delay_sec, expected_delay_pct)
        (100, 100, 0.0, 0.0),        # Zero delay
        (80, 100, 0.0, 0.0),         # Faster than free flow (clamped to 0 delay safely)
        (150, 100, 50.0, 50.0),      # Standard delay
        (200, 80, 120.0, 150.0),     # Severe delay
    ]

    for cur_tt, ff_tt, exp_del, exp_pct in cases:
        data = {
            "flowSegmentData": {
                "currentSpeed": 30,
                "freeFlowSpeed": 50,
                "currentTravelTime": cur_tt,
                "freeFlowTravelTime": ff_tt,
            }
        }
        async def mock_get(self, url, params=None, **kwargs):
            req = httpx.Request("GET", str(url), params=params)
            return httpx.Response(200, json=data, request=req)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        obs, _ = await fetch_flow_for_point(28.63, 77.21, "seg_delay")
        assert obs.delay_seconds == exp_del
        assert obs.delay_percentage == exp_pct


# ─── 2. Explicit Road Closure Handling ───────────────────────────────────────

@pytest.mark.asyncio
async def test_road_closure_explicit_classification(monkeypatch):
    """Verify that a closed road is classified as 'closed' and not ordinary slow traffic."""
    mock_data = {
        "flowSegmentData": {
            "currentSpeed": 0,
            "freeFlowSpeed": 60,
            "currentTravelTime": 9999,
            "freeFlowTravelTime": 60,
            "confidence": 0.95,
            "roadClosure": True,
            "frc": "FRC0",
        }
    }

    async def mock_get(self, url, params=None, **kwargs):
        req = httpx.Request("GET", str(url), params=params)
        return httpx.Response(200, json=mock_data, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    obs, cov = await fetch_flow_for_point(28.63, 77.21, "seg_closed")
    assert cov.status == "ok"
    assert obs.road_closure is True
    assert obs.congestion_level == "closed"
    assert obs.speed_reduction_ratio == 1.0


def test_classify_congestion_function():
    """Unit test _classify_congestion rules aligned with Speed Condition Index (SCI)."""
    assert _classify_congestion(50, 50, road_closure=False) == "free_flow"
    assert _classify_congestion(35, 50, road_closure=False) == "free_flow"  # ratio 0.70 (SCI B boundary)
    assert _classify_congestion(30, 50, road_closure=False) == "moderate"   # ratio 0.60 (SCI C)
    assert _classify_congestion(20, 50, road_closure=False) == "moderate"   # ratio 0.40 (SCI D boundary)
    assert _classify_congestion(15, 50, road_closure=False) == "severe"     # ratio 0.30 (SCI E/F)
    assert _classify_congestion(0, 50, road_closure=True) == "closed"
    assert _classify_congestion(40, 50, road_closure=True) == "closed"       # closure overrides speed
    assert _classify_congestion(None, 50, road_closure=False) == "unknown"
    assert _classify_congestion(30, None, road_closure=False) == "unknown"


# ─── 3. TomTom Incident Details Parsing & Geometries ─────────────────────────

@pytest.mark.asyncio
async def test_incident_details_parsing_point_and_linestring(monkeypatch):
    """Verify parsing of Point and LineString incident geometries, delay magnitudes, and event codes."""
    mock_incidents_data = {
        "incidents": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [77.2167, 28.6315],
                },
                "properties": {
                    "id": "inc_point_01",
                    "iconCategory": 1,  # Accident
                    "magnitudeOfDelay": 3,  # Major
                    "events": [
                        {"code": 101, "description": "Accident involving 2 vehicles", "iconCategory": 1}
                    ],
                    "startTime": "2026-11-21T06:30:00Z",
                    "endTime": "2026-11-21T09:30:00Z",
                    "from": "Barakhamba",
                    "to": "Janpath",
                    "length": 150.0,
                    "delay": 360.0,
                    "roadNumbers": ["Inner Circle"],
                    "timeValidity": "present",
                    "probabilityOfOccurrence": "certain",
                    "numberOfReports": 3,
                    "lastReportTime": "2026-11-21T07:15:00Z",
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [77.210, 28.630],
                        [77.215, 28.632],
                        [77.220, 28.634],
                    ],
                },
                "properties": {
                    "id": "inc_line_02",
                    "iconCategory": 9,  # Road Works
                    "magnitudeOfDelay": 2,  # Moderate
                    "events": [
                        {"code": 501, "description": "Resurfacing works", "iconCategory": 9}
                    ],
                    "length": 1200.0,
                    "delay": 240.0,
                    "roadNumbers": ["NH-44"],
                },
            },
        ]
    }

    async def mock_get(self, url, params=None, **kwargs):
        req = httpx.Request("GET", str(url), params=params)
        return httpx.Response(200, json=mock_incidents_data, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    incidents, cov = await fetch_incidents_for_bbox(28.62, 77.20, 28.64, 77.23)
    assert cov.status == "ok"
    assert len(incidents) == 2

    # Verify Point incident
    pt_inc = incidents[0]
    assert pt_inc.incident_id == "inc_point_01"
    assert pt_inc.type == "accident"
    assert pt_inc.icon_category == 1
    assert pt_inc.icon_category_name == "accident"
    assert pt_inc.magnitude_of_delay == 3
    assert pt_inc.severity_label == "major"
    assert pt_inc.description == "Accident involving 2 vehicles"
    assert pt_inc.event_codes == [101]
    assert pt_inc.start_time == "2026-11-21T06:30:00Z"
    assert pt_inc.from_location == "Barakhamba"
    assert pt_inc.to_location == "Janpath"
    assert pt_inc.length_m == 150.0
    assert pt_inc.delay_seconds == 360.0
    assert pt_inc.road_numbers == ["Inner Circle"]
    assert pt_inc.number_of_reports == 3
    assert pt_inc.geometry["type"] == "Point"
    assert pt_inc.lat == 28.6315
    assert pt_inc.lng == 77.2167

    # Verify LineString incident: full coordinates preserved!
    ln_inc = incidents[1]
    assert ln_inc.incident_id == "inc_line_02"
    assert ln_inc.type == "road_works"
    assert ln_inc.icon_category_name == "road_works"
    assert ln_inc.severity_label == "moderate"
    assert ln_inc.geometry["type"] == "LineString"
    assert len(ln_inc.geometry["coordinates"]) == 3
    assert ln_inc.geometry["coordinates"][0] == [77.210, 28.630]
    assert ln_inc.geometry["coordinates"][2] == [77.220, 28.634]
    assert ln_inc.length_m == 1200.0


# ─── 4. Bounding-Box Order Bug Fix Verification ──────────────────────────────

@pytest.mark.asyncio
async def test_asymmetric_bbox_coordinate_ordering(monkeypatch):
    """
    CRITICAL TEST: Verify that TomTom v5 bbox uses minLon,minLat,maxLon,maxLat coordinate ordering.
    Uses asymmetric coordinates so latitude-longitude inversion will fail immediately.
    """
    captured_params = {}

    async def mock_get(self, url, params=None, **kwargs):
        nonlocal captured_params
        if params:
            captured_params.update(params)
        req = httpx.Request("GET", str(url), params=params)
        return httpx.Response(200, json={"incidents": []}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    min_lat = 12.500
    min_lng = 77.100
    max_lat = 13.900
    max_lng = 78.400

    await fetch_incidents_for_bbox(min_lat, min_lng, max_lat, max_lng)

    assert "bbox" in captured_params
    bbox_str = captured_params["bbox"]
    # TomTom requires: minLon,minLat,maxLon,maxLat
    expected_bbox = f"{min_lng},{min_lat},{max_lng},{max_lat}"
    inverted_bbox = f"{min_lat},{min_lng},{max_lat},{max_lng}"

    assert bbox_str == expected_bbox, (
        f"Bounding box ordering error: expected '{expected_bbox}', got '{bbox_str}'"
    )
    assert bbox_str != inverted_bbox, "Bounding box was incorrectly formatted in lat-lon order!"


# ─── 5. Spatial Road Segment Matching ────────────────────────────────────────

def test_spatial_matching_flow_to_segment():
    """Verify validation of TomTom observations against OSM segments (proximity, direction, FRC)."""
    # Target OSM segment: East-West running arterial corridor
    seg = RoadSegment(
        segment_id="seg_arterial_ew",
        name="MG Road",
        road_type="arterial",
        length_m=300.0,
        geometry=GeoJSONLineString(coordinates=[[77.200, 28.600], [77.203, 28.600]]),
        speed_limit_kmh=50.0,
        lanes=2,
        is_oneway=False,
    )

    # 1. Exact / High quality match: parallel fragment within 5m
    obs_valid = TrafficObservation(
        segment_id="seg_arterial_ew",
        observed_speed_kmh=35.0,
        frc="FRC2",
        coordinates=[[77.200, 28.60002], [77.203, 28.60002]],
    )
    is_valid, quality, dist_m = validate_flow_match(obs_valid, seg)
    assert is_valid is True
    assert quality in ("exact", "high")
    assert dist_m < 5.0

    # 2. Parallel road too far (> 60m away, e.g. service road or adjacent highway)
    obs_parallel_distant = TrafficObservation(
        segment_id="seg_arterial_ew",
        observed_speed_kmh=30.0,
        frc="FRC2",
        coordinates=[[77.200, 28.601], [77.203, 28.601]],  # ~110m north
    )
    is_valid, quality, dist_m = validate_flow_match(obs_parallel_distant, seg)
    assert is_valid is False
    assert quality == "unmatched"
    assert dist_m > 60.0

    # 3. Perpendicular crossing road (bearing differs by ~90 degrees)
    obs_crossing = TrafficObservation(
        segment_id="seg_arterial_ew",
        observed_speed_kmh=20.0,
        frc="FRC2",
        coordinates=[[77.2015, 28.599], [77.2015, 28.601]],  # North-South line
    )
    is_valid, quality, dist_m = validate_flow_match(obs_crossing, seg)
    assert is_valid is False
    assert quality == "unmatched"

    # 4. FRC mismatch: residential local road querying near FRC0 motorway flyover
    local_seg = RoadSegment(
        segment_id="seg_local_lane",
        name="Residential Alley",
        road_type="local",
        length_m=100.0,
        geometry=GeoJSONLineString(coordinates=[[77.200, 28.600], [77.201, 28.600]]),
        lanes=1,
    )
    obs_flyover = TrafficObservation(
        segment_id="seg_local_lane",
        observed_speed_kmh=90.0,
        frc="FRC0",  # Motorway
        coordinates=[[77.200, 28.6001], [77.201, 28.6001]],  # 11m away vertically
    )
    is_valid, quality, dist_m = validate_flow_match(obs_flyover, local_seg)
    assert is_valid is False
    assert quality == "unmatched"


# ─── 6. Incident-to-Road Network Spatial Matching ────────────────────────────

def test_incident_to_road_spatial_matching():
    """Verify spatial assignment of Point and LineString incidents to OSM road segments."""
    seg_a = RoadSegment(
        segment_id="seg_a",
        name="Corridor A",
        road_type="arterial",
        length_m=500.0,
        geometry=GeoJSONLineString(coordinates=[[77.100, 28.500], [77.105, 28.500]]),
        traffic=TrafficObservation(segment_id="seg_a", observed_speed_kmh=20.0),
    )
    seg_b = RoadSegment(
        segment_id="seg_b",
        name="Corridor B",
        road_type="arterial",
        length_m=500.0,
        geometry=GeoJSONLineString(coordinates=[[77.105, 28.500], [77.110, 28.500]]),
        traffic=TrafficObservation(segment_id="seg_b", observed_speed_kmh=25.0),
    )
    seg_c = RoadSegment(
        segment_id="seg_c",
        name="Distant Road",
        road_type="local",
        length_m=300.0,
        geometry=GeoJSONLineString(coordinates=[[77.150, 28.550], [77.153, 28.550]]),
    )

    segments = [seg_a, seg_b, seg_c]

    # Incident 1: Point incident right at seg_a midpoint (28.500, 77.1025)
    inc_pt = TrafficIncident(
        incident_id="inc_pt",
        type="accident",
        lat=28.50005,  # ~5m from seg_a
        lng=77.1025,
        geometry={"type": "Point", "coordinates": [77.1025, 28.50005]},
    )

    # Incident 2: LineString incident spanning across seg_a and seg_b
    inc_line = TrafficIncident(
        incident_id="inc_line",
        type="jam",
        lat=28.500,
        lng=77.105,
        geometry={
            "type": "LineString",
            "coordinates": [[77.102, 28.50002], [77.108, 28.50002]],
        },
    )

    # Incident 3: Distant incident (> 1km away)
    inc_distant = TrafficIncident(
        incident_id="inc_distant",
        type="fog",
        lat=28.590,
        lng=77.190,
        geometry={"type": "Point", "coordinates": [77.190, 28.590]},
    )

    incidents = [inc_pt, inc_line, inc_distant]
    match_incidents_to_segments(incidents, segments, proximity_threshold_m=35.0)

    # Incident 1 matches seg_a
    assert inc_pt.affected_segment_ids == ["seg_a"]
    assert inc_pt.match_quality in ("high", "medium", "CONFIRMED_AFFECTED")
    assert seg_a.traffic.has_incident is True

    # Incident 2 overlaps both seg_a and seg_b
    assert sorted(inc_line.affected_segment_ids) == ["seg_a", "seg_b"]
    assert inc_line.match_quality in ("high", "medium", "CONFIRMED_AFFECTED", "LIKELY_AFFECTED")
    assert seg_b.traffic.has_incident is True

    # Distant incident has no affected segments
    assert inc_distant.affected_segment_ids == []
    assert inc_distant.match_quality in ("unmatched", "UNMATCHED")


# ─── 7. Traffic Summary Calculations & Weighting ─────────────────────────────

def test_summary_calculations_and_length_weighting():
    """Verify segment-weighted vs road-length-weighted calculations, zero speed handling, and closure counts."""
    # Segment 1: Short street (100m) with heavy congestion (10 km/h)
    seg1 = RoadSegment(
        segment_id="s1",
        road_type="local",
        length_m=100.0,
        traffic=TrafficObservation(
            segment_id="s1",
            observed_speed_kmh=10.0,
            free_flow_speed_kmh=50.0,
            speed_reduction_ratio=0.80,
            congestion_level="severe",
            delay_seconds=40.0,
            delay_percentage=80.0,
            confidence=0.90,
        ),
    )

    # Segment 2: Long expressway (900m) running smoothly (90 km/h)
    seg2 = RoadSegment(
        segment_id="s2",
        road_type="highway",
        length_m=900.0,
        traffic=TrafficObservation(
            segment_id="s2",
            observed_speed_kmh=90.0,
            free_flow_speed_kmh=90.0,
            speed_reduction_ratio=0.0,
            congestion_level="free_flow",
            delay_seconds=0.0,
            delay_percentage=0.0,
            confidence=0.80,
        ),
    )

    # Segment 3: Road closure (0 km/h)
    seg3 = RoadSegment(
        segment_id="s3",
        road_type="arterial",
        length_m=200.0,
        traffic=TrafficObservation(
            segment_id="s3",
            observed_speed_kmh=0.0,
            free_flow_speed_kmh=40.0,
            speed_reduction_ratio=1.0,
            congestion_level="closed",
            road_closure=True,
            confidence=0.95,
        ),
    )

    # Segment 4: Unobserved segment (traffic=None)
    seg4 = RoadSegment(
        segment_id="s4",
        road_type="local",
        length_m=300.0,
        traffic=None,
    )

    segments = [seg1, seg2, seg3, seg4]
    incidents = [TrafficIncident(incident_id="inc1", type="accident", lat=28.6, lng=77.2)]

    summary = build_traffic_summary(
        segments=segments,
        incidents=incidents,
        sampled_count=3,
        failed_count=0,
        unmatched_count=0,
    )

    # 1. Congestion counts
    assert summary.congested_segments == 1
    assert summary.free_flow_segments == 1
    assert summary.closed_segments == 1
    assert summary.road_closure_count == 1
    assert summary.unknown_segments == 1  # seg4 is unobserved
    assert summary.total_observed == 3
    assert summary.total_eligible_segments == 4
    assert summary.incident_count == 1

    # 2. Arithmetic average speed: (10 + 90 + 0) / 3 = 33.3 km/h
    assert summary.avg_observed_speed_kmh == 33.3

    # 3. Road-length weighted average speed:
    # (10 * 100 + 90 * 900 + 0 * 200) / (100 + 900 + 200) = (1000 + 81000 + 0) / 1200 = 82000 / 1200 = 68.3 km/h
    assert summary.length_weighted_avg_observed_speed_kmh == 68.3

    # 4. Confidence average: (0.90 + 0.80 + 0.95) / 3 = 0.88
    assert summary.avg_confidence == 0.88

    # 5. Network sample coverage: 3 observed / 4 eligible = 75.0%
    assert summary.network_sample_coverage_pct == 75.0
    # Request success rate: (3 sampled - 0 failed) / 3 = 100.0%
    assert summary.request_success_rate_pct == 100.0


# ─── 8. Legacy Database Record Compatibility ─────────────────────────────────

def test_legacy_database_record_deserialization():
    """Verify that older database records deserialize cleanly without schema errors."""
    # Legacy TrafficObservation dict from previous version
    legacy_obs_data = {
        "segment_id": "seg_legacy_01",
        "observed_speed_kmh": 40.0,
        "free_flow_speed_kmh": 50.0,
        "speed_reduction_ratio": 0.20,
        "congestion_level": "moderate",
        "has_incident": False,
        "source": "tomtom",
    }
    obs = TrafficObservation(**legacy_obs_data)
    assert obs.segment_id == "seg_legacy_01"
    assert obs.observed_speed_kmh == 40.0
    assert obs.road_closure is False
    assert obs.delay_seconds is None
    assert obs.confidence is None

    # Legacy TrafficIncident dict
    legacy_inc_data = {
        "incident_id": "inc_legacy_01",
        "type": "jam",
        "lat": 28.63,
        "lng": 77.21,
        "severity": "2",
        "affected_segment_ids": [],
    }
    inc = TrafficIncident(**legacy_inc_data)
    assert inc.incident_id == "inc_legacy_01"
    assert inc.geometry is None
    assert inc.events == []
    assert inc.road_numbers == []

    # Legacy TrafficSummary dict
    legacy_summary_data = {
        "avg_observed_speed_kmh": 35.0,
        "avg_free_flow_speed_kmh": 50.0,
        "avg_speed_reduction": 0.30,
        "congested_segments": 2,
        "free_flow_segments": 5,
        "moderate_segments": 3,
        "unknown_segments": 0,
        "total_observed": 10,
    }
    summary = TrafficSummary(**legacy_summary_data)
    assert summary.total_observed == 10
    assert summary.closed_segments == 0
    assert summary.length_weighted_avg_observed_speed_kmh is None
