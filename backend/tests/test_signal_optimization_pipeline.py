"""
Tests for the Gativa Traffic Signal Screening, Fixed-Time Optimization,
and Natural Vehicle Population Distribution Pipeline.
"""
from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.sqlite_store import (
    get_candidate_decisions_sync,
    init_sqlite_db,
    reset_candidate_decisions_sync,
    save_candidate_decision_sync,
)
from app.models.schemas import (
    AnalysisResult,
    GeoJSONLineString,
    GeoJSONPolygon,
    RoadSegment,
    TrafficObservation,
)
from app.simulation.network_builder import SumoNetworkBuilder, find_sumo_binary
from app.simulation.scenario_comparator import ScenarioComparator
from app.simulation.signal_candidates import (
    approve_all_eligible_candidates,
    generate_signal_candidates,
    get_signal_candidates_response,
    reset_candidates,
    update_candidate_decision,
)
from app.simulation.signal_optimizer import FixedTimeSignalOptimizer
from main import app


def _create_sample_4way_junction_analysis(analysis_id: str = "test_analysis_1") -> AnalysisResult:
    """Create a synthetic AnalysisResult with a 4-way intersection at (77.2090, 28.6139)."""
    center_lon, center_lat = 77.2090, 28.6139
    segments = [
        # North leg
        RoadSegment(
            segment_id="seg_north",
            name="North Arterial Avenue",
            road_type="arterial",
            length_m=200.0,
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[center_lon, center_lat + 0.002], [center_lon, center_lat]],
            ),
            u="101",
            v="100",  # Center junction is 100
            u_control="priority",
            v_control="priority",
            traffic=TrafficObservation(
                segment_id="seg_north",
                current_speed_kmh=24.0,
                free_flow_speed_kmh=50.0,
                speed_reduction_ratio=0.52,
            ),
        ),
        # South leg
        RoadSegment(
            segment_id="seg_south",
            name="South Arterial Avenue",
            road_type="arterial",
            length_m=200.0,
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[center_lon, center_lat - 0.002], [center_lon, center_lat]],
            ),
            u="102",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
        # East leg
        RoadSegment(
            segment_id="seg_east",
            name="East Crossway",
            road_type="collector",
            length_m=180.0,
            speed_limit_kmh=40.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[center_lon + 0.002, center_lat], [center_lon, center_lat]],
            ),
            u="103",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
        # West leg
        RoadSegment(
            segment_id="seg_west",
            name="West Crossway",
            road_type="collector",
            length_m=180.0,
            speed_limit_kmh=40.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[center_lon - 0.002, center_lat], [center_lon, center_lat]],
            ),
            u="104",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
    ]

    return AnalysisResult(
        analysis_id=analysis_id,
        status="completed",
        area_km2=0.5,
        created_at="2026-10-21T00:00:00Z",
        polygon=GeoJSONPolygon(
            type="Polygon",
            coordinates=[[
                [center_lon - 0.003, center_lat - 0.003],
                [center_lon + 0.003, center_lat - 0.003],
                [center_lon + 0.003, center_lat + 0.003],
                [center_lon - 0.003, center_lat + 0.003],
                [center_lon - 0.003, center_lat - 0.003],
            ]],
        ),
        segments=segments,
        bottlenecks=[],
        summary={},
        data_sources=[],
    )


def test_signal_candidate_screening_and_eligibility():
    """Verify junction candidate screening correctly scores degree >= 3 and identifies eligibility."""
    init_sqlite_db()
    analysis = _create_sample_4way_junction_analysis("screen_test_1")

    candidates = generate_signal_candidates(analysis)
    assert len(candidates) >= 1

    # Find center junction candidate (node_100, 4-way)
    center_cand = next((c for c in candidates if c.junction_id == "node_100"), None)
    assert center_cand is not None
    assert center_cand.degree == 4
    assert center_cand.is_eligible is True
    assert center_cand.priority_score >= 5.0
    assert "North Arterial Avenue" in str(center_cand.approach_roads)
    assert center_cand.status == "pending"
    assert "MUTCD Warrant" in center_cand.uncertainty_notes


def test_candidate_decision_sqlite_persistence_roundtrip():
    """Verify candidate decisions are persisted and restored accurately."""
    init_sqlite_db()
    analysis_id = "persist_test_1"
    cand_id = "cand_node_100"

    reset_candidate_decisions_sync(analysis_id)
    decisions = get_candidate_decisions_sync(analysis_id)
    assert cand_id not in decisions

    # Save decision: approved
    save_candidate_decision_sync(analysis_id, cand_id, "approved")
    decisions_after = get_candidate_decisions_sync(analysis_id)
    assert decisions_after.get(cand_id) == "approved"

    # Save decision: rejected
    save_candidate_decision_sync(analysis_id, cand_id, "rejected")
    decisions_rejected = get_candidate_decisions_sync(analysis_id)
    assert decisions_rejected.get(cand_id) == "rejected"

    # Reset decisions
    reset_candidate_decisions_sync(analysis_id)
    decisions_reset = get_candidate_decisions_sync(analysis_id)
    assert cand_id not in decisions_reset


def test_baseline_vs_optimized_network_compilation_with_approved_signal():
    """
    Verify Baseline scenario preserves unsignalized priority controls
    while Optimized scenario compiles approved candidate nodes into traffic lights.
    """
    analysis = _create_sample_4way_junction_analysis("compile_test_1")
    segments_dict = [s.model_dump() for s in analysis.segments]

    with tempfile.TemporaryDirectory() as tmp_base, tempfile.TemporaryDirectory() as tmp_opt:
        builder_base = SumoNetworkBuilder(Path(tmp_base))
        meta_base = builder_base.build(
            segments=segments_dict,
            duration_seconds=300,
            approved_signal_junctions=None,  # Baseline: no interventions
        )
        # Baseline must have zero traffic lights
        assert meta_base["signal_count"] == 0
        node_100_base = meta_base["nodes"]["node_100"]
        assert node_100_base["type"] == "priority"

        builder_opt = SumoNetworkBuilder(Path(tmp_opt))
        meta_opt = builder_opt.build(
            segments=segments_dict,
            duration_seconds=300,
            approved_signal_junctions={"node_100"},  # User approved center junction
        )
        # Optimized must have traffic light compiled at node_100
        assert meta_opt["signal_count"] == 1
        node_100_opt = meta_opt["nodes"]["node_100"]
        assert node_100_opt["type"] == "traffic_light"
        assert node_100_opt["provenance"] == "user_approved_candidate"


def test_natural_vehicle_initialization_at_time_zero():
    """
    Verify initial vehicle population is placed at depart='0.0' with departPos='random',
    departSpeed='avg', and departLane='best' distributed across distinct network edges.
    """
    analysis = _create_sample_4way_junction_analysis("demand_test_1")
    segments_dict = [s.model_dump() for s in analysis.segments]

    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(
            segments=segments_dict,
            duration_seconds=300,
            demand_rate_veh_hr=2400,
            seed=42,
            initial_population=6,
        )

        rou_file = Path(meta["rou_file"])
        assert rou_file.is_file()

        tree = ET.parse(str(rou_file))
        root = tree.getroot()
        trips = root.findall("trip")
        assert len(trips) >= 6

        # Check initial vehicles at 0.0
        init_trips = [t for t in trips if t.attrib.get("depart") == "0.0"]
        assert len(init_trips) == 6

        # Ensure departPos="random", departSpeed="avg", departLane="best"
        for t in init_trips:
            assert t.attrib.get("departPos") == "random"
            assert t.attrib.get("departSpeed") == "avg"
            assert t.attrib.get("departLane") == "best"

        # Ensure initial vehicles are distributed across distinct edges (not all piled on edge 0)
        from_edges = [t.attrib.get("from") for t in init_trips]
        assert len(set(from_edges)) > 1

        # Check scheduled departures have t >= 1.0
        sched_trips = [t for t in trips if float(t.attrib.get("depart")) > 0.0]
        assert len(sched_trips) > 0
        for st in sched_trips:
            assert float(st.attrib.get("depart")) >= 1.0


def test_fixed_time_signal_optimizer_candidate_generation():
    """Verify FixedTimeSignalOptimizer generates bounded timing alternatives with safe clearance intervals."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        optimizer = FixedTimeSignalOptimizer(Path(tmp_dir))

        base_phases = [
            {"duration": 30.0, "state": "GGGrrr"},
            {"duration": 3.0, "state": "yyyrrr"},
            {"duration": 30.0, "state": "rrrGGG"},
            {"duration": 3.0, "state": "rrryyy"},
        ]

        plans = optimizer.generate_candidate_plans("tl_test", base_phases)
        assert len(plans) == 4

        plan_ids = [p["plan_id"] for p in plans]
        assert "plan_short_60s" in plan_ids
        assert "plan_balanced_90s" in plan_ids
        assert "plan_arterial_90s" in plan_ids
        assert "plan_high_cap_105s" in plan_ids

        # Verify yellow clearance safety constraint (>= 3.0s)
        for p in plans:
            for ph in p["phases"]:
                if "y" in ph["state"].lower():
                    assert float(ph["duration"]) >= 3.0
                elif "g" in ph["state"].lower():
                    assert float(ph["duration"]) >= 10.0  # Minimum green constraint


def test_scenario_comparator_with_approved_signal_metadata():
    """Verify ScenarioComparator preserves honest metadata for approved signals and timing plans."""
    res = ScenarioComparator.compare(
        sim_id="sim_compare_meta",
        analysis_id="analysis_meta",
        duration_seconds=600,
        baseline_strategy="Baseline (Original Controls)",
        optimized_strategy="Optimized (Balanced Cycle Plan)",
        signal_count=1,
        approved_signals_count=1,
        applied_signals_count=1,
        initial_vehicles_count=8,
    )

    assert res.approved_signals_count == 1
    assert res.applied_signals_count == 1
    assert res.initial_vehicles_count == 8
    assert res.baseline_strategy == "Baseline (Original Controls)"
    assert "Optimized" in res.optimized_strategy


def test_signal_candidates_api_endpoints():
    """Verify FastAPI routes for listing candidates, recording decisions, approve-all, and reset."""
    from app.core.sqlite_store import save_analysis_sync

    analysis = _create_sample_4way_junction_analysis("api_cand_test_1")
    save_analysis_sync(analysis.analysis_id, analysis.model_dump())

    client = TestClient(app)

    # 1. GET /api/simulations/{analysis_id}/signal-candidates
    resp = client.get(f"/api/simulations/{analysis.analysis_id}/signal-candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis_id"] == analysis.analysis_id
    assert data["total_candidates"] >= 1
    assert data["eligible_count"] >= 1
    assert data["approved_count"] == 0

    cand_id = data["candidates"][0]["candidate_id"]

    # 2. POST /api/simulations/{analysis_id}/signal-candidates/{candidate_id}/decision
    resp_dec = client.post(
        f"/api/simulations/{analysis.analysis_id}/signal-candidates/{cand_id}/decision",
        json={"status": "approved", "decision": "approved"},
    )
    assert resp_dec.status_code == 200
    assert resp_dec.json()["status"] == "ok"

    # Verify decision reflected in list
    resp_check = client.get(f"/api/simulations/{analysis.analysis_id}/signal-candidates")
    assert resp_check.json()["approved_count"] == 1

    # 3. POST /api/simulations/{analysis_id}/signal-candidates/approve-all
    resp_app_all = client.post(f"/api/simulations/{analysis.analysis_id}/signal-candidates/approve-all")
    assert resp_app_all.status_code == 200
    assert resp_app_all.json()["approved_count"] >= 1

    # 4. POST /api/simulations/{analysis_id}/signal-candidates/reset
    resp_reset = client.post(f"/api/simulations/{analysis.analysis_id}/signal-candidates/reset")
    assert resp_reset.status_code == 200

    # Verify reset to 0 approved
    resp_after_reset = client.get(f"/api/simulations/{analysis.analysis_id}/signal-candidates")
    assert resp_after_reset.json()["approved_count"] == 0


def test_prepare_simulation_with_approved_candidates():
    """Verify POST /api/simulations/prepare accepts approved_candidate_ids and compiles them."""
    from app.core.sqlite_store import save_analysis_sync

    analysis = _create_sample_4way_junction_analysis("api_prep_test_1")
    save_analysis_sync(analysis.analysis_id, analysis.model_dump())

    client = TestClient(app)

    resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": analysis.analysis_id,
            "duration_seconds": 120,
            "approved_candidate_ids": ["cand_node_100"],
            "initial_population": 4,
            "seed": 42,
        },
    )
    assert resp.status_code == 201
    sim_data = resp.json()
    assert sim_data["analysis_id"] == analysis.analysis_id
    assert sim_data["initial_vehicles_count"] == 4
    assert sim_data["approved_signals_count"] == 1
    assert sim_data["applied_signals_count"] >= 1
    assert "Optimized" in sim_data["strategy"]

