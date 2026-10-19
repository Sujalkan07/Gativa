"""
Unit and integration tests for GIS data accuracy, geodesic calculations,
road classification, boundary clipping, edge deduplication, centrality percentile rank,
and SQLite persistence.
"""
import pytest
import networkx as nx
from shapely.geometry import Polygon, LineString, box

from app.geospatial.road_network import (
    _compute_geodesic_area_km2,
    _compute_geodesic_length_m,
    _clip_geometry_to_polygon,
    _classify_road,
    _detect_structural_bottlenecks,
    ROAD_CLASS_MAP,
)
from app.core.sqlite_store import (
    save_analysis_sync,
    get_analysis_sync,
    save_traffic_flow_sync,
    get_traffic_flow_sync,
    save_osm_cache_sync,
    get_osm_cache_sync,
)


def test_geodesic_polygon_area():
    """Verify that WGS84 ellipsoidal area is mathematically positive and accurate."""
    # Approx 0.02 x 0.02 degree box near Lucknow (lat ~26.9, lon ~80.9)
    poly = box(80.93, 26.90, 80.95, 26.92)
    area = _compute_geodesic_area_km2(poly)
    assert 4.0 < area < 5.0, f"Expected ~4.4 km², got {area}"


def test_geodesic_line_length():
    """Verify that WGS84 geodesic length for a known coordinate line is accurate."""
    # 0.01 deg longitudinal line at lat 26.90 is ~993 meters
    line = LineString([[80.93, 26.90], [80.94, 26.90]])
    length = _compute_geodesic_length_m(line)
    assert 980.0 < length < 1010.0, f"Expected ~993m, got {length}"


def test_road_classification_hierarchy():
    """Verify that arterial spines (primary, secondary, tertiary) and highways are accurately classified."""
    # Highways
    assert _classify_road("motorway") == "highway"
    assert _classify_road("motorway_link") == "highway"
    assert _classify_road("trunk") == "highway"
    assert _classify_road("trunk_link") == "highway"

    # Arterials (Critical fix: tertiary & tertiary_link must be arterial, not local)
    assert _classify_road("primary") == "arterial"
    assert _classify_road("primary_link") == "arterial"
    assert _classify_road("secondary") == "arterial"
    assert _classify_road("secondary_link") == "arterial"
    assert _classify_road("tertiary") == "arterial"
    assert _classify_road("tertiary_link") == "arterial"

    # Local & Service
    assert _classify_road("residential") == "local"
    assert _classify_road("living_street") == "local"
    assert _classify_road("service") == "local"
    assert _classify_road("unclassified") == "local"

    # List tag handling: prioritize highest level functional class
    assert _classify_road(["residential", "tertiary"]) == "arterial"
    assert _classify_road(["secondary", "trunk"]) == "highway"


def test_boundary_clipping():
    """Verify that geometries extending outside boundaries are clipped strictly inside."""
    boundary = box(0.0, 0.0, 10.0, 10.0)

    # Line straddling the boundary: from (-5, 5) to (15, 5)
    line_crossing = LineString([[-5.0, 5.0], [15.0, 5.0]])
    clipped = _clip_geometry_to_polygon(line_crossing, boundary)
    assert clipped is not None
    assert clipped.geom_type == "LineString"
    coords = list(clipped.coords)
    assert coords[0] == (0.0, 5.0)
    assert coords[-1] == (10.0, 5.0)

    # Line completely outside
    line_outside = LineString([[15.0, 15.0], [20.0, 20.0]])
    assert _clip_geometry_to_polygon(line_outside, boundary) is None


def test_centrality_percentile_rank_formula():
    """Verify that betweenness centrality ranks are calculated as Top X%, never top 100%."""
    # Create star network with high centrality hub node
    G = nx.MultiDiGraph()
    G.add_node(0, x=80.94, y=26.91)
    for i in range(1, 10):
        G.add_node(i, x=80.94 + i * 0.001, y=26.91 + i * 0.001)
        G.add_edge(0, i, 0, name=f"Street {i}")
        G.add_edge(i, 0, 0, name=f"Street {i}")

    bottlenecks = _detect_structural_bottlenecks(G, locality="Test")
    assert len(bottlenecks) > 0

    top_bn = bottlenecks[0]
    # Check evidence strings
    found_percentile = False
    for ev in top_bn.evidence:
        if "Betweenness centrality score:" in ev:
            found_percentile = True
            # Must NOT contain "top 100%"
            assert "top 100%" not in ev, f"Found defective percentile calculation: {ev}"
            assert "Top 1%" in ev or "Top " in ev, f"Expected 'Top X% of network nodes', got: {ev}"

    assert found_percentile, "Did not find centrality evidence string in bottleneck candidate"


def test_sqlite_persistence_roundtrip():
    """Verify that SQLite persistent store saves and retrieves analyses and OSM caches."""
    test_id = "test_analysis_sqlite_001"
    payload = {
        "analysis_id": test_id,
        "status": "completed",
        "area_km2": 4.5,
        "storage_mode": "sqlite",
    }
    save_analysis_sync(test_id, payload)
    loaded = get_analysis_sync(test_id)
    assert loaded is not None
    assert loaded["analysis_id"] == test_id
    assert loaded["storage_mode"] == "sqlite"

    # Traffic flow roundtrip
    tf_payload = {
        "analysis_id": test_id,
        "segments": [{"segment_id": "seg_1", "speed": 45}],
    }
    save_traffic_flow_sync(test_id, tf_payload)
    loaded_tf = get_traffic_flow_sync(test_id)
    assert loaded_tf is not None
    assert loaded_tf["analysis_id"] == test_id

    # OSM spatial cache roundtrip
    cache_key = "test_bbox_cache_001"
    sample_xml = "<osm version='0.6'></osm>"
    save_osm_cache_sync(cache_key, sample_xml, {"nodes": 12, "edges": 15})
    cached_xml, meta = get_osm_cache_sync(cache_key)
    assert cached_xml == sample_xml
    assert meta["nodes"] == 12
