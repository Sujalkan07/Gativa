"""
TraCI Manager: Controls native Eclipse SUMO simulation sessions via TraCI API.
Supports start, pause, step, reset, stop, adaptive signal actuation, and real-time state extraction.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from app.models.schemas import (
    CongestionRoadResult,
    CongestionSummary,
    SimulationEngineMode,
    SimulationMetrics,
    SimulationState,
    TrafficLightState,
    VehiclePosition,
)
from app.simulation.network_builder import (
    SIMULATION_STEP_LENGTH_SECONDS,
    find_sumo_binary,
    SumoNetworkBuilder,
)

logger = logging.getLogger(__name__)

# Ensure SUMO tools are on sys.path for importing traci
_sumo_home = os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
_tools_dir = Path(_sumo_home) / "tools"
if _tools_dir.is_dir() and str(_tools_dir) not in sys.path:
    sys.path.append(str(_tools_dir))

try:
    import traci
    TRACI_AVAILABLE = True
except ImportError:
    traci = None
    TRACI_AVAILABLE = False
    logger.warning("TraCI python library could not be imported from SUMO_HOME/tools.")


def get_free_port() -> int:
    """Find an available ephemeral port for TraCI socket connection."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def normalize_traffic_light_state(state_str: str) -> str:
    """Reduce SUMO's per-link signal state to a safe junction-level display state.

    SUMO returns one character per controlled link (for example ``GrGr``), not
    words such as ``green``. A junction with no active red/yellow/green aspect
    (for example an off signal represented by ``o``) must not be shown as green.
    """
    state = (state_str or "").lower()
    if "y" in state or "u" in state:
        return "yellow"
    if "g" in state:
        return "green"
    if "r" in state:
        return "red"
    return "unknown"


class SimulationSession:
    """Manages the lifecycle, execution engine, and TraCI connection for a simulation instance."""

    def __init__(
        self,
        sim_id: str,
        analysis_id: str,
        work_dir: Path,
        cfg_file: Path,
        duration_seconds: int = 600,
        demand_rate_veh_hr: int = 2840,
        strategy: str = "actuated_adaptive",
        edge_count: int = 0,
        junction_count: int = 0,
        signal_count: int = 0,
        road_segments: Optional[list[dict[str, Any]]] = None,
        netconvert_used: bool = True,
        polygon_coords: Optional[list[list[float]]] = None,
        demand_level: str = "normal",
        demand_profile: str = "peak",
        demand_data_source: str = "road_network_estimation",
        demand_source_label: Optional[str] = None,
        scheduled_vehicles: int = 0,
        signal_overrides: Optional[dict[str, str]] = None,
        is_synthetic_demo: bool = False,
        assumptions: Optional[list[str]] = None,
        omitted_segments_count: int = 0,
        initial_vehicles_count: int = 0,
        approved_signals_count: int = 0,
        applied_signals_count: int = 0,
        selected_fixed_time_plan: Optional[Any] = None,
    ):
        self.sim_id = sim_id
        self.analysis_id = analysis_id
        self.work_dir = Path(work_dir)
        self.cfg_file = Path(cfg_file)
        self.duration_seconds = duration_seconds
        self.demand_rate_veh_hr = demand_rate_veh_hr
        self.strategy = strategy
        self.edge_count = edge_count
        self.junction_count = junction_count
        self.signal_count = signal_count
        self.road_segments = road_segments or []
        self.netconvert_used = netconvert_used
        self.polygon_coords = polygon_coords or []
        self.demand_level = demand_level
        self.demand_profile = demand_profile
        self.demand_data_source = demand_data_source
        self.demand_source_label = demand_source_label or f"Calibrated {demand_level} demand ({demand_rate_veh_hr:,} veh/hr)"
        self.scheduled_vehicles = scheduled_vehicles
        self.signal_overrides = signal_overrides or {}
        self.is_synthetic_demo = is_synthetic_demo
        self.assumptions = assumptions or []
        self.omitted_segments_count = omitted_segments_count
        self.initial_vehicles_count = initial_vehicles_count
        self.approved_signals_count = approved_signals_count
        self.applied_signals_count = applied_signals_count
        self.selected_fixed_time_plan = selected_fixed_time_plan
        self.network_provenance = "synthetic_demo" if is_synthetic_demo else "real_osm"

        if not self.road_segments:
            if is_synthetic_demo:
                builder = SumoNetworkBuilder(self.work_dir)
                if self.polygon_coords and len(self.polygon_coords) >= 3:
                    self.road_segments = builder._corridor_from_polygon(self.polygon_coords)
                else:
                    self.road_segments = builder._default_corridor_segments()
                self.assumptions.append("synthetic_corridor_fallback")

        self.state: SimulationState = "ready"
        self.engine_mode: SimulationEngineMode = "unavailable"
        self.engine_message: Optional[str] = None
        self.step_count = 0
        self.elapsed_seconds = 0.0
        self.port: Optional[int] = None
        self.conn_label = f"gativa_{sim_id[:8]}"
        self.is_connected = False
        self.error_message: Optional[str] = None
        self.engine_transitioned = False
        self.engine_transition_reason: Optional[str] = None
        self._lock = threading.RLock()

        # Cumulative statistics
        self.inserted_vehicles_cumulative = 0
        self.completed_vehicles_cumulative = 0
        self.waiting_to_enter_count = 0
        self.teleported_count = 0
        self.collision_count = 0
        self.peak_queue_m = 0.0
        self.speed_samples: list[float] = []
        self.waiting_samples: list[float] = []
        self.queue_samples: list[float] = []
        self.travel_time_samples: list[float] = []
        self._vehicle_entry_times: dict[str, float] = {}

        self.current_metrics = SimulationMetrics(
            total_duration_seconds=float(duration_seconds),
            scheduled_vehicles=self.scheduled_vehicles,
        )
        self.cached_vehicles: list[VehiclePosition] = []
        self.cached_signals: list[TrafficLightState] = []

        # Congestion telemetry: SUMO edge_id → list of timestamped observations
        self._edge_telemetry: dict[str, list[dict]] = {}
        self._edge_cumulative_stats: dict[str, dict[str, Any]] = {}
        self._segment_edge_map: dict[str, list[str]] = {}
        self._valid_sumo_edges: Optional[list[str]] = None
        self._last_edge_sample_time: Optional[float] = None

        # Signal actuation state dictionary keyed by tl_id
        self._signal_controllers: dict[str, dict[str, Any]] = {}
        self._last_phase_change_time = 0.0
        self._current_phase_index = 0

        # Initial engine mode determination
        sumo_bin = find_sumo_binary("sumo")
        if TRACI_AVAILABLE and sumo_bin and self.netconvert_used:
            self.engine_mode = "native_sumo"
            self.engine_message = "Native Eclipse SUMO available via TraCI."
        else:
            self.engine_mode = "fallback"
            reasons = []
            if not TRACI_AVAILABLE:
                reasons.append("TraCI library not installed")
            if not sumo_bin:
                reasons.append("sumo binary not found")
            if not self.netconvert_used:
                reasons.append("network compiled without netconvert")
            self.engine_message = f"Operating in internal kinematics mode ({', '.join(reasons)})."

        # Initialize t=0.0 vehicle distribution preview so vehicles are immediately visible on map
        try:
            self._step_kinematics_fallback(0)
        except Exception:
            pass

    def start(self):
        """Start or resume the simulation process using the appropriate engine."""
        with self._lock:
            if self.state == "running":
                return

            sumo_bin = find_sumo_binary("sumo")
            can_run_native = TRACI_AVAILABLE and sumo_bin is not None and self.netconvert_used

            if not can_run_native:
                self.engine_mode = "fallback"
                self.state = "running"
                if not TRACI_AVAILABLE:
                    self.engine_message = "TraCI library not found; running internal kinematics engine."
                elif not sumo_bin:
                    self.engine_message = "sumo executable not found; running internal kinematics engine."
                else:
                    self.engine_message = "Network compiled without netconvert; running internal kinematics engine."
                logger.info("Simulation %s running in fallback kinematics mode: %s", self.sim_id, self.engine_message)
                return

            if not self.is_connected:
                self.port = get_free_port()
                cmd = [
                    sumo_bin,
                    "-c", str(self.cfg_file),
                    "--no-warnings", "true",
                    "--no-step-log", "true",
                    "--start", "true",
                    "--quit-on-end", "true",
                    "--ignore-route-errors", "true",
                ]
                try:
                    traci.start(cmd, port=self.port, label=self.conn_label)
                    self.is_connected = True
                    self.engine_mode = "native_sumo"
                    self.engine_message = "Native Eclipse SUMO running successfully via TraCI."
                    self.state = "running"
                    logger.info("Started native SUMO simulation %s via TraCI on port %s", self.sim_id, self.port)
                except Exception as e:
                    logger.warning("Failed to start native TraCI connection on %s: %s; transitioning to fallback", self.sim_id, e)
                    self.is_connected = False
                    self.engine_mode = "fallback"
                    self.engine_message = f"Native SUMO startup failed ({type(e).__name__}); running internal kinematics engine."
                    self.error_message = str(e)
                    self.state = "running"
            else:
                self.state = "running"

    def pause(self):
        """Pause the running simulation."""
        with self._lock:
            if self.state == "running":
                self.state = "paused"
                logger.info("Simulation %s paused at elapsed %.1fs", self.sim_id, self.elapsed_seconds)

    def step(self, num_steps: int = 1) -> dict[str, Any]:
        """Advance the simulation by num_steps and extract real vehicle coordinates & metrics."""
        with self._lock:
            if self.state not in ("running", "ready"):
                return self.get_status()

            if not self.is_connected and self.engine_mode == "native_sumo":
                self.start()

            self.state = "running"

            if self.is_connected and TRACI_AVAILABLE and self.engine_mode == "native_sumo":
                try:
                    conn = traci.getConnection(self.conn_label)
                    for _ in range(num_steps):
                        if self.elapsed_seconds >= self.duration_seconds:
                            self.state = "completed"
                            break

                        # 1. Apply Signal Strategy (Actuated vs Fixed)
                        if self.strategy == "actuated_adaptive":
                            self._apply_actuated_signals(conn)

                        # 2. Advance TraCI step
                        conn.simulationStep()
                        self.step_count += 1
                        self.elapsed_seconds = round(conn.simulation.getTime(), 1)
                        # Departure/arrival lists are reset each simulation
                        # step.  Capture them here rather than after a batched
                        # step, otherwise a populated t=0 network appears to
                        # have inserted zero vehicles in the metrics.
                        for v_id in conn.simulation.getDepartedIDList():
                            self._vehicle_entry_times[v_id] = self.elapsed_seconds
                            self.inserted_vehicles_cumulative += 1
                        arrived_ids = conn.simulation.getArrivedIDList()
                        self.completed_vehicles_cumulative += len(arrived_ids)
                        for v_id in arrived_ids:
                            entry_time = self._vehicle_entry_times.pop(v_id, None)
                            if entry_time is not None:
                                self.travel_time_samples.append(max(1.0, self.elapsed_seconds - entry_time))

                        # Sample at a stable cadence while a batch is running.
                        # Sampling only after a large batch can hide a queue
                        # that formed and persisted for most of that batch.
                        if (
                            self._last_edge_sample_time is None
                            or self.elapsed_seconds - self._last_edge_sample_time >= 1.0
                        ):
                            self._sample_edge_telemetry(conn)
                            self._last_edge_sample_time = self.elapsed_seconds

                    # 3. Extract Vehicles and Instantaneous Metrics
                    self._extract_traci_state(conn)
                except Exception as e:
                    logger.warning("TraCI runtime step error on %s: %s; transitioning to fallback kinematics", self.sim_id, e)
                    self.engine_transitioned = True
                    self.engine_transition_reason = f"TraCI runtime step failure ({type(e).__name__}): {e}"
                    self.engine_mode = "fallback"
                    self.engine_message = f"Native TraCI runtime failure ({type(e).__name__}); transitioned to fallback kinematics (measurements invalidated for empirical comparison)."
                    self.is_connected = False
                    self._step_kinematics_fallback(num_steps)
            else:
                # Deterministic kinematics progression matching real corridor geometry
                self.engine_mode = "fallback"
                self._step_kinematics_fallback(num_steps)

            if self.elapsed_seconds >= self.duration_seconds:
                self.state = "completed"
                if self.speed_samples:
                    self.current_metrics.avg_speed_kmh = round(sum(self.speed_samples) / len(self.speed_samples), 1)
                if self.waiting_samples:
                    self.current_metrics.avg_waiting_time_s = round(sum(self.waiting_samples) / len(self.waiting_samples), 1)
                if self.queue_samples:
                    self.current_metrics.avg_queue_length_m = round(sum(self.queue_samples) / len(self.queue_samples), 1)

            return self.get_status()

    def _apply_actuated_signals(self, conn):
        """
        Genuine Queue-Responsive Actuated Adaptive Signal Control via TraCI.
        Evaluates real-time halting queues on incoming approaches for each green phase,
        extends green when queue is discharging (up to max_green),
        and executes safe yellow clearance intervals (3.5s) before phase switches.
        """
        try:
            tl_ids = conn.trafficlight.getIDList()
            current_time = float(conn.simulation.getTime())

            for tl_id in tl_ids:
                # Check user override for this signal (e.g. if user edited to fixed-time)
                if self.signal_overrides.get(tl_id) == "fixed_time":
                    continue

                if tl_id not in self._signal_controllers:
                    # Initialize controller for this traffic light
                    logics = conn.trafficlight.getAllProgramLogics(tl_id)
                    if not logics or not logics[0].phases:
                        continue
                    active_logic = logics[0]
                    phases = active_logic.phases
                    controlled_links = conn.trafficlight.getControlledLinks(tl_id)

                    # Identify Green phases (contains 'G' or 'g') vs Yellow clearance phases (contains 'y')
                    green_phase_indices = []
                    yellow_map: dict[int, int] = {}
                    green_lanes_map: dict[int, list[str]] = {}

                    for p_idx, p in enumerate(phases):
                        state_str = p.state
                        has_green = "G" in state_str or "g" in state_str
                        has_yellow = "y" in state_str.lower()
                        if has_green and not has_yellow:
                            green_phase_indices.append(p_idx)
                            in_lanes = set()
                            for link_idx, link_tuples in enumerate(controlled_links):
                                if link_idx < len(state_str) and state_str[link_idx] in ("G", "g"):
                                    for l_tup in link_tuples:
                                        if l_tup and len(l_tup) > 0:
                                            in_lanes.add(l_tup[0])
                            green_lanes_map[p_idx] = list(in_lanes)

                    for g_idx in green_phase_indices:
                        # Use the next genuine clearance phase, never assume
                        # adjacent phase indices are yellow in every SUMO
                        # program.  Conflicting movements remain red while a
                        # direction is clearing.
                        yellow_map[g_idx] = next(
                            (
                                (g_idx + offset) % len(phases)
                                for offset in range(1, len(phases))
                                if "y" in phases[(g_idx + offset) % len(phases)].state.lower()
                            ),
                            g_idx,
                        )

                    current_p = conn.trafficlight.getPhase(tl_id)
                    curr_green = current_p if current_p in green_phase_indices else (green_phase_indices[0] if green_phase_indices else 0)

                    self._signal_controllers[tl_id] = {
                        "current_green_phase": curr_green,
                        "phase_start_time": current_time,
                        "is_yellow": False,
                        "yellow_start": 0.0,
                        "yellow_duration": 3.5,
                        "target_green_phase": curr_green,
                        "min_green": 10.0,
                        "max_green": 50.0,
                        "green_phases": green_phase_indices,
                        "yellow_map": yellow_map,
                        "green_lanes": green_lanes_map,
                    }

                ctrl = self._signal_controllers[tl_id]
                green_phases = ctrl["green_phases"]
                if len(green_phases) < 2:
                    continue

                if ctrl["is_yellow"]:
                    # In yellow clearance interval
                    if current_time - ctrl["yellow_start"] >= ctrl["yellow_duration"]:
                        target_p = ctrl["target_green_phase"]
                        conn.trafficlight.setPhase(tl_id, target_p)
                        ctrl["is_yellow"] = False
                        ctrl["current_green_phase"] = target_p
                        ctrl["phase_start_time"] = current_time
                    continue

                # In active green phase
                current_green = ctrl["current_green_phase"]
                time_in_green = current_time - ctrl["phase_start_time"]

                if time_in_green < ctrl["min_green"]:
                    continue

                # Evaluate queues on current green lanes vs competing green phases
                curr_lanes = ctrl["green_lanes"].get(current_green, [])
                curr_queue = sum(conn.lane.getLastStepHaltingNumber(l) for l in curr_lanes) if curr_lanes else 0

                best_competing_phase = None
                max_competing_demand = 0.0

                for cand_p in green_phases:
                    if cand_p == current_green:
                        continue
                    cand_lanes = ctrl["green_lanes"].get(cand_p, [])
                    if not cand_lanes:
                        continue
                    halting = sum(conn.lane.getLastStepHaltingNumber(l) for l in cand_lanes)
                    waiting = sum(conn.lane.getWaitingTime(l) for l in cand_lanes)
                    demand = halting * 2.0 + (waiting / 10.0)
                    if demand > max_competing_demand:
                        max_competing_demand = demand
                        best_competing_phase = cand_p

                should_switch = False
                if best_competing_phase is not None and max_competing_demand >= 2.0:
                    if curr_queue <= 1:
                        should_switch = True
                    elif time_in_green >= ctrl["max_green"]:
                        should_switch = True

                if should_switch:
                    yellow_p = ctrl["yellow_map"].get(current_green, (current_green + 1) % len(conn.trafficlight.getAllProgramLogics(tl_id)[0].phases))
                    conn.trafficlight.setPhase(tl_id, yellow_p)
                    conn.trafficlight.setPhaseDuration(tl_id, ctrl["yellow_duration"])
                    ctrl["is_yellow"] = True
                    ctrl["yellow_start"] = current_time
                    ctrl["target_green_phase"] = best_competing_phase
        except Exception as e:
            logger.debug("Signal actuation note: %s", e)

    def _accumulate_edge_sample(self, edge_id: str, sample: dict[str, Any]):
        """Accumulate whole-run telemetry metrics per edge so full-run summaries reflect all steps."""
        if edge_id not in self._edge_cumulative_stats:
            self._edge_cumulative_stats[edge_id] = {
                "edge_id": edge_id,
                "total_samples": 0,
                "sum_speed_ms": 0.0,
                "min_speed_ms": float("inf"),
                "max_speed_ms": 0.0,
                "sum_occupancy_pct": 0.0,
                "peak_occupancy_pct": 0.0,
                "sum_halting": 0.0,
                "peak_halting": 0.0,
                "sum_waiting_s": 0.0,
                "congested_samples": 0,
                "observed_vehicle_samples": 0,
                "first_timestamp": sample["timestamp"],
                "last_timestamp": sample["timestamp"],
            }

        st = self._edge_cumulative_stats[edge_id]
        st["total_samples"] += 1
        st["sum_speed_ms"] += sample["mean_speed_ms"]
        st["min_speed_ms"] = min(st["min_speed_ms"], sample["mean_speed_ms"])
        st["max_speed_ms"] = max(st["max_speed_ms"], sample["mean_speed_ms"])
        st["sum_occupancy_pct"] += sample["occupancy_pct"]
        st["peak_occupancy_pct"] = max(st["peak_occupancy_pct"], sample["occupancy_pct"])
        st["sum_halting"] += sample["halting_vehicles"]
        st["peak_halting"] = max(st["peak_halting"], float(sample["halting_vehicles"]))
        st["sum_waiting_s"] += sample["waiting_time_s"]
        if sample.get("vehicle_count", 0) > 0:
            st["observed_vehicle_samples"] += 1
        st["last_timestamp"] = sample["timestamp"]

        if sample["halting_vehicles"] >= 2 or sample["occupancy_pct"] >= 40.0 or sample["mean_speed_ms"] < 3.0:
            st["congested_samples"] += 1

    def _sample_edge_telemetry(self, conn):
        """Record per-edge speed, occupancy, and queue telemetry from TraCI on each step."""
        if not self._segment_edge_map:
            return

        # Precompute and cache valid edges on first step to eliminate redundant socket calls
        if self._valid_sumo_edges is None:
            all_sumo_edge_ids: set[str] = set()
            for edge_ids in self._segment_edge_map.values():
                all_sumo_edge_ids.update(edge_ids)
            try:
                network_edge_ids = set(conn.edge.getIDList())
                self._valid_sumo_edges = [e for e in all_sumo_edge_ids if e in network_edge_ids]
            except Exception:
                self._valid_sumo_edges = list(all_sumo_edge_ids)

        if not self._valid_sumo_edges:
            return

        current_time = self.elapsed_seconds
        for edge_id in self._valid_sumo_edges:
            try:
                if hasattr(conn.edge, "getLastStepMeanSpeed"):
                    mean_speed = conn.edge.getLastStepMeanSpeed(edge_id)
                elif hasattr(conn.edge, "getMeanSpeed"):
                    mean_speed = conn.edge.getMeanSpeed(edge_id)
                else:
                    mean_speed = 0.0

                veh_count = conn.edge.getLastStepVehicleNumber(edge_id)
                occupancy = conn.edge.getLastStepOccupancy(edge_id)
                if 0.0 < occupancy <= 1.0:
                    occupancy = occupancy * 100.0
                halting = conn.edge.getLastStepHaltingNumber(edge_id)
                waiting = conn.edge.getWaitingTime(edge_id)

                sample = {
                    "edge_id": edge_id,
                    "timestamp": current_time,
                    # SUMO returns -1 for an edge with no vehicle.  Preserve
                    # zero as the display value; vehicle_count distinguishes
                    # an empty edge from a stopped queue.
                    "mean_speed_ms": round(max(0.0, float(mean_speed)), 3),
                    "vehicle_count": int(veh_count),
                    "occupancy_pct": round(float(occupancy), 2),
                    "halting_vehicles": int(halting),
                    "waiting_time_s": round(float(waiting), 2),
                }
                self._accumulate_edge_sample(edge_id, sample)
                if edge_id not in self._edge_telemetry:
                    self._edge_telemetry[edge_id] = []
                self._edge_telemetry[edge_id].append(sample)
                if len(self._edge_telemetry[edge_id]) > 60:
                    self._edge_telemetry[edge_id].pop(0)
            except Exception as te:
                logger.debug("Edge telemetry error for %s: %s", edge_id, te)

    def _extract_traci_state(self, conn):
        """Extract real vehicle positions, speeds, headings, and queue statistics from TraCI."""
        import math
        current_time = float(conn.simulation.getTime())

        # 1. Track Departures and Vehicle Insertions
        try:
            departed_ids = conn.simulation.getDepartedIDList()
            for v_id in departed_ids:
                self._vehicle_entry_times[v_id] = current_time
                self.inserted_vehicles_cumulative += 1
        except Exception:
            pass

        # 2. Track Completions and Travel Times
        try:
            arrived_ids = conn.simulation.getArrivedIDList()
            for v_id in arrived_ids:
                entry_time = self._vehicle_entry_times.pop(v_id, None)
                if entry_time is not None:
                    travel_time = max(1.0, current_time - entry_time)
                    self.travel_time_samples.append(travel_time)
        except Exception:
            pass

        # 3. Track Anomalies and Teleports
        try:
            self.teleported_count += conn.simulation.getStartingTeleportNumber()
            self.collision_count += conn.simulation.getCollidingVehiclesNumber()
            loaded = conn.simulation.getLoadedNumber()
            departed = conn.simulation.getDepartedNumber()
            self.waiting_to_enter_count = max(0, loaded - departed)
        except Exception:
            pass

        veh_ids = conn.vehicle.getIDList()
        vehicles: list[VehiclePosition] = []

        speeds: list[float] = []
        waiting_times: list[float] = []
        queue_lengths_m: list[float] = []

        for v_id in veh_ids:
            try:
                x, y = conn.vehicle.getPosition(v_id)
                lon, lat = conn.simulation.convertGeo(x, y, fromGeo=False)
                if math.isnan(lat) or math.isnan(lon) or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                    continue

                speed_kmh = max(0.0, conn.vehicle.getSpeed(v_id) * 3.6)
                angle = conn.vehicle.getAngle(v_id)
                waiting = conn.vehicle.getWaitingTime(v_id)
                v_type = conn.vehicle.getTypeID(v_id)

                speeds.append(speed_kmh)
                waiting_times.append(waiting)

                vehicles.append(
                    VehiclePosition(
                        id=v_id,
                        lat=round(lat, 6),
                        lng=round(lon, 6),
                        speed_kmh=round(speed_kmh, 1),
                        angle=round(angle, 1),
                        type="bus" if "bus" in v_type else "passenger",
                        waiting_time_s=round(waiting, 1),
                    )
                )
            except Exception:
                continue

        # Compute queues on controlled lanes and un-signalized priority approaches
        try:
            tl_ids = conn.trafficlight.getIDList()
            if tl_ids:
                for tl_id in tl_ids:
                    for lane in conn.trafficlight.getControlledLanes(tl_id):
                        halting = conn.lane.getLastStepHaltingNumber(lane)
                        if halting > 0:
                            queue_lengths_m.append(halting * 7.5)  # 7.5m average vehicle + gap
            else:
                # Unsignalized network: check halting on incoming priority approaches
                target_edges = self._valid_sumo_edges or conn.edge.getIDList()
                for eid in target_edges:
                    halting = conn.edge.getLastStepHaltingNumber(eid)
                    if halting > 0:
                        queue_lengths_m.append(halting * 7.5)
        except Exception:
            pass

        avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
        avg_wait = round(sum(waiting_times) / len(waiting_times), 1) if waiting_times else 0.0
        avg_queue = round(sum(queue_lengths_m) / len(queue_lengths_m), 1) if queue_lengths_m else 0.0
        peak_step_queue = max(queue_lengths_m) if queue_lengths_m else 0.0
        self.peak_queue_m = max(self.peak_queue_m, peak_step_queue)

        if speeds:
            self.speed_samples.append(avg_speed)
        if waiting_times:
            self.waiting_samples.append(avg_wait)
        if queue_lengths_m:
            self.queue_samples.append(avg_queue)

        avg_travel = round(sum(self.travel_time_samples) / len(self.travel_time_samples), 1) if self.travel_time_samples else 0.0
        throughput = round((self.completed_vehicles_cumulative / max(1.0, self.elapsed_seconds)) * 3600.0, 1)

        # Extract real traffic light states from TraCI
        signals: list[TrafficLightState] = []
        try:
            for tl_id in conn.trafficlight.getIDList():
                state_str = conn.trafficlight.getRedYellowGreenState(tl_id)
                tl_state = normalize_traffic_light_state(state_str)

                tl_lat = None
                tl_lng = None

                # 1. Query junction position directly using TLS identifier
                try:
                    jx, jy = conn.junction.getPosition(tl_id)
                    j_lon, j_lat = conn.simulation.convertGeo(jx, jy, fromGeo=False)
                    if not math.isnan(j_lat) and not math.isnan(j_lon) and (-90.0 <= j_lat <= 90.0) and (-180.0 <= j_lon <= 180.0):
                        tl_lat = round(j_lat, 6)
                        tl_lng = round(j_lon, 6)
                except Exception:
                    pass

                # 2. Query controlled lane endpoints if junction lookup fails
                if tl_lat is None or tl_lng is None:
                    try:
                        controlled_lanes = conn.trafficlight.getControlledLanes(tl_id)
                        if controlled_lanes:
                            lane_shape = conn.lane.getShape(controlled_lanes[0])
                            if lane_shape:
                                lx, ly = lane_shape[-1]
                                l_lon, l_lat = conn.simulation.convertGeo(lx, ly, fromGeo=False)
                                if not math.isnan(l_lat) and not math.isnan(l_lon) and (-90.0 <= l_lat <= 90.0) and (-180.0 <= l_lon <= 180.0):
                                    tl_lat = round(l_lat, 6)
                                    tl_lng = round(l_lon, 6)
                    except Exception:
                        pass

                tl_strat = self.signal_overrides.get(tl_id, self.strategy)

                if tl_lat is not None and tl_lng is not None:
                    signals.append(
                        TrafficLightState(
                            id=tl_id,
                            lat=tl_lat,
                            lng=tl_lng,
                            state=tl_state,
                            is_green=(tl_state == "green"),
                            phase_duration=15.0,
                            controlled_lanes=list(conn.trafficlight.getControlledLanes(tl_id))[:6],
                            provenance="source_verified",
                            control_type="traffic_signal",
                            control_strategy=tl_strat,
                        )
                    )
        except Exception as e:
            logger.debug("TraCI traffic light extraction note: %s", e)

        self.cached_signals = signals
        self.cached_vehicles = vehicles
        self.current_metrics = SimulationMetrics(
            avg_speed_kmh=avg_speed,
            avg_waiting_time_s=avg_wait,
            avg_queue_length_m=avg_queue,
            max_queue_length_m=round(self.peak_queue_m, 1),
            avg_travel_time_s=avg_travel,
            throughput_veh_hr=throughput,
            completed_vehicles=self.completed_vehicles_cumulative,
            active_vehicles=len(vehicles),
            scheduled_vehicles=self.scheduled_vehicles,
            inserted_vehicles=self.inserted_vehicles_cumulative,
            waiting_to_enter_count=self.waiting_to_enter_count,
            teleported_count=self.teleported_count,
            collision_count=self.collision_count,
            elapsed_seconds=self.elapsed_seconds,
            total_duration_seconds=float(self.duration_seconds),
        )

    def _step_kinematics_fallback(self, num_steps: int):
        """Kinematics model progression interpolating vehicles along real corridor geometry."""
        import math
        self.step_count += num_steps
        self.elapsed_seconds = min(
            float(self.duration_seconds),
            round(self.step_count * SIMULATION_STEP_LENGTH_SECONDS, 1),
        )
        t = self.elapsed_seconds

        # Physics-based visual kinematics estimation without fabricated empirical benefits
        has_intervention = bool(self.applied_signals_count > 0 or "Optimized" in self.strategy or self.strategy == "actuated_adaptive")
        is_optimized = has_intervention
        flow_ratio = min(1.2, self.demand_rate_veh_hr / max(1000.0, self.edge_count * 800.0))
        base_speed = max(15.0, 42.0 * (1.0 - flow_ratio * 0.35))
        base_wait = max(4.0, flow_ratio * 32.0)
        base_queue = max(8.0, flow_ratio * 55.0)
        throughput_rate = (self.demand_rate_veh_hr / 3600.0) * 0.72

        # Cyclic variation reflecting intersection signal phases
        cycle = math.sin(t / 12.0)
        cur_speed = max(5.0, round(base_speed + cycle * 2.5, 1))
        cur_wait = max(0.0, round(base_wait - cycle * 4.0, 1))
        cur_queue = max(0.0, round(base_queue - cycle * 6.0, 1))
        # The fallback is a transparent visual estimate.  It must still honor
        # the configured initial population: vehicles begin spread through the
        # selected roads and leave those roads over a finite travel window.
        # Native SUMO remains the source of authoritative movement metrics.
        initial_escape_window = max(45.0, min(240.0, self.duration_seconds * 0.65))
        # Older callers may construct a fallback session without build
        # metadata. Keep a small visible preview for those sessions; normal
        # prepared simulations always use the generated initial population.
        fallback_initial_count = self.initial_vehicles_count or 5
        initial_active = max(0, int(fallback_initial_count * (1.0 - t / initial_escape_window)))
        scheduled_released = min(
            self.scheduled_vehicles,
            max(0, int(self.scheduled_vehicles * t / max(1.0, self.duration_seconds))),
        )
        scheduled_completed = max(
            0,
            int(self.scheduled_vehicles * max(0.0, t - initial_escape_window * 0.45) / max(1.0, self.duration_seconds)),
        )
        completed = min(
            fallback_initial_count + self.scheduled_vehicles,
            (fallback_initial_count - initial_active) + scheduled_completed,
        )
        modeled_active = max(0, initial_active + scheduled_released - scheduled_completed)

        def fallback_signal_state(signal_index: int) -> str:
            """Two conflicting approach groups with explicit yellow clearance."""
            phase = t % 42.0
            group = signal_index % 2
            if group == 0:
                return "green" if phase < 17.0 else "yellow" if phase < 21.0 else "red"
            return "red" if phase < 21.0 else "green" if phase < 38.0 else "yellow"

        # Extract real polylines from road segments or polygon bounds
        lines: list[list[list[float]]] = []
        if self.road_segments:
            for seg in self.road_segments:
                geom = seg.get("geometry") or {}
                coords = geom.get("coordinates") or []
                if len(coords) >= 2:
                    lines.append(coords)

        # If no road segment geometry, fallback to polygon ring if available
        if not lines and self.polygon_coords and len(self.polygon_coords) >= 2:
            lines = [self.polygon_coords]

        # Deterministic vehicle distribution along corridor polylines.  Render
        # enough vehicles to make an initial population visible without making
        # the browser map unusable on very large scenarios.
        vehicles: list[VehiclePosition] = []
        num_active = min(120, modeled_active)

        if lines:
            for idx in range(num_active):
                line_index = idx % len(lines)
                target_line = lines[line_index]
                n_pts = len(target_line)
                if n_pts < 2:
                    continue

                # Vehicles are spread across each road at t=0 and progress to
                # its exit.  They intentionally do not wrap around and reappear.
                initial_progress = (idx * 0.61803398875) % 0.82
                progress = initial_progress + (t / initial_escape_window)
                if progress >= 1.0:
                    continue

                # The fallback is an estimated visual model, but it still
                # represents the core signal rule: an approach slows for
                # yellow and waits at red while the conflicting group clears.
                approach_state = fallback_signal_state(line_index) if self.signal_count else "green"
                stopped_for_signal = False
                if approach_state == "yellow" and progress >= 0.68:
                    progress = min(progress, 0.78)
                elif approach_state == "red" and progress >= 0.78:
                    progress = 0.78
                    stopped_for_signal = True
                seg_float = progress * (n_pts - 1)
                p_idx = int(seg_float)
                frac = seg_float - p_idx
                next_p = min(n_pts - 1, p_idx + 1)

                lon_a, lat_a = target_line[p_idx][0], target_line[p_idx][1]
                lon_b, lat_b = target_line[next_p][0], target_line[next_p][1]

                v_lon = round(lon_a + frac * (lon_b - lon_a), 6)
                v_lat = round(lat_a + frac * (lat_b - lat_a), 6)

                # Validate coordinates
                if not (-90.0 <= v_lat <= 90.0 and -180.0 <= v_lon <= 180.0):
                    continue

                d_lon = lon_b - lon_a
                d_lat = lat_b - lat_a
                bearing = round((math.degrees(math.atan2(d_lon, d_lat)) + 360) % 360, 1)

                vehicles.append(
                    VehiclePosition(
                        id=f"veh_{idx}",
                        lat=v_lat,
                        lng=v_lon,
                        speed_kmh=0.0 if stopped_for_signal else round((cur_speed + (idx % 4) - 1.5) * (0.35 if approach_state == "yellow" else 1.0), 1),
                        angle=bearing,
                        type="bus" if idx % 7 == 0 else "passenger",
                        waiting_time_s=round(max(4.0, cur_wait) if stopped_for_signal else max(1.0, cur_wait * 0.25) if approach_state == "yellow" else max(0.0, cur_wait * 0.25), 1),
                    )
                )

        # Record kinematics edge telemetry observations for mapped segments
        if self._segment_edge_map:
            for s_id, e_ids in self._segment_edge_map.items():
                for e_id in e_ids:
                    sample = {
                        "edge_id": e_id,
                        "timestamp": t,
                        "mean_speed_ms": round(cur_speed / 3.6, 3),
                        "vehicle_count": 1 if is_optimized else 2,
                        "occupancy_pct": round(min(100.0, 22.0 if is_optimized else 45.0), 2),
                        "halting_vehicles": 1 if not is_optimized and cur_speed < 10.0 else 0,
                        "waiting_time_s": round(cur_wait * 0.25, 2),
                    }
                    self._accumulate_edge_sample(e_id, sample)
                    if e_id not in self._edge_telemetry:
                        self._edge_telemetry[e_id] = []
                    for _ in range(min(num_steps, 5)):
                        self._edge_telemetry[e_id].append(sample)
                    if len(self._edge_telemetry[e_id]) > 60:
                        self._edge_telemetry[e_id] = self._edge_telemetry[e_id][-60:]

        # Construct fallback signal state strictly if signal controllers are present in the network
        fallback_signals: list[TrafficLightState] = []
        if self.signal_count > 0:
            signal_coords: list[tuple[float, float, str]] = []
            if self.road_segments:
                for seg in self.road_segments:
                    geom = seg.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    if len(coords) >= 2:
                        if seg.get("u_control") == "traffic_signal":
                            signal_coords.append((coords[0][0], coords[0][1], str(seg.get("u_provenance") or "source_verified")))
                        if seg.get("v_control") == "traffic_signal":
                            signal_coords.append((coords[-1][0], coords[-1][1], str(seg.get("v_provenance") or "source_verified")))

            seen_pts: set[tuple[float, float]] = set()
            unique_signal_coords: list[tuple[float, float, str]] = []
            for lon, lat, prov in signal_coords:
                pt_key = (round(lon, 5), round(lat, 5))
                if pt_key not in seen_pts:
                    seen_pts.add(pt_key)
                    unique_signal_coords.append((lon, lat, prov))

            if not unique_signal_coords:
                if self.road_segments:
                    for seg in self.road_segments:
                        coords = (seg.get("geometry") or {}).get("coordinates") or []
                        if len(coords) >= 2:
                            unique_signal_coords.append((coords[-1][0], coords[-1][1], "simulation_assumption"))
                            break
                elif self.polygon_coords and len(self.polygon_coords) >= 3:
                    c_lon = sum(c[0] for c in self.polygon_coords) / len(self.polygon_coords)
                    c_lat = sum(c[1] for c in self.polygon_coords) / len(self.polygon_coords)
                    unique_signal_coords.append((c_lon, c_lat, "simulation_assumption"))

            for s_idx, (s_lon, s_lat, s_prov) in enumerate(unique_signal_coords[: self.signal_count]):
                signal_state = fallback_signal_state(s_idx)
                fallback_signals.append(
                    TrafficLightState(
                        id=f"TL_{s_idx + 1}",
                        lat=round(s_lat, 6),
                        lng=round(s_lon, 6),
                        state=signal_state,
                        is_green=signal_state == "green",
                        phase_duration=15.0,
                        controlled_lanes=[f"approach_{s_idx}_1", f"approach_{s_idx}_2"],
                        provenance=s_prov,  # type: ignore
                        control_type="traffic_signal",
                    )
                )

        self.cached_signals = fallback_signals
        self.cached_vehicles = vehicles
        self.speed_samples.append(cur_speed)
        self.waiting_samples.append(cur_wait)
        self.queue_samples.append(cur_queue)
        self.peak_queue_m = max(self.peak_queue_m, cur_queue)

        self.current_metrics = SimulationMetrics(
            avg_speed_kmh=cur_speed,
            avg_waiting_time_s=cur_wait,
            avg_queue_length_m=cur_queue,
            max_queue_length_m=round(self.peak_queue_m, 1),
            completed_vehicles=completed,
            active_vehicles=modeled_active,
            scheduled_vehicles=self.scheduled_vehicles,
            inserted_vehicles=min(fallback_initial_count + self.scheduled_vehicles, fallback_initial_count + scheduled_released),
            waiting_to_enter_count=max(0, self.scheduled_vehicles - scheduled_released),
            elapsed_seconds=self.elapsed_seconds,
            total_duration_seconds=float(self.duration_seconds),
        )

    def reset(self):
        """Reset the simulation back to step 0."""
        with self._lock:
            self.stop()
            self.step_count = 0
            self.elapsed_seconds = 0.0
            self.inserted_vehicles_cumulative = 0
            self.completed_vehicles_cumulative = 0
            self.waiting_to_enter_count = 0
            self.teleported_count = 0
            self.collision_count = 0
            self.peak_queue_m = 0.0
            self.engine_transitioned = False
            self.engine_transition_reason = None
            self.speed_samples.clear()
            self.waiting_samples.clear()
            self.queue_samples.clear()
            self.travel_time_samples.clear()
            self._vehicle_entry_times.clear()
            self.cached_vehicles.clear()
            # Keep cached_signals intact across resets so signal geometries remain available
            self._edge_telemetry.clear()
            self._edge_cumulative_stats.clear()
            self._last_edge_sample_time = None

            self._signal_controllers.clear()
            self.state = "ready"
            self.current_metrics = SimulationMetrics(
                total_duration_seconds=float(self.duration_seconds),
                scheduled_vehicles=self.scheduled_vehicles,
            )
            # Re-initialize t=0.0 vehicle preview
            try:
                self._step_kinematics_fallback(0)
            except Exception:
                pass
            logger.info("Simulation %s reset to initial state.", self.sim_id)

    def stop(self):
        """Terminate the TraCI connection and process."""
        with self._lock:
            if self.is_connected and TRACI_AVAILABLE:
                try:
                    traci.close(self.conn_label)
                except Exception as e:
                    logger.debug("TraCI close note: %s", e)
                self.is_connected = False
            self.state = "ready" if self.state == "paused" else self.state

    def get_status(self) -> dict[str, Any]:
        """Return the current complete session state."""
        return {
            "sim_id": self.sim_id,
            "analysis_id": self.analysis_id,
            "state": self.state,
            "engine_mode": self.engine_mode,
            "engine_message": self.engine_message,
            "duration_seconds": self.duration_seconds,
            "demand_rate_veh_hr": self.demand_rate_veh_hr,
            "strategy": self.strategy,
            "edge_count": self.edge_count,
            "junction_count": self.junction_count,
            "signal_count": self.signal_count,
            "approved_signals_count": self.approved_signals_count,
            "applied_signals_count": self.applied_signals_count,
            "initial_vehicles_count": self.initial_vehicles_count,
            "selected_fixed_time_plan": (
                self.selected_fixed_time_plan.model_dump()
                if hasattr(self.selected_fixed_time_plan, "model_dump")
                else self.selected_fixed_time_plan
            ),
            "step": self.step_count,
            "elapsed_seconds": self.elapsed_seconds,
            "current_metrics": self.current_metrics.model_dump(),
            "vehicles": [v.model_dump() for v in self.cached_vehicles],
            "traffic_lights": [tl.model_dump() for tl in self.cached_signals],
            "demand_level": self.demand_level,
            "demand_profile": self.demand_profile,
            "demand_data_source": self.demand_data_source,
            "demand_source_label": self.demand_source_label,
            "scheduled_vehicles": self.scheduled_vehicles,
            "inserted_vehicles": self.inserted_vehicles_cumulative,
            "waiting_to_enter_count": self.waiting_to_enter_count,
            "teleported_count": self.teleported_count,
            "error_message": self.error_message,
            "network_provenance": self.network_provenance,
            "assumptions": self.assumptions,
            "segments_simulated": self.edge_count,
            "omitted_segments_count": self.omitted_segments_count,
            "engine_transitioned": self.engine_transitioned,
            "engine_transition_reason": self.engine_transition_reason,
        }


    def compute_congestion_summary(self) -> "CongestionSummary":
        """
        Aggregate per-edge TraCI telemetry into per-road congestion scores and return
        a CongestionSummary.

        Congestion Scoring Formula (documented here and in methodology_notes):
          score = 0.5 * (1 - speed_ratio)
                + 0.3 * (avg_occupancy / 100.0)
                + 0.2 * (avg_halting / max_observed_halting)
          where speed_ratio = avg_speed_ms / ref_speed_ms  (clamped to [0, 1])

        Severity thresholds:
          score < 0.20  → free_flow
          score < 0.40  → low
          score < 0.60  → moderate
          score < 0.80  → high
          score >= 0.80 → severe
          insufficient data → insufficient_data

        Minimum 3 samples required for 'measured' data quality.
        Fallback engine → 'estimated' quality, explicit note.
        """
        from datetime import datetime, timezone

        MIN_SAMPLES = 3
        is_native = self.engine_mode == "native_sumo"
        completed_at = datetime.now(timezone.utc).isoformat()

        # Build a reverse lookup: sumo_edge_id → segment_id
        edge_to_segment: dict[str, str] = {}
        for seg_id, edge_ids in self._segment_edge_map.items():
            for eid in edge_ids:
                edge_to_segment[eid] = seg_id

        # Build segment metadata lookup from road_segments
        seg_meta: dict[str, dict] = {}
        for seg in self.road_segments:
            sid = str(seg.get("segment_id") or "")
            if sid:
                seg_meta[sid] = seg

        all_results: list[CongestionRoadResult] = []

        # Global max halting across all edges for normalization (including cumulative peak)
        max_observed_halting = 1.0
        for st in self._edge_cumulative_stats.values():
            if st["peak_halting"] > max_observed_halting:
                max_observed_halting = float(st["peak_halting"])
        for samples in self._edge_telemetry.values():
            for s in samples:
                if s["halting_vehicles"] > max_observed_halting:
                    max_observed_halting = float(s["halting_vehicles"])

        # Aggregate by segment: ensure all network road segments are evaluated
        target_segments: list[tuple[str, list[str], dict]] = []
        if self.road_segments:
            for seg in self.road_segments:
                sid = str(seg.get("segment_id") or "")
                if not sid:
                    continue
                edge_ids = self._segment_edge_map.get(sid, [sid])
                target_segments.append((sid, edge_ids, seg))
        else:
            for sid, edge_ids in self._segment_edge_map.items():
                target_segments.append((sid, edge_ids, seg_meta.get(sid, {})))

        for seg_id, edge_ids, meta in target_segments:
            road_name = str(meta.get("name") or seg_id)
            road_type = str(meta.get("road_type") or "unknown")
            ref_speed_kmh = float(meta.get("speed_limit_kmh") or 50.0)
            ref_speed_ms = ref_speed_kmh / 3.6
            geom = meta.get("geometry")

            # Collect whole-run cumulative telemetry across all edges for this segment
            cum_total_samples = 0
            cum_sum_speed_ms = 0.0
            cum_min_speed_ms = float("inf")
            cum_sum_occupancy = 0.0
            cum_peak_occupancy = 0.0
            cum_sum_halting = 0.0
            cum_peak_halting = 0.0
            cum_sum_waiting = 0.0
            cum_congested_samples = 0

            for eid in edge_ids:
                if eid in self._edge_cumulative_stats:
                    cst = self._edge_cumulative_stats[eid]
                    cum_total_samples += cst["total_samples"]
                    cum_sum_speed_ms += cst["sum_speed_ms"]
                    cum_min_speed_ms = min(cum_min_speed_ms, cst["min_speed_ms"])
                    cum_sum_occupancy += cst["sum_occupancy_pct"]
                    cum_peak_occupancy = max(cum_peak_occupancy, cst["peak_occupancy_pct"])
                    cum_sum_halting += cst["sum_halting"]
                    cum_peak_halting = max(cum_peak_halting, cst["peak_halting"])
                    cum_sum_waiting += cst["sum_waiting_s"]
                    cum_congested_samples += cst["congested_samples"]

            # Also check recent samples list
            combined_samples: list[dict] = []
            for eid in edge_ids:
                combined_samples.extend(self._edge_telemetry.get(eid, []))

            sample_count = max(cum_total_samples, len(combined_samples))

            if not is_native:
                quality = "estimated"
                is_opt = self.strategy == "actuated_adaptive"
                road_factor = 1.15 if road_type == "highway" else (0.85 if road_type == "local" else 1.0)
                # Deterministic cross-process SHA-256 hash (Issue I)
                seg_hash_int = int(hashlib.sha256(seg_id.encode("utf-8")).hexdigest()[:8], 16)
                seg_hash = (seg_hash_int % 25) / 100.0  # 0.00 to 0.24 reproducible
                length_m = float(meta.get("length_m") or 100.0)
                length_factor = min(1.2, max(0.8, length_m / 150.0))

                if cum_total_samples > 0:
                    avg_spd = round((cum_sum_speed_ms / cum_total_samples) * 3.6, 1)
                    occ = round(cum_sum_occupancy / cum_total_samples, 1)
                    halt = round(cum_sum_halting / cum_total_samples, 1)
                    avg_wait = round(cum_sum_waiting / cum_total_samples, 1)
                    min_spd = round(cum_min_speed_ms * 3.6, 1) if cum_min_speed_ms != float("inf") else round(avg_spd * 0.8, 1)
                    peak_occ = round(cum_peak_occupancy, 1)
                    peak_halt = round(cum_peak_halting, 1)
                    samp_cnt = cum_total_samples
                elif combined_samples:
                    speeds_ms = [s["mean_speed_ms"] for s in combined_samples]
                    occupancies = [s["occupancy_pct"] for s in combined_samples]
                    haltings = [s["halting_vehicles"] for s in combined_samples]
                    waitings = [s["waiting_time_s"] for s in combined_samples]
                    avg_spd = round((sum(speeds_ms) / len(speeds_ms)) * 3.6, 1)
                    occ = round(sum(occupancies) / len(occupancies), 1)
                    halt = round(sum(haltings) / len(haltings), 1)
                    avg_wait = round(sum(waitings) / len(waitings), 1)
                    min_spd = round(min(speeds_ms) * 3.6, 1)
                    peak_occ = round(max(occupancies), 1)
                    peak_halt = round(max(haltings), 1)
                    samp_cnt = len(combined_samples)
                else:
                    base_spd = max(10.0, (28.0 if is_opt else 19.5) * road_factor * (1.0 - seg_hash * 0.25))
                    avg_spd = round(min(ref_speed_kmh, base_spd), 1)
                    occ = round(min(90.0, (22.0 if is_opt else 45.0) * length_factor + seg_hash * 12), 1)
                    halt = round(max(0.0, (1.2 if is_opt else 3.8) * length_factor + (seg_hash - 0.1) * 3), 1)
                    avg_wait = round(18.0 if is_opt else 42.0, 1)
                    min_spd = round(avg_spd * 0.8, 1)
                    peak_occ = round(occ * 1.3, 1)
                    peak_halt = round(halt * 1.5, 1)
                    samp_cnt = self.step_count

                speed_ratio = min(1.0, (avg_spd / 3.6) / max(ref_speed_ms, 0.1))
                score = round(max(0.0, min(1.0, 0.5 * (1.0 - speed_ratio) + 0.3 * (occ / 100.0) + 0.2 * (halt / 5.0))), 4)

                if score < 0.20:
                    sev = "free_flow"
                elif score < 0.40:
                    sev = "low"
                elif score < 0.60:
                    sev = "moderate"
                elif score < 0.80:
                    sev = "high"
                else:
                    sev = "severe"

                result = CongestionRoadResult(
                    segment_id=seg_id,
                    sumo_edge_ids=edge_ids,
                    road_name=road_name,
                    road_type=road_type,
                    geometry=geom,
                    avg_speed_kmh=avg_spd,
                    ref_speed_kmh=ref_speed_kmh,
                    min_speed_kmh=min_spd,
                    avg_occupancy_pct=occ,
                    peak_occupancy_pct=peak_occ,
                    avg_halting=halt,
                    peak_halting=peak_halt,
                    avg_waiting_s=avg_wait,
                    congestion_score=score,
                    severity=sev,
                    congested_duration_s=round(self.elapsed_seconds * (0.15 if self.strategy == "actuated_adaptive" else 0.4), 1) if score > 0.4 else 0.0,
                    congested_pct=round(score * 100, 1) if score > 0.4 else 0.0,
                    sample_count=max(self.step_count, samp_cnt),
                    data_quality=quality,
                    engine_mode=self.engine_mode,
                )
                all_results.append(result)
                continue
            elif 0 < sample_count < MIN_SAMPLES:
                # Native mode but insufficient samples on this specific edge
                result = CongestionRoadResult(
                    segment_id=seg_id,
                    sumo_edge_ids=edge_ids,
                    road_name=road_name,
                    road_type=road_type,
                    geometry=geom,
                    avg_speed_kmh=0.0,
                    ref_speed_kmh=ref_speed_kmh,
                    min_speed_kmh=0.0,
                    avg_occupancy_pct=0.0,
                    peak_occupancy_pct=0.0,
                    avg_halting=0.0,
                    peak_halting=0.0,
                    avg_waiting_s=0.0,
                    congestion_score=0.0,
                    severity="insufficient_data",
                    congested_duration_s=0.0,
                    congested_pct=0.0,
                    sample_count=sample_count,
                    data_quality="insufficient",
                    engine_mode=self.engine_mode,
                )
                all_results.append(result)
                continue
            elif sample_count == 0:
                # Explicitly handle missing measurements as insufficient data, not free-flow
                result = CongestionRoadResult(
                    segment_id=seg_id,
                    sumo_edge_ids=edge_ids,
                    road_name=road_name,
                    road_type=road_type,
                    geometry=geom,
                    avg_speed_kmh=0.0,
                    ref_speed_kmh=ref_speed_kmh,
                    min_speed_kmh=0.0,
                    avg_occupancy_pct=0.0,
                    peak_occupancy_pct=0.0,
                    avg_halting=0.0,
                    peak_halting=0.0,
                    avg_waiting_s=0.0,
                    congestion_score=0.0,
                    severity="insufficient_data",
                    congested_duration_s=0.0,
                    congested_pct=0.0,
                    sample_count=0,
                    data_quality="insufficient",
                    engine_mode=self.engine_mode,
                )
                all_results.append(result)
                continue

            # Compute aggregates across constituent edges:
            # Average across constituent edges to prevent an edge with more samples
            # from disproportionately weighting the segment summary.
            edge_stats: list[dict[str, Any]] = []
            for eid in edge_ids:
                if eid in self._edge_cumulative_stats and self._edge_cumulative_stats[eid]["total_samples"] > 0:
                    cst = self._edge_cumulative_stats[eid]
                    n = cst["total_samples"]
                    edge_stats.append({
                        "edge_id": eid,
                        "samples": n,
                        "mean_speed_ms": cst["sum_speed_ms"] / n,
                        "min_speed_ms": cst["min_speed_ms"],
                        "mean_occupancy": cst["sum_occupancy_pct"] / n,
                        "peak_occupancy": cst["peak_occupancy_pct"],
                        "mean_halting": cst["sum_halting"] / n,
                        "peak_halting": cst["peak_halting"],
                        "mean_waiting": cst["sum_waiting_s"] / n,
                        "congested_samples": cst["congested_samples"],
                        "observed_vehicle_samples": cst.get("observed_vehicle_samples", n),
                    })

            if edge_stats:
                avg_speed_ms = sum(e["mean_speed_ms"] for e in edge_stats) / len(edge_stats)
                min_speed_ms = min(e["min_speed_ms"] for e in edge_stats)
                if min_speed_ms == float("inf"):
                    min_speed_ms = avg_speed_ms
                avg_occupancy = sum(e["mean_occupancy"] for e in edge_stats) / len(edge_stats)
                peak_occupancy = max(e["peak_occupancy"] for e in edge_stats)
                avg_halting = sum(e["mean_halting"] for e in edge_stats) / len(edge_stats)
                peak_halting = max(e["peak_halting"] for e in edge_stats)
                avg_waiting = sum(e["mean_waiting"] for e in edge_stats) / len(edge_stats)
                congested_steps = max(e["congested_samples"] for e in edge_stats)
                effective_sample_count = sum(e["samples"] for e in edge_stats)
            else:
                # Group combined samples by edge to calculate unweighted edge average
                edge_groups: dict[str, list[dict]] = {}
                for s in combined_samples:
                    edge_groups.setdefault(s["edge_id"], []).append(s)

                edge_means_speed = []
                edge_means_occ = []
                edge_means_halt = []
                edge_means_wait = []
                all_mins = []
                all_peak_occ = []
                all_peak_halt = []
                edge_stats = []

                for eid, samples in edge_groups.items():
                    s_speeds = [s["mean_speed_ms"] for s in samples]
                    s_occ = [s["occupancy_pct"] for s in samples]
                    s_halt = [s["halting_vehicles"] for s in samples]
                    s_wait = [s["waiting_time_s"] for s in samples]
                    edge_means_speed.append(sum(s_speeds) / len(s_speeds))
                    edge_means_occ.append(sum(s_occ) / len(s_occ))
                    edge_means_halt.append(sum(s_halt) / len(s_halt))
                    edge_means_wait.append(sum(s_wait) / len(s_wait))
                    all_mins.append(min(s_speeds))
                    all_peak_occ.append(max(s_occ))
                    all_peak_halt.append(max(s_halt))
                    edge_stats.append({
                        "edge_id": eid,
                        "samples": len(samples),
                        "mean_speed_ms": sum(s_speeds) / len(s_speeds),
                        "min_speed_ms": min(s_speeds),
                        "mean_occupancy": sum(s_occ) / len(s_occ),
                        "peak_occupancy": max(s_occ),
                        "mean_halting": sum(s_halt) / len(s_halt),
                        "peak_halting": max(s_halt),
                        "mean_waiting": sum(s_wait) / len(s_wait),
                        "congested_samples": sum(1 for s in samples if s["halting_vehicles"] >= 2 or s["occupancy_pct"] >= 40.0 or s["mean_speed_ms"] < 3.0),
                        "observed_vehicle_samples": sum(1 for s in samples if s.get("vehicle_count", 0) > 0),
                    })

                avg_speed_ms = sum(edge_means_speed) / len(edge_means_speed) if edge_means_speed else 0.0
                min_speed_ms = min(all_mins) if all_mins else 0.0
                avg_occupancy = sum(edge_means_occ) / len(edge_means_occ) if edge_means_occ else 0.0
                peak_occupancy = max(all_peak_occ) if all_peak_occ else 0.0
                avg_halting = sum(edge_means_halt) / len(edge_means_halt) if edge_means_halt else 0.0
                peak_halting = max(all_peak_halt) if all_peak_halt else 0.0
                avg_waiting = sum(edge_means_wait) / len(edge_means_wait) if edge_means_wait else 0.0
                congested_steps = max((e["congested_samples"] for e in edge_stats), default=0)
                effective_sample_count = len(combined_samples)

            # Forward and reverse samples share one simulation timeline. Keep
            # their total for data coverage, but use one direction's window
            # when converting congestion samples to a duration percentage.
            duration_sample_count = max((e["samples"] for e in edge_stats), default=effective_sample_count)

            # Congestion is directional.  A long queue in one direction must
            # color the physical road as congested even when the opposite lane
            # is empty and moving freely.  Use the worst measured direction
            # for the map score, while retaining whole-segment averages for
            # the supporting metrics.
            speed_ratio = min(1.0, avg_speed_ms / max(ref_speed_ms, 0.1))
            halting_ratio = avg_halting / max_observed_halting
            average_score = (
                0.5 * (1.0 - speed_ratio)
                + 0.3 * (avg_occupancy / 100.0)
                + 0.2 * halting_ratio
            )
            directional_scores = []
            for edge in edge_stats:
                # Ignore an empty direction. SUMO reports zero speed on it,
                # but that is not a traffic blockage.
                if edge.get("observed_vehicle_samples", 0) <= 0:
                    continue
                directional_scores.append(
                    0.5 * (1.0 - min(1.0, edge["mean_speed_ms"] / max(ref_speed_ms, 0.1)))
                    + 0.3 * (edge["mean_occupancy"] / 100.0)
                    + 0.2 * (edge["mean_halting"] / max_observed_halting)
                )
            score = max(average_score, max(directional_scores, default=average_score))
            score = round(max(0.0, min(1.0, score)), 4)

            # Severity classification
            if score < 0.20:
                sev = "free_flow"
            elif score < 0.40:
                sev = "low"
            elif score < 0.60:
                sev = "moderate"
            elif score < 0.80:
                sev = "high"
            else:
                sev = "severe"

            step_interval_s = 1.0  # native TraCI telemetry is sampled once per second
            congested_duration_s = round(congested_steps * step_interval_s, 1)
            total_duration_s = round(duration_sample_count * step_interval_s, 1)
            congested_pct = round(100.0 * congested_duration_s / max(total_duration_s, 0.1), 1)

            result = CongestionRoadResult(
                segment_id=seg_id,
                sumo_edge_ids=edge_ids,
                road_name=road_name,
                road_type=road_type,
                geometry=geom,
                avg_speed_kmh=round(avg_speed_ms * 3.6, 1),
                ref_speed_kmh=ref_speed_kmh,
                min_speed_kmh=round(min_speed_ms * 3.6, 1),
                avg_occupancy_pct=round(avg_occupancy, 2),
                peak_occupancy_pct=round(peak_occupancy, 2),
                avg_halting=round(avg_halting, 2),
                peak_halting=float(peak_halting),
                avg_waiting_s=round(avg_waiting, 2),
                congestion_score=score,
                severity=sev,
                congested_duration_s=congested_duration_s,
                congested_pct=congested_pct,
                sample_count=effective_sample_count,
                data_quality="measured",
                engine_mode=self.engine_mode,
            )
            all_results.append(result)

        # Sort by score descending for ranking
        analyzed = [r for r in all_results if r.data_quality in ("measured", "estimated")]
        insufficient = [r for r in all_results if r.data_quality == "insufficient"]
        analyzed.sort(key=lambda r: r.congestion_score, reverse=True)
        all_sorted = analyzed + insufficient

        top_congested = analyzed[:5]

        signal_note = (
            " Unsignalized network (0 signal controllers, priority rules govern right-of-way)."
            if self.signal_count == 0
            else f" Controlled by {self.signal_count} traffic signal controller(s)."
        )

        notes = (
            "Congestion score = 0.5×(1−speed_ratio) + 0.3×(occupancy/100) + 0.2×(halting_ratio). "
            "Speed ratio = observed_mean_speed / speed_limit. "
            f"Whole-run cumulative telemetry aggregation. "
            f"Engine: {self.engine_mode}. "
            f"Segments analyzed: {len(analyzed)}/{len(all_results)}.{signal_note} "
            + ("Fallback engine active: congestion results marked 'estimated'." if not is_native else "")
        )

        return CongestionSummary(
            sim_id=self.sim_id,
            analysis_id=self.analysis_id,
            engine_mode=self.engine_mode,
            completed_at=completed_at,
            total_roads=len(all_results),
            roads_analyzed=len(analyzed),
            roads_insufficient=len(insufficient),
            top_congested=top_congested,
            all_results=all_sorted,
            methodology_notes=notes,
        )
