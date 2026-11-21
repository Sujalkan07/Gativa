import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from main import app
from app.simulation.network_builder import SumoNetworkBuilder, interpret_lane_configuration


def test_interpret_lane_configuration():
    """Verify robust interpretation of lane configurations."""
    # 1. Explicit directional lanes
    fwd, bwd, is_est = interpret_lane_configuration(
        total_lanes=4, lanes_forward=3, lanes_backward=1, is_oneway=False, road_class="primary"
    )
    assert (fwd, bwd) == (3, 1)
    assert is_est is False

    # 2. One-way road with 2 lanes
    fwd2, bwd2, is_est2 = interpret_lane_configuration(
        total_lanes=2, lanes_forward=None, lanes_backward=None, is_oneway=True, road_class="secondary"
    )
    assert (fwd2, bwd2) == (2, 0)
    assert is_est2 is False

    # 3. Two-way road with 4 total lanes
    fwd3, bwd3, is_est3 = interpret_lane_configuration(
        total_lanes=4, lanes_forward=None, lanes_backward=None, is_oneway=False, road_class="tertiary"
    )
    assert (fwd3, bwd3) == (2, 2)
    assert is_est3 is False

    # 4. Unknown/missing lanes inferred from road class
    fwd4, bwd4, is_est4 = interpret_lane_configuration(
        total_lanes=None, lanes_forward=None, lanes_backward=None, is_oneway=False, road_class="motorway"
    )
    assert fwd4 >= 2
    assert is_est4 is True


def test_external_road_buffer_and_geometry():
    """Verify external buffer generation and network geometry extraction."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        polygon = [
            [77.5900, 12.9700],
            [77.6000, 12.9700],
            [77.6000, 12.9800],
            [77.5900, 12.9800],
            [77.5900, 12.9700],
        ]
        segments = [
            {
                "segment_id": "seg_1",
                "name": "Main Street",
                "road_type": "primary",
                "lanes": 4,
                "speed_limit_kmh": 50.0,
                "is_oneway": False,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5910, 12.9750], [77.5990, 12.9750]],
                },
                "u": 101,
                "v": 102,
            },
            {
                "segment_id": "seg_2",
                "name": "Cross Avenue",
                "road_type": "secondary",
                "lanes": 2,
                "speed_limit_kmh": 40.0,
                "is_oneway": False,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5950, 12.9710], [77.5950, 12.9790]],
                },
                "u": 201,
                "v": 202,
            },
        ]

        meta = builder.build(
            segments=segments,
            duration_seconds=300,
            demand_rate_veh_hr=1200,
            polygon_coords=polygon,
            external_buffer_m=500.0,
        )

        assert meta["edge_count"] > 0
        assert meta["junction_count"] > 0
        assert meta["external_buffer_distance_m"] == 500.0
        assert "network_geometry" in meta
        geom = meta["network_geometry"]
        assert len(geom["edges"]) > 0
        assert len(geom["junctions"]) > 0
        assert geom["summary"]["total_edges"] > 0
        assert geom["summary"]["total_lanes"] > 0


def test_road_network_api_endpoints():
    """Verify FastAPI endpoints for road network, road-detail, and junction-detail."""
    client = TestClient(app)

    # 1. Prepare simulation in network mode
    prep_resp = client.post(
        "/api/simulations/prepare",
        json={
            "analysis_id": "synth_net_test",
            "duration_seconds": 180,
            "demand_rate_veh_hr": 1500,
            "strategy": "actuated_adaptive",
            "is_synthetic_demo": True,
            "target_mode": "network",
            "external_buffer_m": 500.0,
        },
    )
    assert prep_resp.status_code == 201
    sim_data = prep_resp.json()
    sim_id = sim_data["sim_id"]

    # 2. Query Road Network Geometry
    net_resp = client.get(f"/api/simulations/{sim_id}/network")
    assert net_resp.status_code == 200
    net_data = net_resp.json()
    assert net_data["sim_id"] == sim_id
    assert "edges" in net_data
    assert "junctions" in net_data
    assert "summary" in net_data

    # 3. Step simulation to generate telemetry and verify start/step
    step_resp = client.post(f"/api/simulations/{sim_id}/step", params={"steps": 5})
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["step"] >= 5

    # 4. If edges exist, test road detail endpoint
    if net_data["edges"]:
        edge_id = net_data["edges"][0].get("edge_id") or net_data["edges"][0]["id"]
        rd_resp = client.get(f"/api/simulations/{sim_id}/road-detail/{edge_id}")
        assert rd_resp.status_code == 200
        rd_data = rd_resp.json()
        assert rd_data["edge_id"] == edge_id
        assert "speed_limit_kmh" in rd_data

    # 5. If junctions exist, test junction detail endpoint
    if net_data["junctions"]:
        junc_id = net_data["junctions"][0].get("junction_id") or net_data["junctions"][0]["id"]
        jd_resp = client.get(f"/api/simulations/{sim_id}/junction-detail/{junc_id}")
        assert jd_resp.status_code == 200
        jd_data = jd_resp.json()
        assert jd_data["junction_id"] == junc_id

    # 6. Clean stop
    stop_resp = client.post(f"/api/simulations/{sim_id}/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["state"] == "stopped"


def test_is_oneway_osm_conformance():
    """Verify OSM oneway specification handling: 'no' must be bidirectional, roundabouts one-way."""
    from app.geospatial.road_network import _is_oneway

    assert _is_oneway({"oneway": "yes"}) is True
    assert _is_oneway({"oneway": "1"}) is True
    assert _is_oneway({"oneway": "-1"}) is True
    assert _is_oneway({"oneway": ["yes"]}) is True

    # Critical: string 'no' must NEVER be parsed as truthy!
    assert _is_oneway({"oneway": "no"}) is False
    assert _is_oneway({"oneway": "0"}) is False
    assert _is_oneway({"oneway": "false"}) is False
    assert _is_oneway({"oneway": False}) is False

    # Roundabouts and motorways
    assert _is_oneway({"junction": "roundabout"}) is True
    assert _is_oneway({"highway": "motorway"}) is True
    assert _is_oneway({"highway": "residential"}) is False


def test_no_synthetic_perimeter_ring_and_clean_boundary_extensions():
    """Verify that buffer generation never generates an artificial circular perimeter ring."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        builder = SumoNetworkBuilder(Path(tmp_dir))
        polygon = [
            [77.5900, 12.9700],
            [77.6000, 12.9700],
            [77.6000, 12.9800],
            [77.5900, 12.9800],
            [77.5900, 12.9700],
        ]
        # Road extending to and crossing the boundary
        boundary_segments = [
            {
                "segment_id": "seg_arterial_1",
                "name": "Mahatma Gandhi Road",
                "road_type": "arterial",
                "lanes": 2,
                "speed_limit_kmh": 50.0,
                "is_oneway": False,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.5950, 12.9750], [77.6000, 12.9750]],  # Reaches boundary at 77.6000
                },
                "u": 1,
                "v": 2,
            }
        ]

        meta = builder.build(
            segments=boundary_segments,
            duration_seconds=120,
            polygon_coords=polygon,
            external_buffer_m=500.0,
        )

        edges = meta["network_geometry"]["edges"]
        # Must NOT contain any fabricated perimeter ring
        ring_edges = [e for e in edges if "buf_ring" in e["id"]]
        assert len(ring_edges) == 0, "Network must not contain artificial perimeter ring connectors"

        # Bounds must encompass both polygon and road network
        bounds = meta["network_geometry"]["bounds"]
        assert bounds[0] <= 77.5900
        assert bounds[1] <= 12.9700
        assert bounds[2] >= 77.6000
        assert bounds[3] >= 12.9800

        # Diagnostics validation must be present
        diag = meta["network_geometry"]["diagnostics"]
        assert "validation" in diag
        assert diag["validation"]["polygon_valid"] is True
        assert diag["validation"]["connected_components"] >= 1

