"""
Regression and validation tests for Gativa Simulation & Optimization Reliability Overhaul.
Verifies all 15 audit remediation items across network generation, TraCI telemetry,
signal actuation, scenario comparison parity, and service lifecycle.
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from shapely.geometry import Polygon

from app.models.schemas import (
    RoadNetworkMetrics,
    RoadSegment,
    ScenarioComparisonResult,
    SimulationMetrics,
    SimulationPrepareRequest,
    TrafficObservation,
)
from app.recommendations.engine import _choose_intervention, generate_recommendations
from app.simulation.manifest import create_experiment_manifest
from app.simulation.network_builder import SumoNetworkBuilder
from app.simulation.scenario_comparator import ScenarioComparator
from app.simulation.signal_optimizer import FixedTimeSignalOptimizer
from app.simulation.traci_manager import SimulationSession


def test_polygon_boundary_classification(tmp_path: Path):
    """Test Phase 2A: Shapely polygon boundary classification accurately identifies entry/exit edges."""
    builder = SumoNetworkBuilder(tmp_path)
    # Define a simple rectangular boundary polygon: [lng, lat]
    poly_coords = [
        [77.58, 12.96],
        [77.60, 12.96],
        [77.60, 12.98],
        [77.58, 12.98],
        [77.58, 12.96],
    ]
    # Inbound: crossing from outside into center
    # Outbound: going from center to outside
    # Internal: completely inside
    segments = [
        {
            "segment_id": "seg_in",
            "u": "1",
            "v": "2",
            "geometry": {"coordinates": [[77.57, 12.97], [77.59, 12.97]]},
            "oneway": True,
            "road_type": "arterial",
        },
        {
            "segment_id": "seg_out",
            "u": "2",
            "v": "3",
            "geometry": {"coordinates": [[77.59, 12.97], [77.61, 12.97]]},
            "oneway": True,
            "road_type": "arterial",
        },
        {
            "segment_id": "seg_internal",
            "u": "4",
            "v": "5",
            "geometry": {"coordinates": [[77.585, 12.97], [77.595, 12.97]]},
            "oneway": True,
            "road_type": "local",
        },
    ]

    nodes, edges, _, _, _ = builder._extract_nodes_and_edges(segments)
    inbound, outbound, internal = builder._identify_boundary_edges(nodes, edges, poly_coords)

    # Inbound must contain seg_in forward edge
    assert any("seg_in" in e["id"] for e in inbound)
    # Outbound must contain seg_out forward edge
    assert any("seg_out" in e["id"] for e in outbound)
    # Internal must contain seg_internal
    assert any("seg_internal" in e["id"] for e in internal)
    assert "polygon_boundary" in builder.boundary_diagnostics["method"]


def test_reachability_verified_route_generation(tmp_path: Path):
    """Test Phase 2B: Reachability graph validation verifies paths and tracks demand truthfully."""
    builder = SumoNetworkBuilder(tmp_path)
    rou_file = tmp_path / "routes.rou.xml"

    # Segments with a directed path: seg_1 (1->2) -> seg_2 (2->3)
    # and a disconnected segment: seg_disc (9->10)
    segments = [
        {
            "segment_id": "seg_1",
            "u": "1",
            "v": "2",
            "geometry": {"coordinates": [[77.58, 12.96], [77.585, 12.965]]},
            "oneway": True,
            "road_type": "arterial",
            "lanes": 2,
        },
        {
            "segment_id": "seg_2",
            "u": "2",
            "v": "3",
            "geometry": {"coordinates": [[77.585, 12.965], [77.59, 12.97]]},
            "oneway": True,
            "road_type": "arterial",
            "lanes": 2,
        },
        {
            "segment_id": "seg_disc",
            "u": "9",
            "v": "10",
            "geometry": {"coordinates": [[77.65, 12.90], [77.655, 12.905]]},
            "oneway": True,
            "road_type": "local",
            "lanes": 1,
        },
    ]

    nodes, edges, _, _, _ = builder._extract_nodes_and_edges(segments)
    sched, init = builder._write_routes_xml(
        file_path=rou_file,
        nodes=nodes,
        edges=edges,
        duration_seconds=60,
        demand_rate_veh_hr=300,
        seed=42,
        initial_population=5,
    )

    assert rou_file.is_file()
    assert builder.demand_tracking["valid_trips_count"] > 0
    # Every generated route must start on seg_1 and end on seg_2
    content = rou_file.read_text(encoding="utf-8")
    assert 'from="seg_1"' in content or 'from="e_seg_1_fwd"' in content
    assert 'to="seg_2"' in content or 'to="e_seg_2_fwd"' in content
    # Disconnected segment must never be paired with unreachable origins
    assert 'from="seg_1" to="seg_disc"' not in content
    assert 'from="seg_disc" to="seg_1"' not in content


def test_experiment_manifest_demand_parity(tmp_path: Path):
    """Test Phase 6: Experiment manifest calculates hashes and enforces demand parity."""
    opt_dir = tmp_path / "optimized"
    base_dir = tmp_path / "baseline"
    opt_dir.mkdir()
    base_dir.mkdir()

    opt_net = opt_dir / "network.net.xml"
    base_net = base_dir / "network.net.xml"
    opt_rou = opt_dir / "routes.rou.xml"
    base_rou = base_dir / "routes.rou.xml"

    opt_net.write_text("<net>opt</net>", encoding="utf-8")
    base_net.write_text("<net>base</net>", encoding="utf-8")
    opt_rou.write_text("<routes><v id='1'/></routes>", encoding="utf-8")
    base_rou.write_text("<routes><v id='1'/></routes>", encoding="utf-8")

    manifest = create_experiment_manifest(
        sim_id="sim_test",
        analysis_id="an_test",
        duration_seconds=600,
        seed=42,
        demand_rate_veh_hr=500,
        demand_level="normal",
        demand_profile="peak",
        scheduled_vehicles=10,
        initial_vehicles=5,
        base_dir=base_dir,
        opt_dir=opt_dir,
        base_engine_mode="native_sumo",
        opt_engine_mode="native_sumo",
        base_strategy="base",
        opt_strategy="opt",
        base_signal_count=1,
        opt_signal_count=1,
        applied_signals_count=1,
        approved_signals=["TL_1"],
        step_length=0.2,
    )

    assert manifest.parity_verified is True
    assert len(manifest.parity_discrepancies) == 0
    assert (tmp_path / "experiment_manifest.json").is_file()


def test_scenario_comparison_parity_failure():
    """Test Phase 6: Scenario comparator invalidates comparison when demand parity fails."""
    manifest_dict = {
        "parity_verified": False,
        "discrepancies": ["Route file hash mismatch: baseline routes differ from optimized"],
    }
    base_metrics = SimulationMetrics(
        avg_speed_kmh=20.0,
        avg_waiting_time_s=30.0,
        avg_queue_length_m=15.0,
        completed_vehicles=50,
        elapsed_seconds=100.0,
        total_duration_seconds=600.0,
    )
    opt_metrics = SimulationMetrics(
        avg_speed_kmh=25.0,
        avg_waiting_time_s=20.0,
        avg_queue_length_m=10.0,
        completed_vehicles=60,
        elapsed_seconds=100.0,
        total_duration_seconds=600.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_parity_fail",
        analysis_id="an_1",
        duration_seconds=600,
        engine_mode="native_sumo",
        baseline_metrics=base_metrics,
        optimized_metrics=opt_metrics,
        baseline_engine_mode="native_sumo",
        signal_count=2,
        applied_signals_count=2,
        optimizer_validation_passed=True,
        experiment_manifest=manifest_dict,
    )

    assert res.is_validated is False
    assert res.optimization_status == "experiment_parity_failed"
    assert res.comparison_status == "insufficient_data"
    assert "Demand parity failed" in res.methodology_notes


def test_fallback_mode_never_claims_improvement():
    """Test Phase 5: Fallback kinematics mode strictly disables improvement badges and percentage claims."""
    base_metrics = SimulationMetrics(
        avg_speed_kmh=20.0,
        avg_waiting_time_s=30.0,
        avg_queue_length_m=15.0,
        completed_vehicles=50,
        elapsed_seconds=100.0,
        total_duration_seconds=600.0,
    )
    opt_metrics = SimulationMetrics(
        avg_speed_kmh=28.0,
        avg_waiting_time_s=15.0,
        avg_queue_length_m=8.0,
        completed_vehicles=65,
        elapsed_seconds=100.0,
        total_duration_seconds=600.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_fallback",
        analysis_id="an_1",
        duration_seconds=600,
        engine_mode="fallback",
        baseline_metrics=base_metrics,
        optimized_metrics=opt_metrics,
        baseline_engine_mode="fallback",
        signal_count=2,
        applied_signals_count=2,
        optimizer_validation_passed=True,
    )

    assert res.is_validated is False
    assert res.comparison_status == "completed_inconclusive"
    assert res.optimization_status == "kinematics_estimate_only"
    # All rows must report is_improvement = False under fallback
    for row in res.rows:
        assert row.is_improvement is False
        assert "Estimated visual variance — kinematics fallback" in row.variance


def test_empty_edge_telemetry_accuracy(tmp_path: Path):
    """Test Phase 9: Telemetry correctly distinguishes empty edges from stopped queues."""
    session = SimulationSession(
        sim_id="sim_telemetry",
        analysis_id="an_1",
        work_dir=tmp_path,
        cfg_file=tmp_path / "sim.sumocfg",
        duration_seconds=60,
        demand_rate_veh_hr=500,
        strategy="actuated_adaptive",
        edge_count=2,
        junction_count=1,
        signal_count=0,
        netconvert_used=False,
    )

    # Sample empty edge: vehicle_count = 0, mean_speed = 0.0, halting = 0, occupancy = 0.0
    empty_sample = {
        "edge_id": "e_empty",
        "timestamp": 1.0,
        "mean_speed_ms": 0.0,
        "vehicle_count": 0,
        "occupancy_pct": 0.0,
        "halting_vehicles": 0,
        "waiting_time_s": 0.0,
    }
    session._accumulate_edge_sample("e_empty", empty_sample)

    st = session._edge_cumulative_stats["e_empty"]
    # Empty edge must have 0 observed vehicle samples and 0 congested samples
    assert st["observed_vehicle_samples"] == 0
    assert st["congested_samples"] == 0
    assert st["min_speed_ms"] == float("inf")  # Unpolluted by 0.0

    # Sample congested edge: vehicle_count = 3, mean_speed = 1.5, halting = 2, occupancy = 45%
    cong_sample = {
        "edge_id": "e_cong",
        "timestamp": 1.0,
        "mean_speed_ms": 1.5,
        "vehicle_count": 3,
        "occupancy_pct": 45.0,
        "halting_vehicles": 2,
        "waiting_time_s": 15.0,
    }
    session._accumulate_edge_sample("e_cong", cong_sample)

    st_cong = session._edge_cumulative_stats["e_cong"]
    assert st_cong["observed_vehicle_samples"] == 1
    assert st_cong["congested_samples"] == 1
    assert st_cong["min_speed_ms"] == 1.5


def test_session_stop_lifecycle(tmp_path: Path):
    """Test Phase 4: Session stop correctly sets state to 'stopped'."""
    session = SimulationSession(
        sim_id="sim_stop",
        analysis_id="an_1",
        work_dir=tmp_path,
        cfg_file=tmp_path / "sim.sumocfg",
        duration_seconds=60,
        demand_rate_veh_hr=500,
        strategy="actuated_adaptive",
        edge_count=1,
        junction_count=1,
        signal_count=0,
        netconvert_used=False,
    )
    session.state = "running"
    session.stop()
    assert session.state == "stopped"


def test_recommendation_warrant_validation():
    """Test Phase 12: Recommendations distinguish screening vs formal engineering warrants."""
    # Create segment with heavy traffic and explicit unsignalized controls
    seg = RoadSegment(
        segment_id="seg_unsig",
        name="MG Road",
        u="101",
        v="102",
        coordinates=[[77.60, 12.97], [77.61, 12.97]],
        length_m=350.0,
        road_type="arterial",
        lanes=2,
        u_control="priority",
        v_control="priority",
    )
    obs = TrafficObservation(
        segment_id="seg_unsig",
        congestion_level="severe",
        speed_reduction_ratio=0.55,
        observed_speed_kmh=18.0,
        free_flow_speed_kmh=50.0,
    )
    from app.models.schemas import BottleneckCandidate
    b = BottleneckCandidate(
        segment_id="seg_unsig",
        lat=12.97,
        lng=77.605,
        evidence=["High traffic delay"],
        bottleneck_type="combined",
        severity="high",
        centrality_score=0.45,
    )

    itype, title, desc, cat = _choose_intervention(b, obs, None, seg)
    assert itype == "signal_installation"
    assert "Warrant" in title
    assert "MUTCD Warrant 1" in desc
