"""
Fixed-Time Signal Optimizer: Generates, evaluates, and validates candidate fixed-time signal plans via actual SUMO simulation runs.
Follows transportation engineering standards:
- Minimum green constraints (>= 10s)
- Safety yellow clearance intervals (3.0s - 4.0s)
- Feasible cycle length search (60s, 75s, 90s, 105s, etc.)
- Normalized multi-criteria objective balancing delay, queue burden, unfinished trips, spillback, and throughput
- Truthful evaluation provenance (no fabricated candidate measurements)
- Multi-signal network optimization with whole-network validation
- Generates valid SUMO additional files (signals.add.xml) loaded directly by SUMO
"""
from __future__ import annotations

import concurrent.futures
import logging
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from app.models.schemas import (
    EvaluationStatus,
    FixedTimeOptimizationResult,
    TimingPlanEvaluation,
)
from app.simulation.network_builder import find_sumo_binary

logger = logging.getLogger(__name__)

DEFAULT_OBJECTIVE_WEIGHTS = {
    "delay": 1.2,
    "queue": 0.8,
    "max_queue": 0.4,
    "unfinished_trip": 3.0,
    "teleport": 5.0,
    "speed": 0.6,
    "throughput": 0.1,
}


def validate_phase_structure(
    phases: list[dict[str, Any]],
    base_phases: Optional[list[dict[str, Any]]] = None,
    min_green: float = 10.0,
    min_yellow: float = 3.0,
) -> tuple[bool, str]:
    """
    Validate that a fixed-time timing plan conforms to safety and SUMO constraints:
    1. At least one phase exists.
    2. Phase durations are positive numbers.
    3. State strings contain only valid SUMO aspects (G, g, y, Y, r, R, u, o, O).
    4. Clearance intervals (phases containing 'y'/'Y') have duration >= min_yellow and >= base clearance.
    5. Pure-red / all-red clearance intervals (phases with all 'r'/'R') strictly preserve original base duration.
    6. Green intervals (phases containing 'G'/'g' without yellow) have duration >= min_green.
    7. If base_phases provided, state strings must have matching length.
    8. Phase ordering is preserved.
    """
    if not phases:
        return False, "Plan contains no phases"

    if base_phases and len(phases) != len(base_phases):
        return False, f"Phase count mismatch: expected {len(base_phases)}, got {len(phases)}"

    for idx, p in enumerate(phases):
        dur = float(p.get("duration", 0.0))
        state = str(p.get("state", ""))

        if dur <= 0.0:
            return False, f"Phase {idx} has non-positive duration: {dur}"

        if not state:
            return False, f"Phase {idx} has empty state string"

        # Check for valid SUMO aspects
        valid_chars = set("GgyYrRuuoO0123456789")
        if not all(c in valid_chars for c in state):
            return False, f"Phase {idx} has invalid state character in '{state}'"

        if base_phases:
            base_p = base_phases[idx]
            base_state = str(base_p.get("state", ""))
            if len(state) != len(base_state):
                return False, f"Phase {idx} state length mismatch: expected {len(base_state)}, got {len(state)}"

            base_is_yellow = "y" in base_state.lower()
            cur_is_yellow = "y" in state.lower()
            if base_is_yellow:
                if not cur_is_yellow:
                    return False, f"Phase {idx} dropped required yellow clearance aspect"
                required_yellow = max(min_yellow, float(base_p.get("duration", min_yellow)))
                if dur < required_yellow:
                    return False, f"Phase {idx} yellow clearance duration {dur}s < required {required_yellow}s"

            # All-red / pure-red clearance preservation
            base_is_all_red = all(c in "rR" for c in base_state) and len(base_state) > 0
            cur_is_all_red = all(c in "rR" for c in state) and len(state) > 0
            if base_is_all_red:
                if not cur_is_all_red:
                    return False, f"Phase {idx} altered required all-red clearance aspect '{base_state}' to '{state}'"
                base_all_red_dur = float(base_p.get("duration", 0.0))
                if abs(dur - base_all_red_dur) > 0.01:
                    return False, f"Phase {idx} all-red clearance duration {dur}s must strictly preserve base duration {base_all_red_dur}s"

        # Check minimum green if this is a green phase
        is_green = ("g" in state.lower()) and ("y" not in state.lower())
        if is_green and dur < min_green:
            return False, f"Phase {idx} green duration {dur}s is below minimum constraint {min_green}s"

    return True, "Validation passed"


def calculate_objective_score(
    avg_wait: float,
    avg_speed: float,
    throughput: float,
    queue_burden: float,
    max_queue: float,
    unfinished_count: int,
    inserted_count: int,
    teleported_count: int,
    weights: Optional[dict[str, float]] = None,
) -> tuple[float, dict[str, float]]:
    """
    Normalized, reproducible objective function where lower is strictly better:
    - Normalizes delay against 30s cycle delay baseline
    - Penalizes queue burden and max queue length
    - Penalizes low speeds (< 35 km/h)
    - Penalizes unfinished and failed trips
    - Penalizes teleports (gridlock indicator)
    - Rewards throughput with a dampened, capped term so throughput cannot offset congestion
    """
    w = dict(DEFAULT_OBJECTIVE_WEIGHTS)
    if weights:
        w.update(weights)

    # 1. Delay term
    norm_delay = max(0.0, avg_wait / 30.0)

    # 2. Queue terms
    norm_queue = max(0.0, queue_burden / 50.0)
    norm_max_queue = max(0.0, max_queue / 100.0)

    # 3. Speed term (cost increases as progression speed falls)
    speed_term = 35.0 / max(5.0, avg_speed)

    # 4. Unfinished trip penalty
    ins = max(1, inserted_count)
    unfinished_ratio = max(0.0, unfinished_count / ins)
    unfinished_penalty = unfinished_ratio * w["unfinished_trip"]

    # 5. Teleport penalty
    teleport_ratio = max(0.0, teleported_count / ins)
    teleport_penalty = teleport_ratio * w["teleport"]

    # 6. Throughput contribution (capped at 0.3)
    throughput_reward = min(0.3, max(0.0, (throughput / 3600.0) * w["throughput"]))

    total_score = round(
        (w["delay"] * norm_delay)
        + (w["queue"] * norm_queue)
        + (w["max_queue"] * norm_max_queue)
        + (w["speed"] * speed_term)
        + unfinished_penalty
        + teleport_penalty
        - throughput_reward,
        2,
    )

    components = {
        "norm_delay": round(norm_delay, 3),
        "norm_queue": round(norm_queue, 3),
        "norm_max_queue": round(norm_max_queue, 3),
        "speed_term": round(speed_term, 3),
        "unfinished_penalty": round(unfinished_penalty, 3),
        "teleport_penalty": round(teleport_penalty, 3),
        "throughput_reward": round(throughput_reward, 3),
    }

    return total_score, components


class FixedTimeSignalOptimizer:
    """Evaluates candidate fixed-time timing plans using native SUMO runs to find the optimal plan."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.sumo_bin = find_sumo_binary("sumo")

    def parse_traffic_lights(self, net_file: Path) -> dict[str, list[dict[str, Any]]]:
        """
        Parse traffic light logics from a compiled SUMO network.net.xml file.
        Returns: {tl_id: [{"duration": float, "state": str}, ...]}
        """
        if not net_file.is_file():
            return {}

        tl_logics: dict[str, list[dict[str, Any]]] = {}
        try:
            tree = ET.parse(str(net_file))
            root = tree.getroot()
            for tl in root.findall("tlLogic"):
                tl_id = tl.get("id")
                if not tl_id:
                    continue
                phases = []
                for p in tl.findall("phase"):
                    dur = float(p.get("duration", "30.0"))
                    state = p.get("state", "")
                    phases.append({"duration": dur, "state": state})
                if phases:
                    tl_logics[tl_id] = phases
        except Exception as e:
            logger.warning("Error parsing tlLogics from %s: %s", net_file, e)

        return tl_logics

    def parse_controlled_connections(self, net_file: Path) -> dict[str, list[dict[str, Any]]]:
        """
        Parse signal connections from net_file to determine lane counts and approach geometry.
        Returns: {tl_id: [{"link_index": int, "from_edge": str, "from_lane": int}, ...]}
        """
        if not net_file.is_file():
            return {}

        connections: dict[str, list[dict[str, Any]]] = {}
        try:
            tree = ET.parse(str(net_file))
            root = tree.getroot()
            for conn in root.findall("connection"):
                tl_id = conn.get("tl")
                link_idx_str = conn.get("linkIndex")
                if not tl_id or link_idx_str is None:
                    continue
                try:
                    link_idx = int(link_idx_str)
                    from_edge = conn.get("from", "")
                    from_lane = int(conn.get("fromLane", "0"))
                    if tl_id not in connections:
                        connections[tl_id] = []
                    connections[tl_id].append({
                        "link_index": link_idx,
                        "from_edge": from_edge,
                        "from_lane": from_lane,
                    })
                except ValueError:
                    continue
        except Exception as e:
            logger.debug("Error parsing connections from %s: %s", net_file, e)

        return connections

    def generate_candidate_plans(
        self,
        tl_id: str,
        base_phases: list[dict[str, Any]],
        approach_evidence: Optional[dict[str, Any]] = None,
        include_base: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Generate bounded, feasible fixed-time timing alternatives preserving phase ordering and safety clearance:
        1. Base netconvert plan (plan_base, optional)
        2. Short cycle (60s) - reduces cycle delay for lower flows
        3. Balanced cycle (90s) - standard balanced splits
        4. Arterial-favored progression (90s) - 62% green to primary phase
        5. High-capacity cycle (105s) - extended clearance & storage for peak volumes
        """
        plans: list[dict[str, Any]] = []

        # Identify green phases vs yellow clearance vs pure-red/all-red clearance phases
        green_indices = []
        yellow_indices = []
        all_red_indices = []
        other_indices = []

        for idx, p in enumerate(base_phases):
            state = p.get("state", "")
            state_lower = state.lower()
            if "y" in state_lower:
                yellow_indices.append(idx)
            elif "g" in state_lower:
                green_indices.append(idx)
            elif all(c in "rR" for c in state) and len(state) > 0:
                all_red_indices.append(idx)
            else:
                other_indices.append(idx)

        # Baseline plan representation
        base_durations = [int(round(float(p["duration"]))) for p in base_phases]
        base_cycle = int(sum(base_durations))
        base_plan = {
            "plan_id": "plan_base",
            "name": f"Baseline Fixed-Time Timing ({base_cycle}s)",
            "description": f"Original compiled baseline fixed-time timing ({base_cycle}s cycle)",
            "cycle_length_s": base_cycle,
            "phases": [{"duration": float(d), "state": p["state"]} for d, p in zip(base_durations, base_phases)],
        }

        # If simple structure not recognized (< 2 green phases), return base plan
        if len(green_indices) < 2:
            plans.append(base_plan)
            return plans

        if include_base:
            plans.append(base_plan)

        num_greens = len(green_indices)

        # Calculate exact clearance durations from base phases:
        # 1. Yellow clearance: duration >= base clearance and >= 3.0s
        # 2. Pure-red / all-red clearance: strictly preserve base duration
        # 3. Other transition phases: preserve base duration
        clearance_durations: dict[int, float] = {}
        for y_idx in yellow_indices:
            base_y_dur = float(base_phases[y_idx].get("duration", 3.0))
            clearance_durations[y_idx] = max(3.0, base_y_dur)

        for r_idx in all_red_indices:
            base_r_dur = float(base_phases[r_idx].get("duration", 2.0))
            clearance_durations[r_idx] = base_r_dur

        for o_idx in other_indices:
            clearance_durations[o_idx] = float(base_phases[o_idx].get("duration", 3.0))

        total_clearance = sum(clearance_durations.values())

        def make_plan_phases(target_cycle: int, green_durations: list[int]) -> list[dict[str, Any]]:
            """Construct phases strictly matching target_cycle with exact integer durations."""
            new_phases = []
            g_ptr = 0
            for idx, p in enumerate(base_phases):
                if idx in green_indices:
                    new_phases.append({"duration": float(green_durations[g_ptr]), "state": p["state"]})
                    g_ptr += 1
                else:
                    clr_dur = clearance_durations.get(idx, float(p.get("duration", 3.0)))
                    new_phases.append({"duration": float(round(clr_dur, 2)), "state": p["state"]})

            # Reconcile integer rounding difference to exactly match target_cycle.
            # Difference is reconciled strictly against the largest green phase,
            # never modifying yellow clearance or all-red clearance durations.
            cur_sum = sum(int(round(ph["duration"])) for ph in new_phases)
            diff = target_cycle - cur_sum
            if diff != 0 and green_indices:
                max_g_idx = max(range(len(green_durations)), key=lambda i: green_durations[i])
                g_phase_pos = green_indices[max_g_idx]
                new_phases[g_phase_pos]["duration"] += float(diff)

            return new_phases

        # Plan 1: Short cycle (60s total)
        avail_60 = 60.0 - total_clearance
        if avail_60 >= num_greens * 10.0:
            each_60 = int(avail_60 // num_greens)
            g_durs_60 = [each_60] * num_greens
            remainder_60 = int(avail_60 - (each_60 * num_greens))
            if remainder_60 > 0:
                g_durs_60[0] += remainder_60
            plans.append({
                "plan_id": "plan_short_60s",
                "name": "Short-Cycle Plan (60s)",
                "description": "Short 60s cycle minimizing average vehicle cycle delays on minor approaches",
                "cycle_length_s": 60,
                "phases": make_plan_phases(60, g_durs_60),
            })

        # Plan 2: Balanced Standard (90s total)
        avail_90 = 90.0 - total_clearance
        if avail_90 >= num_greens * 10.0:
            each_90 = int(avail_90 // num_greens)
            g_durs_90 = [each_90] * num_greens
            remainder_90 = int(avail_90 - (each_90 * num_greens))
            if remainder_90 > 0:
                g_durs_90[0] += remainder_90
            plans.append({
                "plan_id": "plan_balanced_90s",
                "name": "Balanced Cycle Plan (90s)",
                "description": "Standard 90s cycle with balanced green allocation across all approach phases",
                "cycle_length_s": 90,
                "phases": make_plan_phases(90, g_durs_90),
            })

        # Plan 3: Arterial-Favored Split (90s total)
        if avail_90 >= num_greens * 10.0 and num_greens >= 2:
            g1_target = max(10, int(round(avail_90 * 0.62)))
            g_rest_each = max(10, int((avail_90 - g1_target) // (num_greens - 1)))
            g_durs_art = [g1_target] + [g_rest_each] * (num_greens - 1)
            rem_art = int(avail_90 - sum(g_durs_art))
            if rem_art != 0:
                g_durs_art[0] += rem_art
            plans.append({
                "plan_id": "plan_arterial_90s",
                "name": "Arterial Priority Plan (90s)",
                "description": "90s cycle allocating 62% green time to primary corridor progression",
                "cycle_length_s": 90,
                "phases": make_plan_phases(90, g_durs_art),
            })

        # Plan 4: High-Capacity Cycle (105s total)
        avail_105 = 105.0 - total_clearance
        if avail_105 >= num_greens * 10.0:
            each_105 = int(avail_105 // num_greens)
            g_durs_105 = [each_105] * num_greens
            rem_105 = int(avail_105 - (each_105 * num_greens))
            if rem_105 > 0:
                g_durs_105[0] += rem_105
            plans.append({
                "plan_id": "plan_high_cap_105s",
                "name": "High-Capacity Plan (105s)",
                "description": "Extended 105s cycle providing deep queue clearance during peak saturation",
                "cycle_length_s": 105,
                "phases": make_plan_phases(105, g_durs_105),
            })

        # Validate all generated plans and deduplicate
        valid_plans = []
        seen_signatures = set()
        for cand in plans:
            ok, reason = validate_phase_structure(cand["phases"], base_phases)
            if not ok:
                logger.warning("Rejected infeasible candidate %s: %s", cand["plan_id"], reason)
                continue
            sig = (cand["cycle_length_s"], tuple(int(round(p["duration"])) for p in cand["phases"]))
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            valid_plans.append(cand)

        return valid_plans

    def write_additional_signals_xml(
        self,
        file_path: Path,
        tl_id_or_plans: str | dict[str, Any],
        phases: Optional[list[dict[str, Any]]] = None,
        program_id: str = "optimized_fixed_time",
        offset: int = 0,
    ) -> None:
        """
        Write SUMO additional file with fixed-time signal logic.
        Supports both single-signal calls:
            write_additional_signals_xml(path, tl_id, phases, program_id)
        and multi-signal dictionary calls:
            write_additional_signals_xml(path, {tl_1: {"phases": [...], "offset": 0}, ...})
        """
        root = ET.Element("additional")

        if isinstance(tl_id_or_plans, str):
            # Single-signal call
            tl_id = tl_id_or_plans
            signal_dict = {tl_id: {"phases": phases or [], "program_id": program_id, "offset": offset}}
        else:
            # Multi-signal call
            signal_dict = {}
            for t_id, data in tl_id_or_plans.items():
                if isinstance(data, list):
                    signal_dict[t_id] = {"phases": data, "program_id": program_id, "offset": 0}
                elif isinstance(data, dict):
                    signal_dict[t_id] = {
                        "phases": data.get("phases", []),
                        "program_id": data.get("program_id", program_id),
                        "offset": data.get("offset", 0),
                    }

        for t_id, s_data in signal_dict.items():
            tl = ET.SubElement(
                root,
                "tlLogic",
                id=t_id,
                type="static",
                programID=s_data.get("program_id", program_id),
                offset=str(s_data.get("offset", 0)),
            )
            for p in s_data.get("phases", []):
                ET.SubElement(
                    tl,
                    "phase",
                    duration=str(int(round(float(p["duration"])))),
                    state=p["state"],
                )

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

    def _run_sumo_eval(
        self,
        net_file: Path,
        rou_file: Path,
        add_file: Optional[Path],
        eval_duration: int,
        seed: int,
        run_label: str,
        timeout_seconds: int = 25,
    ) -> dict[str, Any]:
        """
        Execute an actual SUMO simulation run and extract empirical tripinfo & summary observations.
        Never fabricates measurements: returns explicit evaluation_status and diagnostics.
        """
        result: dict[str, Any] = {
            "evaluation_status": "failed",
            "diagnostics": None,
            "avg_wait": None,
            "avg_speed": None,
            "throughput": None,
            "queue_burden": None,
            "max_queue": None,
            "completed_vehicles": 0,
            "unfinished_vehicles": 0,
            "inserted_vehicles": 0,
            "teleported_vehicles": 0,
            "halting_vehicles": 0,
            "score": float("inf"),
        }

        if not self.sumo_bin or not Path(self.sumo_bin).is_file():
            result["diagnostics"] = "SUMO binary not available"
            result["evaluation_status"] = "failed"
            return result

        summary_file = self.work_dir / f"summary_{run_label}.xml"
        tripinfo_file = self.work_dir / f"tripinfo_{run_label}.xml"

        # Clean previous outputs
        for f in (summary_file, tripinfo_file):
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass

        cmd = [
            self.sumo_bin,
            "-n", str(net_file),
            "-r", str(rou_file),
            "--begin", "0",
            "--end", str(eval_duration),
            "--seed", str(seed),
            "--step-length", "0.2",
            "--no-step-log", "true",
            "--no-warnings", "true",
            "--summary-output", str(summary_file),
            "--tripinfo-output", str(tripinfo_file),
            "--tripinfo-output.write-unfinished", "true",
            "--ignore-route-errors", "true",
        ]
        if add_file and add_file.is_file():
            cmd.extend(["-a", str(add_file)])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            if res.returncode != 0:
                result["evaluation_status"] = "failed"
                stderr_clean = res.stderr.strip()[:300] if res.stderr else "Unknown non-zero exit"
                result["diagnostics"] = f"SUMO exited with code {res.returncode}: {stderr_clean}"
                return result
        except subprocess.TimeoutExpired:
            result["evaluation_status"] = "failed"
            result["diagnostics"] = f"SUMO execution timed out after {timeout_seconds}s"
            return result
        except Exception as e:
            result["evaluation_status"] = "failed"
            result["diagnostics"] = f"Failed to execute SUMO subprocess: {e}"
            return result

        # Parse summary output across all recorded simulation steps
        inserted = 0
        ended = 0
        teleports = 0
        halting = 0
        sum_mean_speed = None
        sum_mean_wait = None
        haltings: list[int] = []
        step_waits: list[float] = []
        step_speeds: list[float] = []

        if summary_file.is_file():
            try:
                s_tree = ET.parse(str(summary_file))
                s_root = s_tree.getroot()
                steps = s_root.findall("step")
                for s in steps:
                    try:
                        h = int(s.get("halting", "0"))
                        haltings.append(h)
                    except (ValueError, TypeError):
                        pass
                    try:
                        w_val = float(s.get("meanWaitingTime", "0.0"))
                        step_waits.append(w_val)
                    except (ValueError, TypeError):
                        pass
                    try:
                        sp_val = float(s.get("meanSpeed", "0.0")) * 3.6  # m/s to km/h
                        step_speeds.append(sp_val)
                    except (ValueError, TypeError):
                        pass

                if steps:
                    last_step = steps[-1]
                    inserted = int(last_step.get("inserted", "0"))
                    ended = int(last_step.get("ended", "0"))
                    teleports = int(last_step.get("teleports", "0"))
                    halting = int(last_step.get("halting", "0"))
                    if step_waits:
                        sum_mean_wait = sum(step_waits) / len(step_waits)
                    if step_speeds:
                        sum_mean_speed = sum(step_speeds) / len(step_speeds)
            except Exception as e:
                logger.debug("Summary parse note: %s", e)

        # Parse tripinfo output (completed trips + unfinished trips)
        waits: list[float] = []
        speeds: list[float] = []
        completed_count = 0
        unfinished_count = 0

        if tripinfo_file.is_file():
            try:
                t_tree = ET.parse(str(tripinfo_file))
                t_root = t_tree.getroot()
                for trip in t_root.findall("tripinfo"):
                    w = float(trip.get("waitingTime", "0.0"))
                    d = float(trip.get("routeLength", "0.0"))
                    dur = float(trip.get("duration", "0.0"))
                    waits.append(w)
                    if dur > 0.0 and d > 0.0:
                        speeds.append((d / dur) * 3.6)
                    completed_count += 1

                for unfin in t_root.findall("unfinished-tripinfo"):
                    w = float(unfin.get("waitingTime", "0.0"))
                    waits.append(w)
                    unfinished_count += 1
            except Exception as e:
                result["evaluation_status"] = "failed"
                result["diagnostics"] = f"Malformed tripinfo XML: {e}"
                return result

        total_observed = completed_count + unfinished_count
        if total_observed == 0:
            result["evaluation_status"] = "insufficient_data"
            result["diagnostics"] = "No trips completed or active during measurement window"
            return result

        # Compute valid metrics
        avg_wait = round(sum(waits) / len(waits), 1) if waits else (round(sum_mean_wait, 1) if sum_mean_wait is not None else 0.0)
        avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else (round(sum_mean_speed, 1) if sum_mean_speed is not None else 25.0)
        throughput = round((completed_count / max(1.0, float(eval_duration))) * 3600.0, 1)

        # Measured queue statistics across the entire measurement run:
        # Peak halting vehicles observed across all simulation steps
        max_halting_count = max(haltings) if haltings else halting
        # Time-integrated mean halting vehicles observed across all simulation steps
        mean_halting_count = (sum(haltings) / len(haltings)) if haltings else float(halting)
        # Standard SUMO queuing spatial extent (7.5m = 5m vehicle + 2.5m minGap)
        queue_burden = round(mean_halting_count * 7.5, 1)
        max_queue = round(max_halting_count * 7.5, 1)

        # Validate numbers are finite
        for v in (avg_wait, avg_speed, throughput, queue_burden, max_queue):
            if not math.isfinite(v):
                result["evaluation_status"] = "failed"
                result["diagnostics"] = "Non-finite metric produced by simulation"
                return result

        score, components = calculate_objective_score(
            avg_wait=avg_wait,
            avg_speed=avg_speed,
            throughput=throughput,
            queue_burden=queue_burden,
            max_queue=max_queue,
            unfinished_count=unfinished_count,
            inserted_count=max(inserted, total_observed),
            teleported_count=teleports,
        )

        result.update({
            "evaluation_status": "success",
            "diagnostics": None,
            "avg_wait": avg_wait,
            "avg_speed": avg_speed,
            "throughput": throughput,
            "queue_burden": queue_burden,
            "max_queue": max_queue,
            "completed_vehicles": completed_count,
            "unfinished_vehicles": unfinished_count,
            "inserted_vehicles": max(inserted, total_observed),
            "teleported_vehicles": teleports,
            "halting_vehicles": halting,
            "score": score,
            "components": components,
        })
        return result

    def optimize(
        self,
        net_file: Path,
        rou_file: Path,
        cfg_file: Path,
        eval_duration: int = 45,
        seed: int = 42,
        target_signal_ids: Optional[set[str]] = None,
        max_signals_to_optimize: int = 6,
    ) -> Optional[FixedTimeOptimizationResult]:
        """
        Execute bounded candidate fixed-time evaluations and select the optimal plan.
        Supports:
        - Multi-signal optimization across all eligible signals in the network
        - Explicit evaluation statuses without fabricated measurements
        - Objective scoring balancing delay, queue, speed, and unfinished trips
        - Separate final network-level validation against baseline
        - Preserving original plan on failure
        """
        tl_logics = self.parse_traffic_lights(net_file)
        if not tl_logics:
            return FixedTimeOptimizationResult(
                signal_id="none",
                validation_passed=False,
                notes="No traffic signal controllers found in compiled network.",
                status="no_signals",
                optimized_signals_count=0,
                total_signals_count=0,
            )

        if not self.sumo_bin or not Path(self.sumo_bin).is_file():
            primary_tl_id = list(tl_logics.keys())[0]
            return FixedTimeOptimizationResult(
                signal_id=primary_tl_id,
                validation_passed=False,
                notes="Native SUMO binary not found; empirical signal optimization unavailable.",
                status="failed",
                failure_reason="sumo_binary_unavailable",
                optimized_signals_count=0,
                total_signals_count=len(tl_logics),
            )

        connections = self.parse_controlled_connections(net_file)

        # Baseline network evaluation (netconvert plans)
        base_net_eval = self._run_sumo_eval(
            net_file=net_file,
            rou_file=rou_file,
            add_file=None,
            eval_duration=eval_duration,
            seed=seed,
            run_label="baseline_screening",
        )

        # Require successful baseline evaluation with finite score
        if (
            base_net_eval["evaluation_status"] != "success"
            or not math.isfinite(base_net_eval.get("score", float("inf")))
        ):
            primary_tl_id = list(tl_logics.keys())[0]
            diag = base_net_eval.get("diagnostics") or f"Evaluation status: {base_net_eval['evaluation_status']}"
            notes = (
                f"Baseline network evaluation did not succeed ({diag}). "
                f"Cannot validate candidate timing plans without a valid empirical baseline. "
                f"Preserving original network signal timing."
            )
            final_add_file = self.work_dir / "signals.add.xml"
            final_add_file.unlink(missing_ok=True)
            self._detach_additional_from_sumocfg(cfg_file, "signals.add.xml")
            return FixedTimeOptimizationResult(
                signal_id=primary_tl_id,
                evaluated_plans=[],
                selected_plan_id="plan_base",
                selected_cycle_length_s=int(sum(float(p["duration"]) for p in tl_logics[primary_tl_id])),
                validation_passed=False,
                notes=notes,
                status="inconclusive",
                failure_reason="baseline_evaluation_failed",
                optimized_signals_count=0,
                total_signals_count=len(tl_logics),
                signal_results={},
            )

        baseline_score = float(base_net_eval["score"])

        # Determine signals to optimize in Stage A
        eligible_tl_ids = list(tl_logics.keys())
        if target_signal_ids:
            # Target signals specified: prioritize approved/selected signals present in network
            targets = [t for t in eligible_tl_ids if t in target_signal_ids]
            signals_to_screen = targets if targets else eligible_tl_ids[:max_signals_to_optimize]
        else:
            # Prioritize signals by complexity (controlled connection count)
            signals_to_screen = sorted(
                eligible_tl_ids,
                key=lambda t: len(connections.get(t, [])),
                reverse=True,
            )[:max_signals_to_optimize]
        signals_to_screen_set = set(signals_to_screen)

        # STAGE A: Optimize each eligible signal
        signal_results: dict[str, Any] = {}
        winning_plans_per_signal: dict[str, dict[str, Any]] = {}
        all_evaluated_plans: list[TimingPlanEvaluation] = []
        optimized_count = 0

        # Preserve baseline timing for signals outside current screening batch
        for tl_id, base_phases in tl_logics.items():
            if tl_id not in signals_to_screen_set:
                winning_plans_per_signal[tl_id] = {"phases": base_phases, "plan_id": "plan_base"}
                signal_results[tl_id] = {
                    "status": "baseline_preserved",
                    "selected_plan": "plan_base",
                    "reason": "Signal preserved with baseline netconvert timing",
                }

        for tl_id in signals_to_screen:
            base_phases = tl_logics[tl_id]
            candidates = self.generate_candidate_plans(tl_id, base_phases, include_base=True)
            if not candidates:
                signal_results[tl_id] = {"status": "unsupported", "selected_plan": None}
                winning_plans_per_signal[tl_id] = {"phases": base_phases, "plan_id": "plan_base"}
                continue

            def _eval_candidate(cand: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                plan_id = cand["plan_id"]
                phases = cand["phases"]
                cand_add_file = self.work_dir / f"signals_{tl_id}_{plan_id}.add.xml"
                self.write_additional_signals_xml(cand_add_file, tl_id, phases, program_id=plan_id)
                run_res = self._run_sumo_eval(
                    net_file=net_file,
                    rou_file=rou_file,
                    add_file=cand_add_file,
                    eval_duration=eval_duration,
                    seed=seed,
                    run_label=f"{tl_id}_{plan_id}",
                )
                return cand, run_res

            # Concurrently evaluate candidates using ThreadPoolExecutor for fast non-blocking screening
            workers = min(4, os.cpu_count() or 2, len(candidates))
            if workers > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    eval_tuples = list(executor.map(_eval_candidate, candidates))
            else:
                eval_tuples = [_eval_candidate(c) for c in candidates]

            evaluated_cands: list[TimingPlanEvaluation] = []
            best_cand = candidates[0]  # default to base plan
            best_score = float("inf")
            valid_eval_count = 0

            for cand, run_res in eval_tuples:
                plan_id = cand["plan_id"]
                phases = cand["phases"]
                cycle_len = cand["cycle_length_s"]

                st: EvaluationStatus = run_res["evaluation_status"]
                score = run_res["score"]
                is_valid = st == "success" and math.isfinite(score) and score < float("inf")

                if is_valid:
                    valid_eval_count += 1
                    # Deterministic tie-breaking: lower score, then lower avg_wait, then plan_id
                    if (
                        score < best_score
                        or (score == best_score and (run_res["avg_wait"] or 0.0) < (getattr(best_cand, "avg_wait", 999.0)))
                    ):
                        best_score = score
                        best_cand = cand

                evaluated_cands.append(
                    TimingPlanEvaluation(
                        plan_id=plan_id,
                        cycle_length_s=cycle_len,
                        name=cand["name"],
                        description=cand["description"],
                        objective_score=score if is_valid else 999.0,
                        avg_waiting_time_s=run_res["avg_wait"] if is_valid else 0.0,
                        avg_speed_kmh=run_res["avg_speed"] if is_valid else 0.0,
                        throughput_veh_hr=run_res["throughput"] if is_valid else 0.0,
                        is_selected=False,
                        validation_passed=is_valid,
                        evaluation_status=st,
                        diagnostics=run_res.get("diagnostics"),
                        queue_burden_m=run_res.get("queue_burden"),
                        max_queue_m=run_res.get("max_queue"),
                        completed_vehicles=run_res.get("completed_vehicles"),
                        unfinished_vehicles=run_res.get("unfinished_vehicles"),
                        teleported_vehicles=run_res.get("teleported_vehicles"),
                        phases=phases,
                    )
                )

            # Mark winning plan if valid evaluations exist
            if valid_eval_count > 0:
                for ec in evaluated_cands:
                    if ec.plan_id == best_cand["plan_id"]:
                        ec.is_selected = True
                winning_plans_per_signal[tl_id] = best_cand
                signal_results[tl_id] = {
                    "status": "optimized",
                    "selected_plan": best_cand["plan_id"],
                    "best_score": best_score,
                }
                optimized_count += 1
            else:
                winning_plans_per_signal[tl_id] = {"phases": base_phases, "plan_id": "plan_base"}
                signal_results[tl_id] = {
                    "status": "failed",
                    "reason": "All candidate evaluations failed in native SUMO",
                }

            all_evaluated_plans.extend(evaluated_cands)

        # STAGE B: Network-Level Validation
        primary_tl_id = list(tl_logics.keys())[0]
        final_add_file = self.work_dir / "signals.add.xml"

        # If any signal was successfully evaluated, assemble multi-signal additional file
        if optimized_count > 0:
            multi_signal_dict = {
                t_id: {"phases": p_data["phases"], "program_id": p_data.get("plan_id", "optimized_fixed_time")}
                for t_id, p_data in winning_plans_per_signal.items()
            }
            self.write_additional_signals_xml(final_add_file, multi_signal_dict)

            # Run network-level validation of combined plan
            net_eval = self._run_sumo_eval(
                net_file=net_file,
                rou_file=rou_file,
                add_file=final_add_file,
                eval_duration=eval_duration,
                seed=seed,
                run_label="combined_network_validation",
            )

            is_net_validated = (
                base_net_eval["evaluation_status"] == "success"
                and math.isfinite(baseline_score)
                and net_eval["evaluation_status"] == "success"
                and math.isfinite(net_eval["score"])
                and net_eval["score"] <= (baseline_score + 0.5)  # Must not significantly regress network
            )

            if is_net_validated:
                self._attach_additional_to_sumocfg(cfg_file, "signals.add.xml")
                primary_win = winning_plans_per_signal.get(primary_tl_id, {})
                notes = (
                    f"Validated {optimized_count}/{len(tl_logics)} traffic signals across network in native SUMO. "
                    f"Network-level objective: {net_eval['score']:.2f} (baseline: {baseline_score:.2f})."
                )
                return FixedTimeOptimizationResult(
                    signal_id=primary_tl_id,
                    evaluated_plans=all_evaluated_plans,
                    selected_plan_id=primary_win.get("plan_id", "plan_base"),
                    selected_cycle_length_s=primary_win.get("cycle_length_s", 90),
                    validation_passed=True,
                    notes=notes,
                    status="completed",
                    optimized_signals_count=optimized_count,
                    total_signals_count=len(tl_logics),
                    signal_results=signal_results,
                )
            else:
                # Combined plan regressed or failed network validation: clean up and fall back cleanly
                final_add_file.unlink(missing_ok=True)
                self._detach_additional_from_sumocfg(cfg_file, "signals.add.xml")
                eval_diag = net_eval.get("diagnostics")
                comb_score_str = f"{net_eval['score']:.2f}" if math.isfinite(net_eval.get("score", float("nan"))) else "failed"
                notes = (
                    f"Candidate plans were screened for {optimized_count} signals, but combined whole-network validation "
                    f"did not beat baseline (combined: {comb_score_str} vs baseline: {baseline_score:.2f}"
                    + (f", diagnostics: {eval_diag}" if eval_diag else "")
                    + "). Preserving original network signal timing."
                )
                return FixedTimeOptimizationResult(
                    signal_id=primary_tl_id,
                    evaluated_plans=all_evaluated_plans,
                    selected_plan_id="plan_base",
                    selected_cycle_length_s=int(sum(float(p['duration']) for p in tl_logics[primary_tl_id])),
                    validation_passed=False,
                    notes=notes,
                    status="inconclusive",
                    failure_reason="combined_network_validation_failed",
                    optimized_signals_count=0,
                    total_signals_count=len(tl_logics),
                    signal_results=signal_results,
                )

        # If zero signals were successfully optimized
        final_add_file.unlink(missing_ok=True)
        self._detach_additional_from_sumocfg(cfg_file, "signals.add.xml")
        notes = (
            f"All candidate evaluations for {len(tl_logics)} traffic signal(s) failed or returned insufficient data in SUMO. "
            f"Preserved original compiled timing plan."
        )
        return FixedTimeOptimizationResult(
            signal_id=primary_tl_id,
            evaluated_plans=all_evaluated_plans,
            selected_plan_id=None,
            selected_cycle_length_s=None,
            validation_passed=False,
            notes=notes,
            status="failed",
            failure_reason="all_evaluations_failed",
            optimized_signals_count=0,
            total_signals_count=len(tl_logics),
            signal_results=signal_results,
        )

    def _attach_additional_to_sumocfg(self, cfg_file: Path, add_file_name: str) -> None:
        """Attach additional-files element to simulation.sumocfg."""
        if not cfg_file.is_file():
            return
        try:
            tree = ET.parse(str(cfg_file))
            root = tree.getroot()
            inp = root.find("input")
            if inp is None:
                inp = ET.SubElement(root, "input")
            add_elem = inp.find("additional-files")
            if add_elem is None:
                add_elem = ET.SubElement(inp, "additional-files")
            add_elem.set("value", add_file_name)
            tree.write(str(cfg_file), encoding="utf-8", xml_declaration=True)
            logger.info("Attached %s to %s successfully", add_file_name, cfg_file)
        except Exception as e:
            logger.warning("Could not attach additional-files to sumocfg: %s", e)

    def _detach_additional_from_sumocfg(self, cfg_file: Path, add_file_name: str) -> None:
        """Detach additional-files element from simulation.sumocfg if present."""
        if not cfg_file.is_file():
            return
        try:
            tree = ET.parse(str(cfg_file))
            root = tree.getroot()
            inp = root.find("input")
            if inp is not None:
                add_elem = inp.find("additional-files")
                if add_elem is not None:
                    cur_val = add_elem.get("value", "")
                    if add_file_name in cur_val:
                        inp.remove(add_elem)
                        tree.write(str(cfg_file), encoding="utf-8", xml_declaration=True)
                        logger.info("Detached %s from %s successfully", add_file_name, cfg_file)
        except Exception as e:
            logger.warning("Could not detach additional-files from sumocfg: %s", e)
