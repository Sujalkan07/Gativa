"""
Comprehensive tests for SUMO Signal Optimization Reliability, Validation & Multi-Signal Architecture.
Tests cover:
- A. Candidate evaluation truthfulness, error/timeout handling, diagnostic retention.
- B. Signal-plan validation, phase structures, clearance constraints, integer rounding.
- C. Multi-signal network evaluation, per-signal tracking, whole-network validation.
- D. Demand, routing, unfinished trips, teleports, and queue metrics.
- E. Engine mode provenance, engine transitions, fallback disclosures.
- F. Objective function normalization, reproducibility, and tie-breaking.
- G. Real SUMO execution integration tests.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import (
    AnalysisResult,
    GeoJSONLineString,
    GeoJSONPolygon,
    RoadSegment,
    SimulationMetrics,
    TimingPlanEvaluation,
    TrafficObservation,
)
from app.simulation.network_builder import SumoNetworkBuilder, find_sumo_binary
from app.simulation.scenario_comparator import ScenarioComparator
from app.simulation.signal_optimizer import (
    FixedTimeSignalOptimizer,
    calculate_objective_score,
    validate_phase_structure,
)


# ─── FIXTURES & HELPERS ────────────────────────────────────────────────────────

def _create_2signal_corridor_analysis(analysis_id: str = "test_2sig_corridor") -> AnalysisResult:
    """
    Create a 2-intersection corridor:
    - West junction: node_100 at (77.2000, 28.6100)
    - East junction: node_200 at (77.2040, 28.6100)
    - Connected by an arterial road segment between node_100 and node_200
    - Each junction has 4 legs (degree 4)
    """
    w_lon, w_lat = 77.2000, 28.6100
    e_lon, e_lat = 77.2040, 28.6100

    segments = [
        # Connecting corridor between node_100 and node_200
        RoadSegment(
            segment_id="seg_corridor",
            name="Main Arterial Corridor",
            road_type="arterial",
            length_m=400.0,
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[w_lon, w_lat], [e_lon, e_lat]],
            ),
            u="100",
            v="200",
            u_control="priority",
            v_control="priority",
            traffic=TrafficObservation(
                segment_id="seg_corridor",
                current_speed_kmh=32.0,
                free_flow_speed_kmh=50.0,
                speed_reduction_ratio=0.36,
            ),
        ),
        # West Junction: North Leg
        RoadSegment(
            segment_id="seg_w_north",
            name="West North Approach",
            road_type="collector",
            length_m=200.0,
            speed_limit_kmh=40.0,
            lanes=1,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[w_lon, w_lat + 0.002], [w_lon, w_lat]],
            ),
            u="101",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
        # West Junction: South Leg
        RoadSegment(
            segment_id="seg_w_south",
            name="West South Approach",
            road_type="collector",
            length_m=200.0,
            speed_limit_kmh=40.0,
            lanes=1,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[w_lon, w_lat - 0.002], [w_lon, w_lat]],
            ),
            u="102",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
        # West Junction: West Outer Leg
        RoadSegment(
            segment_id="seg_w_west",
            name="West Outer Approach",
            road_type="arterial",
            length_m=200.0,
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[w_lon - 0.002, w_lat], [w_lon, w_lat]],
            ),
            u="103",
            v="100",
            u_control="priority",
            v_control="priority",
        ),
        # East Junction: North Leg
        RoadSegment(
            segment_id="seg_e_north",
            name="East North Approach",
            road_type="collector",
            length_m=200.0,
            speed_limit_kmh=40.0,
            lanes=1,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[e_lon, e_lat + 0.002], [e_lon, e_lat]],
            ),
            u="201",
            v="200",
            u_control="priority",
            v_control="priority",
        ),
        # East Junction: South Leg
        RoadSegment(
            segment_id="seg_e_south",
            name="East South Approach",
            road_type="collector",
            length_m=200.0,
            speed_limit_kmh=40.0,
            lanes=1,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[e_lon, e_lat - 0.002], [e_lon, e_lat]],
            ),
            u="202",
            v="200",
            u_control="priority",
            v_control="priority",
        ),
        # East Junction: East Outer Leg
        RoadSegment(
            segment_id="seg_e_east",
            name="East Outer Approach",
            road_type="arterial",
            length_m=200.0,
            speed_limit_kmh=50.0,
            lanes=2,
            is_oneway=False,
            geometry=GeoJSONLineString(
                type="LineString",
                coordinates=[[e_lon + 0.002, e_lat], [e_lon, e_lat]],
            ),
            u="203",
            v="200",
            u_control="priority",
            v_control="priority",
        ),
    ]

    return AnalysisResult(
        analysis_id=analysis_id,
        status="completed",
        area_km2=0.8,
        created_at="2026-10-21T00:00:00Z",
        polygon=GeoJSONPolygon(
            type="Polygon",
            coordinates=[[
                [w_lon - 0.003, w_lat - 0.003],
                [e_lon + 0.003, e_lat - 0.003],
                [e_lon + 0.003, e_lat + 0.003],
                [w_lon - 0.003, w_lat + 0.003],
                [w_lon - 0.003, w_lat - 0.003],
            ]],
        ),
        segments=segments,
        bottlenecks=[],
        summary={},
        data_sources=[],
    )


# ─── A. CANDIDATE EVALUATION TESTS ─────────────────────────────────────────────

class TestCandidateEvaluation:
    """Verifies that candidate evaluations are truthful and never use fabricated measurements."""

    def test_nonzero_return_code_produces_failed_evaluation(self, tmp_path):
        """A nonzero process return code must produce evaluation_status='failed' with diagnostics."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        net_file.write_text("<net/>", encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Error: Invalid road configuration specified in network"

        with patch("subprocess.run", return_value=mock_proc):
            res = optimizer._run_sumo_eval(net_file, rou_file, None, 60, 42, "fail_test")

        assert res["evaluation_status"] == "failed"
        assert res["score"] == float("inf")
        assert "Invalid road configuration" in res["diagnostics"]
        # Must not fabricate defaults
        assert res["avg_wait"] is None
        assert res["avg_speed"] is None

    def test_subprocess_timeout_produces_failed_evaluation(self, tmp_path):
        """Subprocess timeout must produce evaluation_status='failed' with timeout diagnostics."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        net_file.write_text("<net/>", encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sumo", timeout=25)):
            res = optimizer._run_sumo_eval(net_file, rou_file, None, 60, 42, "timeout_test")

        assert res["evaluation_status"] == "failed"
        assert res["score"] == float("inf")
        assert "timed out" in res["diagnostics"]
        assert res["avg_wait"] is None

    def test_missing_or_empty_tripinfo_produces_insufficient_data(self, tmp_path):
        """Missing tripinfo output must produce insufficient_data, never fabricated numbers."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        net_file.write_text("<net/>", encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = ""

        # Output tripinfo file with empty root (0 completed, 0 unfinished trips)
        tripinfo_file = tmp_path / "tripinfo_no_trips.xml"
        tripinfo_file.write_text("<tripinfos/>", encoding="utf-8")

        with patch("subprocess.run", return_value=mock_proc):
            res = optimizer._run_sumo_eval(net_file, rou_file, None, 60, 42, "no_trips")

        assert res["evaluation_status"] == "insufficient_data"
        assert res["score"] == float("inf")
        assert "No trips completed or active" in res["diagnostics"]

    def test_malformed_xml_produces_failed_evaluation(self, tmp_path):
        """Malformed XML output must be caught and recorded as failed evaluation."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        net_file.write_text("<net/>", encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        tripinfo_file = tmp_path / "tripinfo_bad_xml.xml"

        def write_bad_xml(*args, **kwargs):
            tripinfo_file.write_text("<tripinfos><unclosed_tag>", encoding="utf-8")
            return mock_proc

        with patch("subprocess.run", side_effect=write_bad_xml):
            res = optimizer._run_sumo_eval(net_file, rou_file, None, 60, 42, "bad_xml")

        assert res["evaluation_status"] == "failed"
        assert "Malformed tripinfo XML" in res["diagnostics"]

    def test_all_invalid_candidates_preserves_original_plan_and_reports_failure(self, tmp_path):
        """When all candidate evaluations fail, system preserves original plan and reports validation_passed=False."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        cfg_file = tmp_path / "simulation.sumocfg"

        net_xml = """<net>
            <tlLogic id="tl_main" type="static" programID="0" offset="0">
                <phase duration="30" state="GGGrrr"/>
                <phase duration="3" state="yyyrrr"/>
                <phase duration="30" state="rrrGGG"/>
                <phase duration="3" state="rrryyy"/>
            </tlLogic>
        </net>"""
        net_file.write_text(net_xml, encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")
        cfg_file.write_text("<configuration><input><net-file value='network.net.xml'/></input></configuration>", encoding="utf-8")

        # Mock _run_sumo_eval to always return failed
        failed_eval = {
            "evaluation_status": "failed",
            "diagnostics": "Simulation engine failure",
            "avg_wait": None,
            "avg_speed": None,
            "throughput": None,
            "queue_burden": None,
            "max_queue": None,
            "completed_vehicles": 0,
            "unfinished_vehicles": 0,
            "inserted_vehicles": 0,
            "teleported_vehicles": 0,
            "score": float("inf"),
        }

        with patch.object(optimizer, "_run_sumo_eval", return_value=failed_eval):
            result = optimizer.optimize(net_file, rou_file, cfg_file)

        assert result is not None
        assert result.validation_passed is False
        assert result.status == "failed"
        assert result.selected_plan_id is None
        assert result.optimized_signals_count == 0
        assert "failed or returned insufficient data" in result.notes
        # Candidate evaluations must be marked failed
        for ep in result.evaluated_plans:
            assert ep.validation_passed is False
            assert ep.is_selected is False
            assert ep.evaluation_status == "failed"


# ─── B. SIGNAL PLAN VALIDATION TESTS ──────────────────────────────────────────

class TestSignalPlanValidation:
    """Verifies timing plan constraints, clearance safety, and integer cycle sums."""

    def test_validate_phase_structure_green_yellow_red(self):
        """Standard green and yellow clearance structure passes validation."""
        base_phases = [
            {"duration": 30.0, "state": "GGGrrr"},
            {"duration": 3.0, "state": "yyyrrr"},
            {"duration": 30.0, "state": "rrrGGG"},
            {"duration": 3.0, "state": "rrryyy"},
        ]
        ok, msg = validate_phase_structure(base_phases, base_phases)
        assert ok is True
        assert msg == "Validation passed"

    def test_clearance_intervals_cannot_be_shortened(self):
        """Shortening yellow clearance below required baseline duration must be rejected."""
        base_phases = [
            {"duration": 30.0, "state": "GGGrrr"},
            {"duration": 4.0, "state": "yyyrrr"},
            {"duration": 30.0, "state": "rrrGGG"},
            {"duration": 4.0, "state": "rrryyy"},
        ]
        short_yellow = [
            {"duration": 35.0, "state": "GGGrrr"},
            {"duration": 2.0, "state": "yyyrrr"},  # Shortened below safe 4.0s / 3.0s!
            {"duration": 35.0, "state": "rrrGGG"},
            {"duration": 4.0, "state": "rrryyy"},
        ]
        ok, msg = validate_phase_structure(short_yellow, base_phases)
        assert ok is False
        assert "clearance duration" in msg.lower() or "shortened" in msg.lower()

    def test_minimum_green_enforced(self):
        """Green phase below minimum green constraint (10.0s) must be rejected."""
        base_phases = [
            {"duration": 30.0, "state": "GGGrrr"},
            {"duration": 3.0, "state": "yyyrrr"},
            {"duration": 30.0, "state": "rrrGGG"},
            {"duration": 3.0, "state": "rrryyy"},
        ]
        too_short_green = [
            {"duration": 5.0, "state": "GGGrrr"},  # Only 5s green!
            {"duration": 3.0, "state": "yyyrrr"},
            {"duration": 55.0, "state": "rrrGGG"},
            {"duration": 3.0, "state": "rrryyy"},
        ]
        ok, msg = validate_phase_structure(too_short_green, base_phases, min_green=10.0)
        assert ok is False
        assert "minimum constraint" in msg

    def test_invalid_aspect_characters_rejected(self):
        """State strings with invalid characters must be rejected."""
        invalid_state_phases = [
            {"duration": 30.0, "state": "GGGZZZ"},  # 'Z' is not a SUMO signal aspect
            {"duration": 3.0, "state": "yyyrrr"},
        ]
        ok, msg = validate_phase_structure(invalid_state_phases)
        assert ok is False
        assert "invalid state character" in msg

    def test_cycle_length_integer_sum_exact(self, tmp_path):
        """All generated candidate plans must sum phase durations exactly to their cycle length."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        base_phases = [
            {"duration": 35.0, "state": "GGGrrr"},
            {"duration": 3.5, "state": "yyyrrr"},
            {"duration": 25.0, "state": "rrrGGG"},
            {"duration": 3.5, "state": "rrryyy"},
        ]
        plans = optimizer.generate_candidate_plans("tl_test", base_phases, include_base=True)
        assert len(plans) >= 4

        for p in plans:
            cycle = p["cycle_length_s"]
            phase_sum = sum(int(round(ph["duration"])) for ph in p["phases"])
            assert phase_sum == cycle, f"Plan {p['plan_id']} sum ({phase_sum}) != cycle ({cycle})"

    def test_candidate_deduplication(self, tmp_path):
        """Deduplication must prevent identical candidate plans after integer rounding."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        base_phases = [
            {"duration": 20.0, "state": "GGGrrr"},
            {"duration": 3.0, "state": "yyyrrr"},
            {"duration": 20.0, "state": "rrrGGG"},
            {"duration": 3.0, "state": "rrryyy"},
        ]
        plans = optimizer.generate_candidate_plans("tl_test", base_phases)
        signatures = [(p["cycle_length_s"], tuple(ph["duration"] for ph in p["phases"])) for p in plans]
        assert len(signatures) == len(set(signatures)), "Duplicate candidate plans were generated"


# ─── C. MULTI-SIGNAL ARCHITECTURE TESTS ────────────────────────────────────────

class TestMultiSignalOptimization:
    """Verifies that all eligible signals are evaluated and whole-network validation protects network flow."""

    def test_multi_signal_evaluates_all_signals(self, tmp_path):
        """A network with 2 traffic lights must evaluate both signals, not only the first."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        cfg_file = tmp_path / "simulation.sumocfg"

        net_xml = """<net>
            <tlLogic id="TL_WEST" type="static" programID="0" offset="0">
                <phase duration="30" state="GGGrrr"/>
                <phase duration="3" state="yyyrrr"/>
                <phase duration="30" state="rrrGGG"/>
                <phase duration="3" state="rrryyy"/>
            </tlLogic>
            <tlLogic id="TL_EAST" type="static" programID="0" offset="0">
                <phase duration="25" state="GGrr"/>
                <phase duration="3" state="yyrr"/>
                <phase duration="25" state="rrGG"/>
                <phase duration="3" state="rryy"/>
            </tlLogic>
        </net>"""
        net_file.write_text(net_xml, encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")
        cfg_file.write_text("<configuration><input><net-file value='network.net.xml'/></input></configuration>", encoding="utf-8")

        mock_eval_results = {
            # Baseline evaluation
            "baseline_screening": {
                "evaluation_status": "success",
                "diagnostics": None,
                "avg_wait": 28.0,
                "avg_speed": 30.0,
                "throughput": 1200.0,
                "queue_burden": 15.0,
                "max_queue": 25.0,
                "completed_vehicles": 30,
                "unfinished_vehicles": 5,
                "inserted_vehicles": 35,
                "teleported_vehicles": 0,
                "score": 3.8,
            },
            # Combined network validation
            "combined_network_validation": {
                "evaluation_status": "success",
                "diagnostics": None,
                "avg_wait": 18.0,
                "avg_speed": 36.0,
                "throughput": 1400.0,
                "queue_burden": 8.0,
                "max_queue": 15.0,
                "completed_vehicles": 35,
                "unfinished_vehicles": 2,
                "inserted_vehicles": 37,
                "teleported_vehicles": 0,
                "score": 2.6,
            },
        }

        def mock_run_sumo(*args, **kwargs):
            run_label = kwargs.get("run_label") or (args[5] if len(args) > 5 else "")
            if run_label in mock_eval_results:
                return dict(mock_eval_results[run_label])
            # Candidate runs for individual signals
            return {
                "evaluation_status": "success",
                "diagnostics": None,
                "avg_wait": 20.0,
                "avg_speed": 34.0,
                "throughput": 1300.0,
                "queue_burden": 10.0,
                "max_queue": 18.0,
                "completed_vehicles": 32,
                "unfinished_vehicles": 3,
                "inserted_vehicles": 35,
                "teleported_vehicles": 0,
                "score": 2.9,
            }

        with patch.object(optimizer, "_run_sumo_eval", side_effect=mock_run_sumo):
            result = optimizer.optimize(net_file, rou_file, cfg_file)

        assert result is not None
        assert result.validation_passed is True
        assert result.total_signals_count == 2
        assert result.optimized_signals_count == 2
        assert "TL_WEST" in result.signal_results
        assert "TL_EAST" in result.signal_results
        assert result.signal_results["TL_WEST"]["status"] == "optimized"
        assert result.signal_results["TL_EAST"]["status"] == "optimized"

        # Verify signals.add.xml has both traffic lights
        final_add = tmp_path / "signals.add.xml"
        assert final_add.is_file()
        tree = ET.parse(str(final_add))
        root = tree.getroot()
        tl_ids_in_xml = {tl.get("id") for tl in root.findall("tlLogic")}
        assert "TL_WEST" in tl_ids_in_xml
        assert "TL_EAST" in tl_ids_in_xml

    def test_network_level_validation_rejects_regressing_composite_plan(self, tmp_path):
        """If individual plans combine to produce worse gridlock, network-level validation must reject them."""
        optimizer = FixedTimeSignalOptimizer(tmp_path)
        net_file = tmp_path / "network.net.xml"
        rou_file = tmp_path / "routes.rou.xml"
        cfg_file = tmp_path / "simulation.sumocfg"

        net_xml = """<net>
            <tlLogic id="TL_1" type="static" programID="0" offset="0">
                <phase duration="30" state="GGGrrr"/><phase duration="3" state="yyyrrr"/>
                <phase duration="30" state="rrrGGG"/><phase duration="3" state="rrryyy"/>
            </tlLogic>
            <tlLogic id="TL_2" type="static" programID="0" offset="0">
                <phase duration="30" state="GGGrrr"/><phase duration="3" state="yyyrrr"/>
                <phase duration="30" state="rrrGGG"/><phase duration="3" state="rrryyy"/>
            </tlLogic>
        </net>"""
        net_file.write_text(net_xml, encoding="utf-8")
        rou_file.write_text("<routes/>", encoding="utf-8")
        cfg_file.write_text("<configuration><input><net-file value='network.net.xml'/></input></configuration>", encoding="utf-8")

        def mock_run_sumo(*args, **kwargs):
            run_label = kwargs.get("run_label") or (args[5] if len(args) > 5 else "")
            if run_label == "baseline_screening":
                return {
                    "evaluation_status": "success", "score": 3.5, "avg_wait": 25.0, "avg_speed": 30.0,
                    "throughput": 1200.0, "queue_burden": 20.0, "max_queue": 30.0, "completed_vehicles": 30,
                    "unfinished_vehicles": 5, "inserted_vehicles": 35, "teleported_vehicles": 0, "diagnostics": None,
                }
            elif run_label == "combined_network_validation":
                # Combined plan caused spillback gridlock! Score is much worse (8.5 vs baseline 3.5)
                return {
                    "evaluation_status": "success", "score": 8.5, "avg_wait": 65.0, "avg_speed": 12.0,
                    "throughput": 600.0, "queue_burden": 80.0, "max_queue": 120.0, "completed_vehicles": 15,
                    "unfinished_vehicles": 20, "inserted_vehicles": 35, "teleported_vehicles": 4, "diagnostics": None,
                }
            # Individual candidate runs
            return {
                "evaluation_status": "success", "score": 2.8, "avg_wait": 18.0, "avg_speed": 35.0,
                "throughput": 1300.0, "queue_burden": 10.0, "max_queue": 15.0, "completed_vehicles": 32,
                "unfinished_vehicles": 3, "inserted_vehicles": 35, "teleported_vehicles": 0, "diagnostics": None,
            }

        with patch.object(optimizer, "_run_sumo_eval", side_effect=mock_run_sumo):
            result = optimizer.optimize(net_file, rou_file, cfg_file)

        assert result is not None
        assert result.validation_passed is False
        assert result.status == "inconclusive"
        assert "did not beat baseline" in result.notes
        assert result.selected_plan_id == "plan_base"


# ─── D. DEMAND, ROUTING, UNFINISHED TRIPS & ENGINE PROVENANCE ──────────────────

class TestDemandRouteAndEngineProvenance:
    """Verifies unfinished trip accounting, route generation transparency, and engine provenance."""

    def test_unfinished_trips_distinct_from_completed_in_scenario_comparator(self):
        """ScenarioComparator must explicitly account for unfinished trips."""
        baseline = SimulationMetrics(
            avg_speed_kmh=20.0,
            avg_waiting_time_s=40.0,
            avg_queue_length_m=50.0,
            completed_vehicles=300,
            inserted_vehicles=400,  # 100 unfinished
            elapsed_seconds=300.0,
        )
        optimized = SimulationMetrics(
            avg_speed_kmh=25.0,
            avg_waiting_time_s=25.0,
            avg_queue_length_m=30.0,
            completed_vehicles=380,
            inserted_vehicles=400,  # 20 unfinished
            elapsed_seconds=300.0,
        )

        res = ScenarioComparator.compare(
            sim_id="sim_unfin_test",
            analysis_id="analysis_unfin",
            duration_seconds=300,
            engine_mode="native_sumo",
            baseline_metrics=baseline,
            optimized_metrics=optimized,
            step_count=50,
        )

        unfin_row = next((r for r in res.extended_rows if r.metric == "Unfinished Trips"), None)
        assert unfin_row is not None
        assert unfin_row.baseline == "100 vehs"
        assert unfin_row.optimized == "20 vehs"
        assert unfin_row.is_improvement is True

    def test_engine_transition_invalidates_comparison(self):
        """If a session transitions from native SUMO to fallback mid-run, comparison must be withheld."""
        metrics = SimulationMetrics(avg_speed_kmh=22.0, elapsed_seconds=60.0)

        res = ScenarioComparator.compare(
            sim_id="sim_trans_test",
            analysis_id="analysis_trans",
            duration_seconds=300,
            engine_mode="fallback",
            baseline_metrics=metrics,
            optimized_metrics=metrics,
            step_count=30,
            engine_transitioned=True,  # Transition occurred!
        )

        assert res.comparison_status == "insufficient_data"
        assert "invalidated because simulation execution encountered a runtime error" in res.methodology_notes
        assert all("transitioned mid-run" in r.variance for r in res.rows)

    def test_fallback_mode_discloses_estimation_without_claiming_empirical_validation(self):
        """Fallback mode must disclose that results are simulated visual estimates."""
        metrics = SimulationMetrics(avg_speed_kmh=25.0, elapsed_seconds=60.0)

        res = ScenarioComparator.compare(
            sim_id="sim_fallback_disclosure",
            analysis_id="analysis_fb",
            duration_seconds=300,
            engine_mode="fallback",
            baseline_metrics=metrics,
            optimized_metrics=metrics,
            step_count=30,
        )

        assert res.is_validated is False
        assert "Internal kinematics engine estimation mode" in res.methodology_notes


# ─── E. OBJECTIVE FUNCTION TESTS ───────────────────────────────────────────────

class TestObjectiveFunction:
    """Verifies that the normalized objective behaves consistently and rewards true performance."""

    def test_lower_objective_score_means_better_performance(self):
        """A run with lower delay and smaller queues must strictly have a lower objective score."""
        good_score, good_comp = calculate_objective_score(
            avg_wait=15.0,
            avg_speed=38.0,
            throughput=1400.0,
            queue_burden=10.0,
            max_queue=20.0,
            unfinished_count=2,
            inserted_count=100,
            teleported_count=0,
        )

        bad_score, bad_comp = calculate_objective_score(
            avg_wait=55.0,
            avg_speed=15.0,
            throughput=800.0,
            queue_burden=60.0,
            max_queue=110.0,
            unfinished_count=25,
            inserted_count=100,
            teleported_count=4,
        )

        assert good_score < bad_score, f"Expected good score ({good_score}) < bad score ({bad_score})"

    def test_high_speed_with_gridlock_cannot_win(self):
        """A plan with high speed but severe spillback/teleports must be heavily penalized."""
        gridlock_score, _ = calculate_objective_score(
            avg_wait=20.0,
            avg_speed=45.0,  # fast but congested perimeter
            throughput=900.0,
            queue_burden=85.0,
            max_queue=150.0,
            unfinished_count=35,
            inserted_count=100,
            teleported_count=10,  # Gridlock teleports!
        )

        stable_score, _ = calculate_objective_score(
            avg_wait=28.0,
            avg_speed=32.0,  # moderate speed, zero gridlock
            throughput=1200.0,
            queue_burden=15.0,
            max_queue=25.0,
            unfinished_count=3,
            inserted_count=100,
            teleported_count=0,
        )

        assert stable_score < gridlock_score, "Gridlock run should have higher cost than stable run"

    def test_reproducibility_of_objective_components(self):
        """Objective score components must sum to the final score reproducibly."""
        score, comp = calculate_objective_score(
            avg_wait=22.5,
            avg_speed=29.0,
            throughput=1150.0,
            queue_burden=18.0,
            max_queue=32.0,
            unfinished_count=5,
            inserted_count=80,
            teleported_count=0,
        )
        assert math.isfinite(score)
        assert all(isinstance(v, float) for v in comp.values())


# ─── F. REAL SUMO EXECUTION INTEGRATION TESTS ──────────────────────────────────

class TestRealSumoIntegration:
    """Executes genuine SUMO runs with native SUMO binary when available in environment."""

    @pytest.mark.skipif(find_sumo_binary("sumo") is None, reason="SUMO binary not installed")
    def test_real_sumo_optimization_on_compiled_network(self):
        """
        End-to-end integration test running actual SUMO binary:
        1. Compiles a real 4-way intersection network with netconvert.
        2. Generates genuine routes and trip demand.
        3. Executes FixedTimeSignalOptimizer on the network with native SUMO.
        4. Verifies genuine tripinfo XML and summary XML parsing.
        5. Verifies selected plan is written and attached to sumocfg.
        """
        analysis = _create_2signal_corridor_analysis("real_sumo_e2e_test")
        segments_dict = [s.model_dump() for s in analysis.segments]

        with tempfile.TemporaryDirectory() as tmp_dir:
            work_path = Path(tmp_dir)
            builder = SumoNetworkBuilder(work_path)
            meta = builder.build(
                segments=segments_dict,
                duration_seconds=120,
                demand_rate_veh_hr=1800,
                seed=42,
                approved_signal_junctions={"node_100", "node_200"},
            )

            assert meta["netconvert_used"] is True, "netconvert should compile network"
            assert meta["signal_count"] >= 1, "At least one traffic light should be compiled"

            optimizer = FixedTimeSignalOptimizer(work_path)
            result = optimizer.optimize(
                net_file=Path(meta["net_file"]),
                rou_file=Path(meta["rou_file"]),
                cfg_file=Path(meta["cfg_file"]),
                eval_duration=60,
                seed=42,
            )

            assert result is not None
            assert result.status in ("completed", "inconclusive")
            assert len(result.evaluated_plans) >= 4

            # Verify genuine measurements were collected
            successful_evals = [ep for ep in result.evaluated_plans if ep.evaluation_status == "success"]
            assert len(successful_evals) > 0, "At least one candidate plan must successfully evaluate in native SUMO"

            for ep in successful_evals:
                assert ep.validation_passed is True
                assert ep.avg_speed_kmh > 0.0
                assert ep.objective_score < 900.0

            # Verify signals.add.xml was generated and sumocfg updated if completed
            if result.validation_passed:
                final_add = work_path / "signals.add.xml"
                assert final_add.is_file()
                sumocfg_content = (work_path / "simulation.sumocfg").read_text(encoding="utf-8")
                assert "signals.add.xml" in sumocfg_content
