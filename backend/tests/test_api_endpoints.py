"""Integration tests for FastAPI endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "configured_providers" in data
    assert "warnings" in data


@pytest.mark.asyncio
async def test_get_nonexistent_analysis_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/analyses/nonexistent-id-000")
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_create_analysis_with_invalid_polygon_returns_422():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Invalid: ring has only 2 points
        response = await ac.post(
            "/api/analyses",
            json={"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_full_analysis_lifecycle_and_geojson_export(monkeypatch):
    """
    Test full lifecycle:
    1. POST /api/analyses creates an analysis and returns AnalysisResult.
    2. GET /api/analyses/{id} retrieves the saved analysis.
    3. GET /api/analyses/{id}/traffic-flow retrieves traffic flow metrics.
    4. GET /api/analyses/{id}/recommendations retrieves evidence-backed recommendations.
    5. GET /api/analyses/{id}/export/geojson exports valid GeoJSON FeatureCollection.
    """
    from unittest.mock import AsyncMock
    from app.models.schemas import (
        RoadSegment,
        RoadNetworkMetrics,
        BottleneckCandidate,
        DataSourceCoverage,
        TrafficObservation,
        WeatherContext,
        GeoJSONLineString,
    )
    import app.services.analysis as analysis_service

    # Mock road network retrieval
    mock_segments = [
        RoadSegment(
            segment_id="seg_001",
            name="Ring Road North",
            road_type="arterial",
            length_m=450.0,
            geometry=GeoJSONLineString(coordinates=[[77.21, 28.63], [77.22, 28.63]]),
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
        ),
        RoadSegment(
            segment_id="seg_002",
            name="Janpath Link",
            road_type="local",
            length_m=280.0,
            geometry=GeoJSONLineString(coordinates=[[77.215, 28.63], [77.215, 28.635]]),
            speed_limit_kmh=30.0,
            lanes=1,
            is_oneway=True,
        ),
    ]
    mock_metrics = RoadNetworkMetrics(
        total_segments=2,
        highway_count=0,
        arterial_count=1,
        local_count=1,
        total_length_km=0.73,
        road_density_km_per_km2=14.6,
        intersection_count=1,
        potential_bottleneck_count=1,
        area_km2=0.05,
        road_class_distribution={"Highway": 0, "Arterial": 1, "Local": 1},
    )
    mock_bottlenecks = [
        BottleneckCandidate(
            segment_id="seg_001",
            location_name="Ring Road North Junction",
            lat=28.63,
            lng=77.215,
            bottleneck_type="network_structural",
            severity="high",
            evidence=["High betweenness centrality: 0.22", "Intersection degree: 3"],
            centrality_score=0.22,
            speed_reduction=None,
        )
    ]
    mock_osm_coverage = DataSourceCoverage(source="osm", status="ok", message="Mocked 2 segments")

    monkeypatch.setattr(
        analysis_service,
        "fetch_road_network",
        AsyncMock(return_value=(None, mock_segments, mock_metrics, mock_bottlenecks, mock_osm_coverage)),
    )

    # Mock TomTom flow
    mock_obs = TrafficObservation(
        segment_id="seg_001",
        observed_speed_kmh=18.0,
        free_flow_speed_kmh=50.0,
        speed_reduction_ratio=0.64,
        congestion_level="severe",
        has_incident=False,
        source="tomtom",
    )
    monkeypatch.setattr(
        analysis_service,
        "fetch_flow_for_point",
        AsyncMock(return_value=(mock_obs, DataSourceCoverage(source="tomtom_flow", status="ok"))),
    )

    # Mock TomTom incidents
    monkeypatch.setattr(
        analysis_service,
        "fetch_incidents_for_bbox",
        AsyncMock(return_value=([], DataSourceCoverage(source="tomtom_incidents", status="ok"))),
    )

    # Mock Weather
    mock_weather = WeatherContext(
        temperature_c=31.5,
        condition="Clear Sky",
        precipitation_mm=0.0,
        wind_speed_kmh=8.5,
        source="openweather",
    )
    monkeypatch.setattr(
        analysis_service,
        "fetch_weather",
        AsyncMock(return_value=(mock_weather, DataSourceCoverage(source="openweather", status="ok"))),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. POST /api/analyses
        payload = {
            "polygon": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [77.210, 28.630],
                        [77.220, 28.630],
                        [77.220, 28.635],
                        [77.210, 28.635],
                        [77.210, 28.630],
                    ]
                ],
            }
        }
        resp = await ac.post("/api/analyses", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        analysis_id = data["analysis_id"]
        assert analysis_id is not None
        assert data["status"] == "completed"
        assert data["storage_mode"] in ("mongodb", "in_memory")
        assert data["road_network"]["total_segments"] == 2
        assert len(data["segments"]) == 2
        assert len(data["bottlenecks"]) >= 1

        # 2. GET /api/analyses/{id}
        resp_get = await ac.get(f"/api/analyses/{analysis_id}")
        assert resp_get.status_code == 200
        assert resp_get.json()["analysis_id"] == analysis_id

        # 3. GET /api/analyses/{id}/traffic-flow
        resp_tf = await ac.get(f"/api/analyses/{analysis_id}/traffic-flow")
        assert resp_tf.status_code == 200
        tf_data = resp_tf.json()
        assert tf_data["analysis_id"] == analysis_id
        assert "summary" in tf_data
        assert tf_data["summary"]["total_observed"] > 0

        # 4. GET /api/analyses/{id}/recommendations
        resp_rec = await ac.get(f"/api/analyses/{analysis_id}/recommendations")
        assert resp_rec.status_code == 200
        rec_data = resp_rec.json()
        assert rec_data["analysis_id"] == analysis_id
        assert len(rec_data["recommendations"]) > 0
        assert rec_data["recommendations"][0]["requires_engineering_review"] is True

        # 5. GET /api/analyses/{id}/export/geojson
        resp_geo = await ac.get(f"/api/analyses/{analysis_id}/export/geojson")
        assert resp_geo.status_code == 200
        assert resp_geo.headers["content-type"] == "application/geo+json"
        geojson = resp_geo.json()
        assert geojson["type"] == "FeatureCollection"
        types = {f["properties"]["feature_type"] for f in geojson["features"]}
        assert "boundary" in types
        assert "road_segment" in types
        assert "bottleneck" in types

