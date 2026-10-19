"""
Comprehensive Test Suite for SUMO Signal Authenticity, Zero-Signal Corridors,
Telemetry Accumulation, and Scenario Comparison Integrity.
"""
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import pytest

from app.simulation.network_builder import SumoNetworkBuilder, find_sumo_binary
from app.simulation.traci_manager import SimulationSession
from app.simulation.scenario_comparator import ScenarioComparator
from app.models.schemas import SimulationMetrics, RoadSegment, GeoJSONLineString


def test_zero_signal_network_construction():
    """Verify that road segments without signals produce a genuine zero-signal network (signal_count = 0)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        # 3 connecting segments forming a T-junction (degree 3) without any signal tags
        segments = [
            {
                "segment_id": "seg_1",
                "name": "Road West",
                "geometry": {"coordinates": [[80.9300, 26.8900], [80.9400, 26.8900]]},
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
                "u_control": "priority",
                "v_control": "priority",
                "u_provenance": "unknown",
                "v_provenance": "unknown",
            },
            {
                "segment_id": "seg_2",
                "name": "Road East",
                "geometry": {"coordinates": [[80.9400, 26.8900], [80.9500, 26.8900]]},
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
                "u_control": "priority",
                "v_control": "priority",
                "u_provenance": "unknown",
                "v_provenance": "unknown",
            },
            {
                "segment_id": "seg_3",
                "name": "Road North",
                "geometry": {"coordinates": [[80.9400, 26.8900], [80.9400, 26.9000]]},
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
                "u_control": "priority",
                "v_control": "priority",
                "u_provenance": "unknown",
                "v_provenance": "unknown",
            },
        ]

        meta = builder.build(segments=segments, duration_seconds=120)

        # 1. Authentic signal count must be strictly 0
        assert meta["signal_count"] == 0, f"Expected 0 signals for unsignalized corridor, got {meta['signal_count']}"

        # 2. Inspect nodes.nod.xml - NO node should have type='traffic_light'
        nod_file = Path(tmp_dir) / "nodes.nod.xml"
        assert nod_file.is_file()
        tree = ET.parse(str(nod_file))
        for node in tree.findall("node"):
            assert node.get("type") != "traffic_light", f"Node {node.get('id')} was falsely typed as traffic_light"
            assert node.get("type") in ("priority", "priority_stop", "roundabout")

        # 3. SUMO network file must exist and be valid
        assert Path(meta["net_file"]).is_file()


def test_no_degree_based_signal_fabrication():
    """Verify that degree >= 3 or degree >= 4 junctions are NOT converted into traffic lights."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        # 4-way cross junction centered on (80.9400, 26.8900)
        center = [80.9400, 26.8900]
        segments = [
            {"segment_id": "w", "geometry": {"coordinates": [[80.9300, 26.8900], center]}, "lanes": 2},
            {"segment_id": "e", "geometry": {"coordinates": [center, [80.9500, 26.8900]]}, "lanes": 2},
            {"segment_id": "s", "geometry": {"coordinates": [[80.9400, 26.8800], center]}, "lanes": 2},
            {"segment_id": "n", "geometry": {"coordinates": [center, [80.9400, 26.9000]]}, "lanes": 2},
        ]

        meta = builder.build(segments=segments, duration_seconds=60)
        assert meta["signal_count"] == 0, "4-way intersection without signal metadata must NOT be classified as traffic light"


def test_verified_signal_detection():
    """Verify that genuine signal metadata (u_control='traffic_signal') compiles into a verified traffic light."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        center = [80.9400, 26.8900]
        segments = [
            {
                "segment_id": "seg_sig_w",
                "geometry": {"coordinates": [[80.9300, 26.8900], center]},
                "lanes": 2,
                "v_control": "traffic_signal",
                "v_provenance": "source_verified",
            },
            {
                "segment_id": "seg_sig_e",
                "geometry": {"coordinates": [center, [80.9500, 26.8900]]},
                "lanes": 2,
                "u_control": "traffic_signal",
                "u_provenance": "source_verified",
            },
        ]

        meta = builder.build(segments=segments, duration_seconds=60)
        assert meta["signal_count"] == 1, f"Expected 1 verified signal, got {meta['signal_count']}"

        nod_file = Path(tmp_dir) / "nodes.nod.xml"
        tree = ET.parse(str(nod_file))
        tl_nodes = [n for n in tree.findall("node") if n.get("type") == "traffic_light"]
        assert len(tl_nodes) == 1


def test_fallback_simulation_zero_signals_honesty():
    """Verify that fallback kinematics simulation returns empty traffic_lights when signal_count is 0."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        segments = [
            {
                "segment_id": "s1",
                "name": "Plain Corridor",
                "geometry": {"coordinates": [[80.9400, 26.8900], [80.9500, 26.8900]]},
                "speed_limit_kmh": 40,
                "lanes": 1,
                "is_oneway": False,
            }
        ]
        meta = builder.build(segments=segments, duration_seconds=60)
        assert meta["signal_count"] == 0

        session = SimulationSession(
            sim_id="sim_zero_sig_test",
            analysis_id="analysis_zero_sig",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=60,
            demand_rate_veh_hr=1200,
            strategy="fixed_time",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=0,
            road_segments=segments,
            netconvert_used=False,  # force fallback kinematics
        )

        try:
            session.start()
            status = session.step(num_steps=3)
            # Must NOT fabricate phantom signals like TL_fallback_1
            assert status["signal_count"] == 0
            assert status["traffic_lights"] == []
            assert len(status["vehicles"]) > 0
        finally:
            session.stop()


def test_cumulative_whole_run_telemetry():
    """Verify that congestion analysis aggregates telemetry across > 60 steps via _edge_cumulative_stats."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(segments=[], duration_seconds=300)

        session = SimulationSession(
            sim_id="sim_cum_telemetry_test",
            analysis_id="analysis_cum_test",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=300,
            demand_rate_veh_hr=2000,
            strategy="actuated_adaptive",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
            road_segments=builder._default_corridor_segments(),
            netconvert_used=False,
        )

        try:
            session.start()
            # Step 70 times (each step = 1 step, total 70 steps > 60)
            for _ in range(70):
                session.step(num_steps=1)

            assert session.step_count == 70

            # Verify _edge_cumulative_stats tracked all 70 steps
            for edge_id, st in session._edge_cumulative_stats.items():
                assert st["total_samples"] >= 70, f"Expected >= 70 samples for edge {edge_id}, got {st['total_samples']}"

            # Compute congestion summary
            summary = session.compute_congestion_summary()
            assert summary.total_roads > 0
            assert summary.roads_analyzed > 0

            # Verify each analyzed road has sample_count reflecting the full run (> 60)
            for r in summary.all_results:
                if r.data_quality in ("measured", "estimated"):
                    assert r.sample_count >= 70, f"Expected full-run sample count >= 70, got {r.sample_count}"

            # Verify methodology notes mentions whole-run cumulative telemetry
            assert "Whole-run cumulative telemetry aggregation" in summary.methodology_notes
        finally:
            session.stop()


def test_scenario_comparator_zero_signals_honesty():
    """Verify that ScenarioComparator clearly reports unsignalized priority rules when signal_count is 0."""
    baseline_metrics = SimulationMetrics(
        avg_speed_kmh=24.5,
        avg_waiting_time_s=14.2,
        avg_queue_length_m=18.0,
        completed_vehicles=85,
        active_vehicles=12,
        elapsed_seconds=120.0,
        total_duration_seconds=600.0,
    )
    optimized_metrics = SimulationMetrics(
        avg_speed_kmh=25.1,
        avg_waiting_time_s=13.8,
        avg_queue_length_m=16.5,
        completed_vehicles=88,
        active_vehicles=11,
        elapsed_seconds=120.0,
        total_duration_seconds=600.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_comp_zero_sig",
        analysis_id="analysis_zero_sig",
        duration_seconds=600,
        engine_mode="fallback",
        baseline_metrics=baseline_metrics,
        optimized_metrics=optimized_metrics,
        step_count=60,
        signal_count=0,
    )

    assert res.comparison_status == "completed"
    assert "Unsignalized" in res.baseline_strategy
    assert "Unsignalized" in res.optimized_strategy
    assert "0 traffic signal controllers" in res.methodology_notes
    assert "priority right-of-way rules" in res.methodology_notes
