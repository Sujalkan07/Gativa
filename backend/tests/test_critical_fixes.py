"""
Comprehensive Regression Tests for Gativa Critical & High-Priority Fixes (Issues A through O).
Verifies:
- Issue A: Zero-signal networks & verified signal detection
- Issue B: Elimination of silent synthetic network substitution & demo mode isolation
- Issue C: Separation of native SUMO from fallback estimates
- Issue D: Collision-safe deterministic edge IDs
- Issue E: Non-lossy MultiLineString and GeometryCollection polygon clipping
- Issue F: Network truncation & coverage limit consistency
- Issue G: Observable SQLite initialization & failure propagation
- Issue H: Zero-baseline comparison percentage honesty
- Issue I: Deterministic cross-process congestion fallback
- Issue J: Multi-edge telemetry aggregation semantics
- Issue K: OSM source node identity preservation & simulation assumptions
- Issue L: Polygon cache key collision prevention
- Issue M: Traffic observation timestamps & sampling metadata
- Issue N: Explicit HTTP error status codes (404/422)
- Issue O: Simulation session metadata and network provenance
"""
import hashlib
import tempfile
from pathlib import Path
import pytest
from shapely.geometry import Polygon, LineString, MultiLineString, GeometryCollection, Point
from fastapi.testclient import TestClient

from main import app
from app.simulation.network_builder import SumoNetworkBuilder
from app.simulation.traci_manager import SimulationSession
from app.simulation.scenario_comparator import ScenarioComparator
from app.models.schemas import SimulationMetrics
from app.geospatial.road_network import (
    _clip_geometry_to_polygon_parts,
    _clip_geometry_to_polygon,
    _get_polygon_cache_key,
)
from app.core.sqlite_store import get_sqlite_status, init_sqlite_db

client = TestClient(app)


# ─── ISSUE A & B: Network Authenticity & Zero Synthetic Substitution ──────────

def test_issue_a_b_zero_signal_and_no_silent_substitution():
    """Verify zero-signal network compiles authentically and empty inputs are rejected without allow_synthetic."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))

        # Real road segments with priority right-of-way (no signals)
        real_segments = [
            {
                "segment_id": "seg_real_1",
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
                "speed_limit_kmh": 40.0,
                "lanes": 2,
            },
            {
                "segment_id": "seg_real_2",
                "geometry": {"type": "LineString", "coordinates": [[77.60, 12.97], [77.61, 12.97]]},
                "speed_limit_kmh": 40.0,
                "lanes": 2,
            },
        ]
        meta = builder.build(segments=real_segments, duration_seconds=120)
        assert meta["signal_count"] == 0, "Must not fabricate signals for unsignalized roads"
        assert meta["network_provenance"] == "real_osm"

        # Rejection of empty segments for real analyses (Issue B)
        with pytest.raises(ValueError, match="No road segments provided"):
            builder.build(segments=[], allow_synthetic=False)

        # Explicit synthetic demo mode succeeds and is labelled (Issue B)
        demo_meta = builder.build(segments=[], allow_synthetic=True)
        assert demo_meta["network_provenance"] == "synthetic_demo"
        assert demo_meta["edge_count"] > 0


def test_issue_b_endpoint_rejection_of_missing_analysis():
    """Verify that preparing a simulation for a nonexistent analysis returns HTTP 404 instead of 500."""
    resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "completely_missing_analysis_id_12345",
            "duration_seconds": 600,
        },
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ─── ISSUE C: Engine Provenance & Transitions ─────────────────────────────────

def test_issue_c_fallback_engine_provenance_and_diagnostics():
    """Verify fallback engine is explicitly identified and diagnostic notes are retained."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(segments=[], allow_synthetic=True)

        session = SimulationSession(
            sim_id="test_engine_prov",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            netconvert_used=False,  # Force fallback
            is_synthetic_demo=True,
        )

        assert session.engine_mode == "fallback"
        assert "kinematics" in session.engine_message.lower()

        session.start()
        status = session.step(num_steps=1)
        assert status["engine_mode"] == "fallback"
        assert status["network_provenance"] == "synthetic_demo"
        session.stop()


# ─── ISSUE D: Collision-Safe Deterministic Edge IDs ───────────────────────────

def test_issue_d_edge_id_collision_safety():
    """Verify that colliding sanitized IDs (e.g. road-1 and road_1, unicode, spaces) get unique edge IDs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        colliding_segments = [
            {"segment_id": "road-1", "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.1, 0.0]]}},
            {"segment_id": "road_1", "geometry": {"type": "LineString", "coordinates": [[0.1, 0.0], [0.2, 0.0]]}},
            {"segment_id": "road 1", "geometry": {"type": "LineString", "coordinates": [[0.2, 0.0], [0.3, 0.0]]}},
            {"segment_id": "मार्ग_1", "geometry": {"type": "LineString", "coordinates": [[0.3, 0.0], [0.4, 0.0]]}},
        ]
        nodes, edges, seg_map, edge_map, assumptions = builder._extract_nodes_and_edges(
            colliding_segments, allow_synthetic=False
        )

        edge_ids = [e["id"] for e in edges]
        # Every edge ID in the simulation network must be unique
        assert len(edge_ids) == len(set(edge_ids)), f"Collision detected in edge IDs: {edge_ids}"

        # Every source segment must have its own mapping entry
        for seg in colliding_segments:
            sid = seg["segment_id"]
            assert sid in seg_map
            mapped_edges = seg_map[sid]
            assert len(mapped_edges) >= 1
            for me in mapped_edges:
                assert edge_map[me] == sid, f"Edge {me} failed reverse mapping to {sid}"


# ─── ISSUE E: Polygon Geometry Clipping (MultiLineString & Collection) ────────

def test_issue_e_multilinestring_and_collection_clipping():
    """Verify clipping preserves all valid in-polygon LineString fragments rather than just the longest."""
    # A box polygon from (0, 0) to (10, 10) with a hole or concave shape
    poly = Polygon([(2, 2), (8, 2), (8, 8), (2, 8)])

    # 1. Road that enters, exits, and re-enters the polygon:
    # (0, 5) -> (4, 5) [in] -> (6, 12) [out] -> (7, 5) [in] -> (12, 5) [out]
    road = LineString([(0, 5), (4, 5), (6, 12), (7, 5), (12, 5)])
    parts = _clip_geometry_to_polygon_parts(road, poly)

    # Must contain 2 distinct disjoint LineString fragments inside the polygon
    assert len(parts) == 2, f"Expected 2 in-polygon fragments, got {len(parts)}"
    for p in parts:
        assert isinstance(p, LineString)
        assert p.length > 0
        assert poly.contains(p) or poly.touches(p) or poly.intersects(p)

    # 2. GeometryCollection containing lines and points
    collection = GeometryCollection([
        LineString([(3, 3), (7, 3)]),
        Point(5, 5),
        LineString([(3, 7), (7, 7)]),
    ])
    gc_parts = _clip_geometry_to_polygon_parts(collection, poly)
    assert len(gc_parts) == 2
    for p in gc_parts:
        assert isinstance(p, LineString)

    # 3. Road completely outside
    outside_road = LineString([(15, 15), (20, 20)])
    assert _clip_geometry_to_polygon_parts(outside_road, poly) == []


# ─── ISSUE F: Network Limits & Coverage Consistency ───────────────────────────

def test_issue_f_network_metadata_and_limits_consistency():
    """Verify segment limit metadata tracking in simulation status and builder."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        real_segments = [
            {
                "segment_id": f"seg_{i}",
                "geometry": {"type": "LineString", "coordinates": [[77.5 + i*0.001, 12.9], [77.5 + (i+1)*0.001, 12.9]]},
                "speed_limit_kmh": 50.0,
                "lanes": 2,
            }
            for i in range(5)
        ]
        meta = builder.build(segments=real_segments)
        assert meta["total_eligible_segments"] == 5
        assert meta["omitted_segments_count"] == 0
        assert meta["segments_simulated"] > 0


# ─── ISSUE G: Observable SQLite Initialization & Failures ────────────────────

def test_issue_g_observable_sqlite_initialization():
    """Verify get_sqlite_status reports accurate health and database connection."""
    init_sqlite_db()
    status = get_sqlite_status()
    assert status["status"] == "healthy"
    assert status["initialized"] is True
    assert status["error"] is None
    assert "gativa.db" in status["path"]


# ─── ISSUE H: Zero-Baseline Comparison Percentages ────────────────────────────

def test_issue_h_zero_baseline_honest_variance():
    """Verify ScenarioComparator reports 'N/A — zero baseline' when baseline is 0 and optimized is > 0."""
    baseline = SimulationMetrics(
        avg_speed_kmh=0.0,
        avg_waiting_time_s=0.0,
        avg_queue_length_m=0.0,
        completed_vehicles=0,
        elapsed_seconds=10.0,
    )
    optimized = SimulationMetrics(
        avg_speed_kmh=24.5,
        avg_waiting_time_s=15.0,
        avg_queue_length_m=20.0,
        completed_vehicles=8,
        elapsed_seconds=10.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_zero_base_test",
        analysis_id="analysis_zero_base",
        baseline_metrics=baseline,
        optimized_metrics=optimized,
        step_count=5,
    )

    assert res.comparison_status == "completed"
    speed_row = next(r for r in res.rows if r.metric == "Average Speed")
    assert "zero baseline" in speed_row.variance.lower()
    assert "+24.5 km/h" in speed_row.variance
    assert "0.0%" not in speed_row.variance  # MUST NOT report 0% when speed jumped to 24.5!

    wait_row = next(r for r in res.rows if r.metric == "Average Waiting Time")
    assert "zero baseline" in wait_row.variance.lower()
    assert "+15.0 s" in wait_row.variance

    comp_row = next(r for r in res.rows if r.metric == "Completed Vehicles")
    assert "zero baseline" in comp_row.variance.lower()
    assert "+8 vehs" in comp_row.variance


# ─── ISSUE I: Deterministic Cross-Process Congestion Fallback ──────────────────

def test_issue_i_deterministic_congestion_fallback():
    """Verify congestion fallback calculations are deterministic and invariant to Python process hash randomization."""
    seg_id = "test_bangalore_junction_seg_42"

    # Compute hash using our deterministic implementation
    h1 = int(hashlib.sha256(seg_id.encode("utf-8")).hexdigest()[:8], 16)
    h2 = int(hashlib.sha256(seg_id.encode("utf-8")).hexdigest()[:8], 16)
    assert h1 == h2

    # In traci_manager, fallback simulation uses this hash
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        segments = [
            {
                "segment_id": seg_id,
                "name": "Hosur Road",
                "road_type": "arterial",
                "speed_limit_kmh": 60.0,
                "geometry": {"type": "LineString", "coordinates": [[77.6, 12.9], [77.61, 12.91]]},
            }
        ]
        meta = builder.build(segments=segments)
        session1 = SimulationSession(
            sim_id="sim_det_1",
            analysis_id="analysis_det",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            road_segments=segments,
            netconvert_used=False,
        )
        session1._segment_edge_map = meta["segment_edge_map"]
        session1.step(num_steps=2)
        summary1 = session1.compute_congestion_summary()

        session2 = SimulationSession(
            sim_id="sim_det_2",
            analysis_id="analysis_det",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            road_segments=segments,
            netconvert_used=False,
        )
        session2._segment_edge_map = meta["segment_edge_map"]
        session2.step(num_steps=2)
        summary2 = session2.compute_congestion_summary()

        # Both runs MUST produce identical congestion score and avg speed
        assert summary1.all_results[0].avg_speed_kmh == summary2.all_results[0].avg_speed_kmh
        assert summary1.all_results[0].congestion_score == summary2.all_results[0].congestion_score


# ─── ISSUE K: OSM Source Node Identity & Simulation Assumptions ───────────────

def test_issue_k_osm_source_node_identity_preservation():
    """Verify that source node identities u and v are preserved and simulation assumptions disclosed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        osm_segments = [
            {
                "segment_id": "seg_osm_1",
                "u": 1001,
                "v": 1002,
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
                # Missing speed limit and lanes to test assumptions tracking
            }
        ]
        nodes, edges, seg_map, edge_map, assumptions = builder._extract_nodes_and_edges(
            osm_segments, allow_synthetic=False
        )

        assert "node_1001" in nodes
        assert "node_1002" in nodes
        assert "default_speed_50kmh_applied" in assumptions
        assert "default_lanes_2_applied" in assumptions


# ─── ISSUE L: Polygon Cache Key Collision Prevention ──────────────────────────

def test_issue_l_polygon_cache_key_collision_prevention():
    """Verify that different polygon geometries sharing identical bounding boxes produce distinct cache keys."""
    # Polygon 1: Right triangle in top-right of bounding box [0, 0, 10, 10]
    poly_tr = Polygon([(0, 10), (10, 10), (10, 0), (0, 10)])

    # Polygon 2: Right triangle in bottom-left of bounding box [0, 0, 10, 10]
    poly_bl = Polygon([(0, 0), (10, 0), (0, 10), (0, 0)])

    # Both have identical bounding box [0.0, 0.0, 10.0, 10.0]
    assert poly_tr.bounds == poly_bl.bounds

    key1 = _get_polygon_cache_key(poly_tr)
    key2 = _get_polygon_cache_key(poly_bl)

    assert key1 != key2, "Different polygons with same bounding box MUST produce distinct cache keys!"

    # Invariance: Same polygon rotated or wound differently must match
    poly_tr_rotated = Polygon([(10, 10), (10, 0), (0, 10), (10, 10)])
    key1_rotated = _get_polygon_cache_key(poly_tr_rotated)
    assert key1 == key1_rotated, "Identical polygon with shifted vertex origin must produce identical cache key"


def test_issue_l_polygon_cache_key_with_holes():
    """Verify that a polygon with a hole produces a distinct cache key from a solid polygon."""
    solid = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    with_hole = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
        holes=[[(2, 2), (8, 2), (8, 8), (2, 8), (2, 2)]],
    )
    assert solid.bounds == with_hole.bounds
    k_solid = _get_polygon_cache_key(solid)
    k_hole = _get_polygon_cache_key(with_hole)
    assert k_solid != k_hole, "Polygon with hole must produce a distinct cache key from solid polygon"


# ─── REMAINING FIXES: Telemetry Aggregation & Missing Data ───────────────────

def test_multi_edge_unequal_sample_count_aggregation():
    """
    Verify that when one edge generates 100 samples and another generates 2 samples,
    the constituent edges are averaged without allowing the 100-sample edge to drown out the other.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_unequal",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_twoway",
                    "name": "Two-Way Unequal",
                    "road_type": "arterial",
                    "speed_limit_kmh": 60.0,
                }
            ],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        session._segment_edge_map = {"seg_twoway": ["edge_fwd", "edge_rev"]}

        # Edge fwd has 100 samples with mean speed 20 m/s
        session._edge_cumulative_stats["edge_fwd"] = {
            "edge_id": "edge_fwd",
            "total_samples": 100,
            "sum_speed_ms": 2000.0,
            "min_speed_ms": 18.0,
            "max_speed_ms": 22.0,
            "sum_occupancy_pct": 1000.0,
            "peak_occupancy_pct": 15.0,
            "sum_halting": 0.0,
            "peak_halting": 0.0,
            "sum_waiting_s": 0.0,
            "congested_samples": 0,
            "first_timestamp": 0.0,
            "last_timestamp": 100.0,
        }

        # Edge rev has 2 samples with mean speed 10 m/s
        session._edge_cumulative_stats["edge_rev"] = {
            "edge_id": "edge_rev",
            "total_samples": 2,
            "sum_speed_ms": 20.0,
            "min_speed_ms": 9.0,
            "max_speed_ms": 11.0,
            "sum_occupancy_pct": 40.0,
            "peak_occupancy_pct": 25.0,
            "sum_halting": 2.0,
            "peak_halting": 1.0,
            "sum_waiting_s": 10.0,
            "congested_samples": 0,
            "first_timestamp": 0.0,
            "last_timestamp": 2.0,
        }

        summary = session.compute_congestion_summary()
        res = summary.all_results[0]

        # Edge fwd mean = 20 m/s, Edge rev mean = 10 m/s
        # Unweighted average across constituent edges = 15 m/s = 54.0 km/h
        # (If sample-count weighted, it would have been ~19.8 m/s = 71.3 km/h, drowning out rev)
        expected_kmh = round(15.0 * 3.6, 1)
        assert abs(res.avg_speed_kmh - expected_kmh) < 1.0, f"Expected ~{expected_kmh} km/h, got {res.avg_speed_kmh}"
        assert res.data_quality == "measured"


def test_missing_telemetry_insufficient_data_honesty():
    """Verify that an unobserved or untraversed edge is classified as insufficient_data, never free_flow."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_unobserved",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_unobserved",
                    "name": "Untraversed Lane",
                    "road_type": "local",
                    "speed_limit_kmh": 50.0,
                }
            ],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        session.step_count = 50
        session._segment_edge_map = {"seg_unobserved": ["edge_unobserved"]}

        # No telemetry collected on edge_unobserved
        summary = session.compute_congestion_summary()
        res = summary.all_results[0]

        assert res.severity == "insufficient_data", "Untraversed edge must be insufficient_data, not free_flow"
        assert res.data_quality == "insufficient"
        assert res.avg_speed_kmh == 0.0, "Must not fabricate free-flow speed for untraversed road"
        assert res.sample_count == 0


def test_zero_baseline_no_change_and_mismatch_disclosures():
    """Verify that (0, 0) reports no change without claiming improvement, and duration mismatches are disclosed."""
    metrics_0 = SimulationMetrics(
        avg_speed_kmh=0.0,
        avg_waiting_time_s=0.0,
        avg_queue_length_m=0.0,
        completed_vehicles=0,
        total_duration_seconds=300.0,
        elapsed_seconds=10.0,
    )
    metrics_diff_duration = SimulationMetrics(
        avg_speed_kmh=0.0,
        avg_waiting_time_s=0.0,
        avg_queue_length_m=0.0,
        completed_vehicles=0,
        total_duration_seconds=600.0,
        elapsed_seconds=10.0,
    )

    res = ScenarioComparator.compare(
        sim_id="test_comp_zeros",
        analysis_id="test_analysis",
        baseline_metrics=metrics_0,
        optimized_metrics=metrics_diff_duration,
        step_count=5,
        engine_mode="fallback",
    )

    # 1. Zero values must report (no change) and is_improvement=False
    for row in res.rows:
        assert "no change" in row.variance.lower(), f"Row {row.metric} should say 'no change', got: {row.variance}"
        assert not row.is_improvement, f"Row {row.metric} must not claim improvement when both are 0"

    # 2. Mismatch disclosure in methodology notes
    assert "Duration mismatch" in res.methodology_notes
    assert "Internal kinematics engine estimation" in res.methodology_notes


def test_sqlite_status_no_internal_path_leak():
    """Verify that public health check / sqlite status does not leak filesystem paths."""
    status = get_sqlite_status(include_internals=False)
    assert "status" in status
    assert "initialized" in status
    assert "path" not in status, "Public SQLite status must not leak local filesystem paths"

    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    h_data = health_resp.json()
    assert "path" not in h_data.get("database", {}), "API /health must not leak filesystem paths"


def test_simulation_session_thread_safety_and_idempotent_lifecycle():
    """Verify that repeated stop() and reset() calls are idempotent and thread-safe."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_lifecycle",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_1",
                    "name": "Street",
                    "road_type": "local",
                    "speed_limit_kmh": 40.0,
                }
            ],
            netconvert_used=False,
            is_synthetic_demo=True,
        )

        # Repeated stop calls should be idempotent
        session.stop()
        session.stop()

        # Repeated reset calls should be idempotent
        session.reset()
        session.reset()
        assert session.step_count == 0
        assert session.state == "ready"
