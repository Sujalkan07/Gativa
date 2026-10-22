"""
Unit and integration tests for SUMO Microscopic Traffic Simulation, TraCI controls,
engine mode transparency, coordinate validation, and honest scenario comparisons.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile

from main import app
from app.simulation.network_builder import find_sumo_binary, SumoNetworkBuilder
from app.simulation.traci_manager import SimulationSession, normalize_traffic_light_state
from app.simulation.scenario_comparator import ScenarioComparator
from app.simulation.service import simulation_service
from app.models.schemas import SimulationMetrics, SimulationPrepareRequest

client = TestClient(app)


@pytest.mark.parametrize(
    ("sumo_state", "display_state"),
    [
        ("GrGr", "green"),
        ("yyyy", "yellow"),
        ("uuuu", "yellow"),
        ("rrrr", "red"),
        ("oooo", "unknown"),
        ("", "unknown"),
    ],
)
def test_sumo_signal_state_normalization(sumo_state, display_state):
    assert normalize_traffic_light_state(sumo_state) == display_state


def test_native_sumo_extracts_real_signal_state():
    """Compile a signalized crossing and verify TraCI exposes its live phase."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        segments = [
            {
                "segment_id": "west_approach",
                "geometry": {"type": "LineString", "coordinates": [[77.590, 12.970], [77.600, 12.970]]},
                "u": "west", "v": "center", "v_control": "traffic_signal", "v_provenance": "source_verified",
            },
            {
                "segment_id": "east_approach",
                "geometry": {"type": "LineString", "coordinates": [[77.600, 12.970], [77.610, 12.970]]},
                "u": "center", "v": "east", "u_control": "traffic_signal", "u_provenance": "source_verified",
            },
            {
                "segment_id": "south_approach",
                "geometry": {"type": "LineString", "coordinates": [[77.600, 12.960], [77.600, 12.970]]},
                "u": "south", "v": "center", "v_control": "traffic_signal", "v_provenance": "source_verified",
            },
            {
                "segment_id": "north_approach",
                "geometry": {"type": "LineString", "coordinates": [[77.600, 12.970], [77.600, 12.980]]},
                "u": "center", "v": "north", "u_control": "traffic_signal", "u_provenance": "source_verified",
            },
        ]
        work_dir = Path(tmp_dir)
        meta = SumoNetworkBuilder(work_dir).build(segments, duration_seconds=60)
        assert meta["netconvert_used"] is True
        session = SimulationSession(
            sim_id="test_native_signal_state",
            analysis_id="test_native_signal_state",
            work_dir=work_dir,
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=60,
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
            road_segments=segments,
            netconvert_used=meta["netconvert_used"],
        )
        try:
            session.start()
            assert session.engine_mode == "native_sumo"
            status = session.step(num_steps=1)
            assert status["engine_mode"] == "native_sumo"
            assert status["elapsed_seconds"] == pytest.approx(0.2)
            assert status["traffic_lights"], "native TraCI should return the compiled signal"
            for signal in status["traffic_lights"]:
                assert signal["state"] in {"green", "yellow", "red", "unknown"}
                assert signal["is_green"] is (signal["state"] == "green")
        finally:
            session.stop()


def test_find_sumo_binary():
    """Verify SUMO binaries are discoverable on this machine."""
    sumo_bin = find_sumo_binary("sumo")
    netconvert_bin = find_sumo_binary("netconvert")
    assert sumo_bin is not None, "sumo binary should be discovered"
    assert netconvert_bin is not None, "netconvert binary should be discovered"
    assert Path(sumo_bin).exists()
    assert Path(netconvert_bin).exists()


def test_sumo_network_builder():
    """Verify SumoNetworkBuilder generates valid XML files and netconvert succeeds."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))

        # 1. Real road segments with zero traffic signals (Issue A)
        real_segments = [
            {
                "segment_id": "seg_1",
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
                "speed_limit_kmh": 50.0,
                "lanes": 2,
                "is_oneway": False,
            },
            {
                "segment_id": "seg_2",
                "geometry": {"type": "LineString", "coordinates": [[77.60, 12.97], [77.61, 12.97]]},
                "speed_limit_kmh": 50.0,
                "lanes": 2,
                "is_oneway": False,
            },
        ]
        result = builder.build(
            segments=real_segments,
            duration_seconds=300,
            demand_rate_veh_hr=2000,
        )
        assert Path(result["net_file"]).is_file()
        assert Path(result["cfg_file"]).is_file()
        assert Path(result["rou_file"]).is_file()
        assert result["edge_count"] > 0
        assert result["junction_count"] > 0
        assert result["signal_count"] == 0

        # 2. Road segments with verified traffic signal
        signalized_segments = [
            {
                "segment_id": "seg_sig_1",
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
                "u_control": "traffic_signal",
                "u_provenance": "source_verified",
            }
        ]
        result_sig = builder.build(
            segments=signalized_segments,
            duration_seconds=300,
            demand_rate_veh_hr=2000,
        )
        assert result_sig["signal_count"] >= 1

        # 3. Explicit synthetic demo mode
        result_demo = builder.build(
            segments=[],
            duration_seconds=300,
            allow_synthetic=True,
        )
        assert result_demo["edge_count"] > 0
        assert result_demo["network_provenance"] == "synthetic_demo"

        # 4. Critical Issue B: Reject empty segments when allow_synthetic is False
        with pytest.raises(ValueError, match="No road segments provided"):
            builder.build(segments=[], allow_synthetic=False)


def test_fallback_net_xml_marked_unvalidated():
    """Verify fallback net XML contains explicit unvalidated structural fallback notice."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        net_path = Path(tmp_dir) / "network.net.xml"
        nodes = {"n1": {"id": "n1", "x": 0.0, "y": 0.0}, "n2": {"id": "n2", "x": 1.0, "y": 1.0}}
        edges = [{"id": "e1", "from": "n1", "to": "n2", "numLanes": 1, "speed": 13.9}]
        builder._write_fallback_net_xml(net_path, nodes, edges)

        content = net_path.read_text(encoding="utf-8")
        assert "UNVALIDATED_STRUCTURAL_FALLBACK" in content


def test_simulation_session_lifecycle():
    """Verify SimulationSession lifecycle: ready -> start -> step -> pause -> reset -> stop."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(segments=[], duration_seconds=120, allow_synthetic=True)

        session = SimulationSession(
            sim_id="test_sim_lifecycle",
            analysis_id="test_analysis_123",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=120,
            demand_rate_veh_hr=2840,
            strategy="actuated_adaptive",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
            netconvert_used=meta["netconvert_used"],
            is_synthetic_demo=True,
        )

        try:
            assert session.state == "ready"
            assert session.engine_mode in ("native_sumo", "fallback")
            session.start()
            assert session.state == "running"

            status_after_step = session.step(num_steps=3)
            assert status_after_step["step"] == 3
            assert status_after_step["elapsed_seconds"] > 0
            assert status_after_step["engine_mode"] in ("native_sumo", "fallback")
            assert len(status_after_step["vehicles"]) > 0

            # Validate WGS84 coordinates
            for v in status_after_step["vehicles"]:
                assert -90.0 <= v["lat"] <= 90.0
                assert -180.0 <= v["lng"] <= 180.0

            session.pause()
            assert session.state == "paused"

            session.reset()
            assert session.state == "ready"
            assert session.step_count == 0
            assert session.elapsed_seconds == 0.0
        finally:
            session.stop()


def test_fallback_corridor_interpolation():
    """Verify fallback simulation interpolates vehicles along provided road segment polylines."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Bangalore road segments
        segments = [
            {
                "segment_id": "seg_blr_1",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5946, 12.9716], [77.6046, 12.9816]],
                },
            }
        ]
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(segments=segments, duration_seconds=120)

        session = SimulationSession(
            sim_id="test_sim_fallback",
            analysis_id="test_blr_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=120,
            demand_rate_veh_hr=1500,
            strategy="actuated_adaptive",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
            road_segments=segments,
            netconvert_used=False,  # Force fallback
        )

        assert session.engine_mode == "fallback"
        session.start()
        status = session.step(num_steps=2)

        assert len(status["vehicles"]) > 0
        assert status["elapsed_seconds"] == pytest.approx(0.4)
        for veh in status["vehicles"]:
            # Vehicles must be interpolated around Bangalore [12.9x, 77.5x-77.6x], NOT hardcoded Lucknow!
            assert 12.90 <= veh["lat"] <= 13.05, f"Expected Bangalore latitude, got {veh['lat']}"
            assert 77.50 <= veh["lng"] <= 77.70, f"Expected Bangalore longitude, got {veh['lng']}"

        session.stop()


def test_scenario_comparator_honest_variance():
    """Verify ScenarioComparator computes genuine percentage variances without synthetic multipliers."""
    baseline = SimulationMetrics(
        avg_speed_kmh=18.0,
        avg_waiting_time_s=80.0,
        avg_queue_length_m=120.0,
        completed_vehicles=400,
        elapsed_seconds=60.0,
    )
    optimized = SimulationMetrics(
        avg_speed_kmh=27.0,
        avg_waiting_time_s=40.0,
        avg_queue_length_m=60.0,
        completed_vehicles=500,
        elapsed_seconds=60.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_comp_test",
        analysis_id="analysis_comp_test",
        duration_seconds=600,
        engine_mode="native_sumo",
        baseline_metrics=baseline,
        optimized_metrics=optimized,
        step_count=10,
    )

    assert res.sim_id == "sim_comp_test"
    assert res.comparison_status == "completed"
    assert res.engine_mode == "native_sumo"
    assert len(res.rows) == 4

    # Speed: (27 - 18) / 18 * 100 = +50.0%
    speed_row = next(r for r in res.rows if r.metric == "Average Speed")
    assert "+50.0%" in speed_row.variance
    assert speed_row.is_improvement is True

    # Waiting Time: (40 - 80) / 80 * 100 = -50.0%
    wait_row = next(r for r in res.rows if r.metric == "Average Waiting Time")
    assert "-50.0%" in wait_row.variance
    assert wait_row.is_improvement is True

    # Completed Vehicles: (500 - 400) / 400 * 100 = +25.0%
    comp_row = next(r for r in res.rows if r.metric == "Completed Vehicles")
    assert "+25.0%" in comp_row.variance
    assert comp_row.is_improvement is True


def test_scenario_comparator_withholds_mixed_engine_comparison():
    metrics = SimulationMetrics(avg_speed_kmh=20.0, elapsed_seconds=10.0)
    result = ScenarioComparator.compare(
        sim_id="mixed_engine_test",
        analysis_id="analysis_mixed_engine_test",
        duration_seconds=60,
        engine_mode="fallback",
        baseline_engine_mode="native_sumo",
        baseline_metrics=metrics.model_copy(deep=True),
        optimized_metrics=metrics.model_copy(deep=True),
        step_count=10,
    )

    assert result.comparison_status == "insufficient_data"
    assert "baseline ran with native_sumo" in result.methodology_notes
    assert all("engine mismatch" in row.variance.lower() for row in result.rows)


def test_scenario_comparator_pending_state():
    """Verify ScenarioComparator returns pending state when simulation has 0 steps."""
    res = ScenarioComparator.compare(
        sim_id="sim_pending",
        analysis_id="analysis_pending",
        duration_seconds=600,
        engine_mode="native_sumo",
        baseline_metrics=None,
        optimized_metrics=None,
        step_count=0,
    )

    assert res.comparison_status == "pending"
    for row in res.rows:
        assert row.variance == "Pending step"
        assert row.is_improvement is False


def test_scenario_comparator_honest_regression():
    """Verify ScenarioComparator honestly reports regressions if optimized performs worse."""
    baseline = SimulationMetrics(
        avg_speed_kmh=25.0,
        avg_waiting_time_s=30.0,
        avg_queue_length_m=40.0,
        completed_vehicles=500,
        elapsed_seconds=100.0,
    )
    # Worse speed and longer queue
    worse_optimized = SimulationMetrics(
        avg_speed_kmh=20.0,
        avg_waiting_time_s=45.0,
        avg_queue_length_m=60.0,
        completed_vehicles=400,
        elapsed_seconds=100.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_regression",
        analysis_id="analysis_regression",
        duration_seconds=600,
        engine_mode="native_sumo",
        baseline_metrics=baseline,
        optimized_metrics=worse_optimized,
        step_count=20,
    )

    assert res.comparison_status == "completed"
    speed_row = next(r for r in res.rows if r.metric == "Average Speed")
    assert "-20.0%" in speed_row.variance
    assert speed_row.is_improvement is False

    wait_row = next(r for r in res.rows if r.metric == "Average Waiting Time")
    assert "+50.0%" in wait_row.variance
    assert wait_row.is_improvement is False


def test_scenario_comparator_division_by_zero():
    """Verify zero baseline values are handled gracefully without NaN or Infinity."""
    baseline = SimulationMetrics(
        avg_speed_kmh=0.0,
        avg_waiting_time_s=0.0,
        avg_queue_length_m=0.0,
        completed_vehicles=0,
        elapsed_seconds=10.0,
    )
    optimized = SimulationMetrics(
        avg_speed_kmh=15.0,
        avg_waiting_time_s=10.0,
        avg_queue_length_m=20.0,
        completed_vehicles=5,
        elapsed_seconds=10.0,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_zero",
        analysis_id="analysis_zero",
        duration_seconds=600,
        engine_mode="fallback",
        baseline_metrics=baseline,
        optimized_metrics=optimized,
        step_count=5,
    )

    assert res.comparison_status == "completed"
    for row in res.rows:
        assert "nan" not in row.variance.lower()
        assert "inf" not in row.variance.lower()


def test_simulation_api_endpoints():
    """Verify HTTP API endpoints for simulation preparation, step, and comparison."""
    # 1. Validation failure: Missing analysis without synthetic demo returns 404 (Issue B)
    missing_resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "non_existent_analysis_xyz",
            "duration_seconds": 600,
            "demand_rate_veh_hr": 2840,
        },
    )
    assert missing_resp.status_code == 404

    # 2. Explicit synthetic demo mode succeeds (Issue B)
    prep_resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "test_endpoint_analysis",
            "duration_seconds": 600,
            "demand_rate_veh_hr": 2840,
            "strategy": "actuated_adaptive",
            "is_synthetic_demo": True,
            "is_synthetic_demo": True,
        },
    )
    assert prep_resp.status_code == 201
    sim_data = prep_resp.json()
    sim_id = sim_data["sim_id"]
    assert sim_data["state"] == "ready"
    assert sim_data["engine_mode"] in ("native_sumo", "fallback")
    assert sim_data["edge_count"] > 0
    assert sim_data["junction_count"] > 0
    assert sim_data["network_provenance"] == "synthetic_demo"

    try:
        # 3. Get Status
        status_resp = client.get(f"/api/simulations/{sim_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["sim_id"] == sim_id
        assert status_resp.json()["engine_mode"] in ("native_sumo", "fallback")

        # 4. Start
        start_resp = client.post(f"/api/simulations/{sim_id}/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["state"] == "running"

        # 5. Step
        step_resp = client.post(f"/api/simulations/{sim_id}/step?steps=2")
        assert step_resp.status_code == 200
        step_data = step_resp.json()
        assert step_data["step"] == 2
        assert len(step_data["vehicles"]) > 0

        # 6. Comparison
        comp_resp = client.get(f"/api/simulations/{sim_id}/comparison")
        assert comp_resp.status_code == 200
        comp_data = comp_resp.json()
        assert len(comp_data["rows"]) == 4
        assert comp_data["engine_mode"] in ("native_sumo", "fallback")
        assert comp_data["comparison_status"] == "completed"
        assert comp_data["baseline_strategy"] != ""
        assert comp_data["optimized_strategy"] != ""
    finally:
        # 7. Stop
        stop_resp = client.post(f"/api/simulations/{sim_id}/stop")
        assert stop_resp.status_code == 200


def test_polygon_centroid_corridor():
    """Verify empty segments with polygon_coords builds corridor centered on polygon centroid in demo mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Mumbai polygon coordinates
        mumbai_poly = [
            [72.8700, 19.0700],
            [72.8800, 19.0700],
            [72.8800, 19.0800],
            [72.8700, 19.0800],
            [72.8700, 19.0700],
        ]
        builder = SumoNetworkBuilder(Path(tmp_dir))
        res = builder.build(segments=[], polygon_coords=mumbai_poly, allow_synthetic=True)

        assert res["netconvert_used"] is True or Path(res["net_file"]).is_file()
        assert res["edge_count"] > 0
        assert res["junction_count"] > 0

        # Check nodes.nod.xml coordinates are around Mumbai
        nod_text = (Path(tmp_dir) / "nodes.nod.xml").read_text(encoding="utf-8")
        assert "72.8" in nod_text, "Nodes should be centered on Mumbai longitude"
        assert "19.0" in nod_text, "Nodes should be centered on Mumbai latitude"


def test_traffic_lights_in_session_status():
    """Verify session status returns valid TrafficLightState list for signalized network and zero for unsignalized (Issue A)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        # 1. Network with genuine verified traffic signals
        sig_segments = [
            {
                "segment_id": "seg_sig_status",
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
                "u_control": "traffic_signal",
                "u_provenance": "source_verified",
            }
        ]
        meta = builder.build(segments=sig_segments, duration_seconds=60)

        session = SimulationSession(
            sim_id="test_tl_status",
            analysis_id="test_tl_analysis",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=60,
            demand_rate_veh_hr=2000,
            strategy="actuated_adaptive",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
            road_segments=sig_segments,
            netconvert_used=False,  # Fallback to test deterministic signals
        )
        try:
            session.start()
            status = session.step(num_steps=1)
            assert "traffic_lights" in status
            assert isinstance(status["traffic_lights"], list)
            assert len(status["traffic_lights"]) > 0
            tl = status["traffic_lights"][0]
            assert "id" in tl
            assert "lat" in tl and -90.0 <= tl["lat"] <= 90.0
            assert "lng" in tl and -180.0 <= tl["lng"] <= 180.0
            assert tl["state"] in ("green", "yellow", "red")
        finally:
            session.stop()

        # 2. Network with zero signals must honestly report 0 signals
        unsig_segments = [
            {
                "segment_id": "seg_unsig_status",
                "geometry": {"type": "LineString", "coordinates": [[77.59, 12.97], [77.60, 12.97]]},
            }
        ]
        meta_unsig = builder.build(segments=unsig_segments, duration_seconds=60)
        session_unsig = SimulationSession(
            sim_id="test_tl_status_unsig",
            analysis_id="test_tl_analysis_unsig",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta_unsig["cfg_file"]),
            duration_seconds=60,
            demand_rate_veh_hr=2000,
            strategy="actuated_adaptive",
            edge_count=meta_unsig["edge_count"],
            junction_count=meta_unsig["junction_count"],
            signal_count=meta_unsig["signal_count"],
            road_segments=unsig_segments,
            netconvert_used=False,
        )
        try:
            session_unsig.start()
            status_unsig = session_unsig.step(num_steps=1)
            assert status_unsig["signal_count"] == 0
            assert status_unsig["traffic_lights"] == []
        finally:
            session_unsig.stop()


def test_routable_routes_generation():
    """Verify _write_routes_xml produces valid trip entries with immediate initial departure."""
    import xml.etree.ElementTree as ET

    with tempfile.TemporaryDirectory() as tmp_dir:
        rou_file = Path(tmp_dir) / "routes.rou.xml"
        builder = SumoNetworkBuilder(Path(tmp_dir))
        edges = [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
            {"id": "e3", "from": "n3", "to": "n4"},
        ]
        builder._write_routes_xml(rou_file, edges, duration_seconds=60, demand_rate_veh_hr=3600, seed=42)

        tree = ET.parse(str(rou_file))
        root = tree.getroot()
        trips = root.findall("trip")
        assert len(trips) >= 20

        # At least one trip must depart at 0.0 for immediate vehicle visibility
        departs = [float(t.attrib["depart"]) for t in trips]
        assert any(d == 0.0 for d in departs)

        # All trips must originate and terminate at valid edges
        valid_ids = {"e1", "e2", "e3"}
        for t in trips:
            assert t.attrib["from"] in valid_ids
            assert t.attrib["to"] in valid_ids


def test_step_speed_multipliers():
    """Verify simulation steps accurately and efficiently across 1x, 2x, and 5x step multipliers."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    prep_resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "test_speed_mult",
            "duration_seconds": 600,
            "demand_rate_veh_hr": 2500,
            "strategy": "actuated_adaptive",
            "is_synthetic_demo": True,
        },
    )
    assert prep_resp.status_code == 201
    sim_id = prep_resp.json()["sim_id"]

    try:
        # Start
        start_resp = client.post(f"/api/simulations/{sim_id}/start")
        assert start_resp.status_code == 200

        # Step 1x (1 step)
        s1 = client.post(f"/api/simulations/{sim_id}/step?steps=1").json()
        assert s1["step"] == 1

        # Step 2x (2 steps)
        s2 = client.post(f"/api/simulations/{sim_id}/step?steps=2").json()
        assert s2["step"] == 3

        # Step 5x (5 steps)
        s5 = client.post(f"/api/simulations/{sim_id}/step?steps=5").json()
        assert s5["step"] == 8
        assert s5["elapsed_seconds"] > 0
        assert s5["state"] == "running"
        assert len(s5["vehicles"]) > 0

        # Verify post-simulation congestion results are available and valid
        cong_resp = client.get(f"/api/simulations/{sim_id}/congestion")
        assert cong_resp.status_code == 200
        cong_data = cong_resp.json()
        assert cong_data["total_roads"] >= 0
        assert "all_results" in cong_data
    finally:
        client.post(f"/api/simulations/{sim_id}/stop")

