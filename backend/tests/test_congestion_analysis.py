"""
Unit tests for Post-Simulation Road-Level Congestion Analysis.
Tests:
- Edge telemetry collection and data structure validation
- Congestion scoring formula correctness and boundary conditions
- Severity threshold classifications (free_flow, low, moderate, high, severe, insufficient_data)
- Insufficient samples handling (< MIN_SAMPLES = 3)
- Fallback mode honest disclosure (data_quality='estimated', engine_mode='fallback')
- Multi-edge segment mapping (forward and reverse edges)
- SQLite persistence and retrieval of congestion summaries
- GET /api/simulations/{sim_id}/congestion API endpoint response
"""
import pytest
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient

from main import app
from app.models.schemas import CongestionRoadResult, CongestionSummary
from app.simulation.traci_manager import SimulationSession
from app.simulation.network_builder import SumoNetworkBuilder, MAX_SEGMENTS
from app.core.sqlite_store import save_congestion_summary_sync, get_congestion_summary_sync
from app.simulation.service import simulation_service

client = TestClient(app)


def test_congestion_scoring_formula_and_thresholds():
    """Verify congestion scoring formula matches the documented specification across all severity bands."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_scoring",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_free_flow",
                    "name": "Expressway Free Flow",
                    "road_type": "highway",
                    "speed_limit_kmh": 100.0,
                    "geometry": {"coordinates": [[80.9, 26.8], [80.91, 26.81]]},
                },
                {
                    "segment_id": "seg_severe",
                    "name": "Choked Junction Approach",
                    "road_type": "arterial",
                    "speed_limit_kmh": 50.0,
                    "geometry": {"coordinates": [[80.92, 26.82], [80.93, 26.83]]},
                },
            ],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        session._segment_edge_map = {
            "seg_free_flow": ["edge_ff_0"],
            "seg_severe": ["edge_sev_0"],
        }

        # Simulate free-flow telemetry: 100 km/h (27.78 m/s), 5% occupancy, 0 halting
        session._edge_telemetry["edge_ff_0"] = [
            {
                "edge_id": "edge_ff_0",
                "timestamp": float(t),
                "mean_speed_ms": 27.78,
                "vehicle_count": 5,
                "occupancy_pct": 5.0,
                "halting_vehicles": 0,
                "waiting_time_s": 0.0,
            }
            for t in range(5, 50, 5)
        ]

        # Simulate severe congestion: 3 km/h (0.83 m/s), 90% occupancy, 12 halting
        session._edge_telemetry["edge_sev_0"] = [
            {
                "edge_id": "edge_sev_0",
                "timestamp": float(t),
                "mean_speed_ms": 0.83,
                "vehicle_count": 25,
                "occupancy_pct": 90.0,
                "halting_vehicles": 12,
                "waiting_time_s": 75.0,
            }
            for t in range(5, 50, 5)
        ]

        summary = session.compute_congestion_summary()
        assert summary.total_roads == 2
        assert summary.roads_analyzed == 2
        assert summary.roads_insufficient == 0

        res_map = {r.segment_id: r for r in summary.all_results}

        # 1. Free flow segment
        ff = res_map["seg_free_flow"]
        assert ff.severity == "free_flow"
        assert ff.congestion_score < 0.20
        assert ff.data_quality == "measured"
        assert ff.engine_mode == "native_sumo"

        # 2. Severe segment
        sev = res_map["seg_severe"]
        assert sev.severity == "severe"
        assert sev.congestion_score >= 0.80
        assert sev.data_quality == "measured"
        assert sev.congested_pct > 0


def test_one_direction_blockage_colors_the_full_road_congested():
    """An empty reverse direction must not dilute a sustained forward queue."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_directional_blockage",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            road_segments=[{
                "segment_id": "seg_blocked",
                "name": "Blocked arterial",
                "road_type": "arterial",
                "speed_limit_kmh": 50.0,
                "geometry": {"coordinates": [[80.9, 26.8], [80.91, 26.81]]},
            }],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        session._segment_edge_map = {"seg_blocked": ["edge_forward", "edge_reverse"]}
        session._edge_telemetry["edge_forward"] = [
            {"edge_id": "edge_forward", "timestamp": float(t), "mean_speed_ms": 0.5,
             "vehicle_count": 14, "occupancy_pct": 92.0, "halting_vehicles": 12,
             "waiting_time_s": 60.0}
            for t in range(8)
        ]
        session._edge_telemetry["edge_reverse"] = [
            {"edge_id": "edge_reverse", "timestamp": float(t), "mean_speed_ms": 0.0,
             "vehicle_count": 0, "occupancy_pct": 0.0, "halting_vehicles": 0,
             "waiting_time_s": 0.0}
            for t in range(8)
        ]

        result = session.compute_congestion_summary().all_results[0]
        assert result.severity == "severe"
        assert result.congestion_score >= 0.80
        assert result.congested_pct == 100.0


def test_insufficient_samples_handling():
    """Verify edges with fewer than 3 samples receive insufficient_data classification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_insufficient",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_barely_sampled",
                    "name": "Side Alley",
                    "road_type": "local",
                    "speed_limit_kmh": 30.0,
                }
            ],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        session._segment_edge_map = {"seg_barely_sampled": ["edge_alley"]}

        # Only 2 observations (fewer than MIN_SAMPLES = 3)
        session._edge_telemetry["edge_alley"] = [
            {
                "edge_id": "edge_alley",
                "timestamp": 5.0,
                "mean_speed_ms": 8.0,
                "vehicle_count": 1,
                "occupancy_pct": 2.0,
                "halting_vehicles": 0,
                "waiting_time_s": 0.0,
            },
            {
                "edge_id": "edge_alley",
                "timestamp": 10.0,
                "mean_speed_ms": 7.5,
                "vehicle_count": 1,
                "occupancy_pct": 2.5,
                "halting_vehicles": 0,
                "waiting_time_s": 0.0,
            },
        ]

        summary = session.compute_congestion_summary()
        assert summary.roads_insufficient == 1
        assert summary.roads_analyzed == 0
        res = summary.all_results[0]
        assert res.severity == "insufficient_data"
        assert res.data_quality == "insufficient"
        assert res.sample_count == 2


def test_fallback_mode_honest_disclosure():
    """Verify that fallback mode marks results as 'estimated', never 'measured', and discloses in notes."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_fallback",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_poly_main_w",
                    "name": "Arterial West",
                    "road_type": "arterial",
                    "speed_limit_kmh": 50.0,
                }
            ],
            netconvert_used=False,
        )
        assert session.engine_mode == "fallback"
        session._segment_edge_map = {"seg_poly_main_w": ["seg_poly_main_w", "seg_poly_main_w_rev"]}

        # Advance fallback simulation steps
        session.step(num_steps=10)
        assert session.step_count == 10

        summary = session.compute_congestion_summary()
        assert summary.engine_mode == "fallback"
        assert "Fallback engine active" in summary.methodology_notes
        assert len(summary.all_results) > 0

        res = summary.all_results[0]
        # Must be explicitly 'estimated', NEVER 'measured'
        assert res.data_quality == "estimated"
        assert res.engine_mode == "fallback"


def test_segment_edge_map_multi_edge_aggregation():
    """Verify two-way road segments combine telemetry from forward and reverse edges."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        session = SimulationSession(
            sim_id="test_sim_bidir",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(tmp_dir) / "sim.sumocfg",
            duration_seconds=600,
            road_segments=[
                {
                    "segment_id": "seg_bidirectional",
                    "name": "Two-Way Avenue",
                    "road_type": "arterial",
                    "speed_limit_kmh": 60.0,
                    "is_oneway": False,
                }
            ],
            netconvert_used=True,
        )
        session.engine_mode = "native_sumo"
        # Bidirectional segment has two SUMO edges
        session._segment_edge_map = {
            "seg_bidirectional": ["edge_fwd", "edge_fwd_rev"]
        }

        # Samples on forward edge
        session._edge_telemetry["edge_fwd"] = [
            {"edge_id": "edge_fwd", "timestamp": 5.0, "mean_speed_ms": 15.0, "vehicle_count": 3, "occupancy_pct": 10.0, "halting_vehicles": 0, "waiting_time_s": 0.0},
            {"edge_id": "edge_fwd", "timestamp": 10.0, "mean_speed_ms": 14.0, "vehicle_count": 4, "occupancy_pct": 12.0, "halting_vehicles": 1, "waiting_time_s": 2.0},
        ]
        # Samples on reverse edge
        session._edge_telemetry["edge_fwd_rev"] = [
            {"edge_id": "edge_fwd_rev", "timestamp": 5.0, "mean_speed_ms": 16.0, "vehicle_count": 2, "occupancy_pct": 8.0, "halting_vehicles": 0, "waiting_time_s": 0.0},
            {"edge_id": "edge_fwd_rev", "timestamp": 10.0, "mean_speed_ms": 15.0, "vehicle_count": 3, "occupancy_pct": 9.0, "halting_vehicles": 0, "waiting_time_s": 0.0},
        ]

        summary = session.compute_congestion_summary()
        res = summary.all_results[0]
        # Combined sample count must be 2 + 2 = 4 (satisfies MIN_SAMPLES=3)
        assert res.sample_count == 4
        assert res.data_quality == "measured"
        assert res.avg_speed_kmh > 0


def test_sqlite_congestion_store():
    """Verify sqlite persistence and retrieval of congestion summary."""
    sim_id = "test_persist_sim_123"
    payload = {
        "sim_id": sim_id,
        "analysis_id": "test_analysis",
        "engine_mode": "native_sumo",
        "completed_at": "2026-10-19T12:00:00Z",
        "total_roads": 5,
        "roads_analyzed": 5,
        "roads_insufficient": 0,
        "top_congested": [],
        "all_results": [],
        "methodology_notes": "Test notes",
    }

    save_congestion_summary_sync(sim_id, payload)
    retrieved = get_congestion_summary_sync(sim_id)
    assert retrieved is not None
    assert retrieved["sim_id"] == sim_id
    assert retrieved["total_roads"] == 5
    assert retrieved["engine_mode"] == "native_sumo"


def test_max_segments_truncation_warning(caplog):
    """Verify that network builder warns when segments exceed MAX_SEGMENTS limit."""
    import logging
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        # Create MAX_SEGMENTS + 10 dummy segments
        excess_segments = [
            {
                "segment_id": f"seg_test_{i}",
                "name": f"Road {i}",
                "road_type": "arterial",
                "geometry": {"coordinates": [[80.9 + i*0.001, 26.8], [80.9 + (i+1)*0.001, 26.8]]},
            }
            for i in range(MAX_SEGMENTS + 10)
        ]

        with caplog.at_level(logging.WARNING):
            builder._extract_nodes_and_edges(excess_segments)

        assert any("exceeds MAX_SEGMENTS" in record.message for record in caplog.records)


def test_api_congestion_endpoint_404_for_unknown():
    """Verify that GET /api/simulations/{unknown_id}/congestion returns 404."""
    response = client.get("/api/simulations/non_existent_sim_99999/congestion")
    assert response.status_code == 404


def test_native_sumo_end_to_end_congestion_analysis():
    """Verify that a native SUMO simulation compiles, steps, collects edge telemetry, and computes measured congestion."""
    from app.simulation.network_builder import find_sumo_binary
    if not find_sumo_binary("sumo") or not find_sumo_binary("netconvert"):
        pytest.skip("SUMO binaries not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build([], duration_seconds=60, allow_synthetic=True)
        session = SimulationSession(
            sim_id="test_native_e2e",
            analysis_id="test_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=60,
            netconvert_used=meta["netconvert_used"],
            is_synthetic_demo=True,
        )
        session._segment_edge_map = meta["segment_edge_map"]
        try:
            session.start()
            assert session.engine_mode == "native_sumo"
            for _ in range(5):
                session.step(num_steps=5)

            assert len(session._edge_telemetry) > 0
            summary = session.compute_congestion_summary()
            assert summary.engine_mode == "native_sumo"
            assert summary.roads_analyzed > 0
            assert len(summary.top_congested) > 0
            top = summary.top_congested[0]
            assert top.data_quality == "measured"
            assert top.avg_speed_kmh > 0
            assert top.severity in ("free_flow", "low", "moderate", "high", "severe")
        finally:
            session.stop()
