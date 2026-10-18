"""
Unit and integration tests for SUMO Microscopic Traffic Simulation and TraCI controls.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile

from main import app
from app.simulation.network_builder import find_sumo_binary, SumoNetworkBuilder
from app.simulation.traci_manager import SimulationSession
from app.simulation.scenario_comparator import ScenarioComparator
from app.models.schemas import SimulationMetrics

client = TestClient(app)


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
        result = builder.build(
            segments=[],
            duration_seconds=300,
            demand_rate_veh_hr=2000,
        )
        assert Path(result["net_file"]).is_file()
        assert Path(result["cfg_file"]).is_file()
        assert Path(result["rou_file"]).is_file()
        assert result["edge_count"] > 0
        assert result["junction_count"] > 0
        assert result["signal_count"] >= 1


def test_simulation_session_lifecycle():
    """Verify SimulationSession lifecycle: ready -> start -> step -> pause -> reset -> stop."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        meta = builder.build(segments=[], duration_seconds=120)

        session = SimulationSession(
            sim_id="test_sim_lifecycle",
            analysis_id="test_analysis_123",
            work_dir=Path(tmp_dir),
            cfg_file=Path(meta["cfg_file"]),
            duration_seconds=120,
            demand_rate_veh_hr=1500,
            strategy="actuated_adaptive",
            edge_count=meta["edge_count"],
            junction_count=meta["junction_count"],
            signal_count=meta["signal_count"],
        )

        assert session.state == "ready"
        session.start()
        assert session.state == "running"

        status_after_step = session.step(num_steps=3)
        assert status_after_step["step"] == 3
        assert status_after_step["elapsed_seconds"] > 0
        assert len(status_after_step["vehicles"]) > 0
        assert status_after_step["current_metrics"]["avg_speed_kmh"] > 0

        session.pause()
        assert session.state == "paused"

        session.reset()
        assert session.state == "ready"
        assert session.step_count == 0
        assert session.elapsed_seconds == 0.0

        session.stop()


def test_scenario_comparator():
    """Verify ScenarioComparator computes correct variances and improvement indicators."""
    baseline = SimulationMetrics(
        avg_speed_kmh=18.0,
        avg_waiting_time_s=80.0,
        avg_queue_length_m=120.0,
        completed_vehicles=400,
    )
    optimized = SimulationMetrics(
        avg_speed_kmh=27.0,
        avg_waiting_time_s=40.0,
        avg_queue_length_m=60.0,
        completed_vehicles=500,
    )

    res = ScenarioComparator.compare(
        sim_id="sim_comp_test",
        analysis_id="analysis_comp_test",
        duration_seconds=600,
        baseline_metrics=baseline,
        optimized_metrics=optimized,
    )

    assert res.sim_id == "sim_comp_test"
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


def test_simulation_api_endpoints():
    """Verify HTTP API endpoints for simulation preparation, step, and comparison."""
    # 1. Prepare
    prep_resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "test_endpoint_analysis",
            "duration_seconds": 600,
            "demand_rate_veh_hr": 2840,
            "strategy": "actuated_adaptive",
        },
    )
    assert prep_resp.status_code == 201
    sim_data = prep_resp.json()
    sim_id = sim_data["sim_id"]
    assert sim_data["state"] == "ready"
    assert sim_data["edge_count"] > 0
    assert sim_data["junction_count"] > 0

    # 2. Get Status
    status_resp = client.get(f"/api/simulations/{sim_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["sim_id"] == sim_id

    # 3. Start
    start_resp = client.post(f"/api/simulations/{sim_id}/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["state"] == "running"

    # 4. Step
    step_resp = client.post(f"/api/simulations/{sim_id}/step?steps=2")
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["step"] == 2
    assert len(step_data["vehicles"]) > 0

    # 5. Comparison
    comp_resp = client.get(f"/api/simulations/{sim_id}/comparison")
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert len(comp_data["rows"]) == 4
    assert comp_data["baseline_strategy"] != ""
    assert comp_data["optimized_strategy"] != ""

    # 6. Stop
    stop_resp = client.post(f"/api/simulations/{sim_id}/stop")
    assert stop_resp.status_code == 200
