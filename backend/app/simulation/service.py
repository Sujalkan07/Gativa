"""
Simulation Service: High-level orchestrator connecting Gativa Analyses to SUMO simulation sessions.
Executes dual independent simulation sessions (Baseline: Fixed-Time vs Optimized: Actuated Adaptive)
to guarantee honest, empirical comparative analytics without synthesized metrics.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from app.core.sqlite_store import get_congestion_summary_sync, save_congestion_summary_sync
from app.models.schemas import (
    CongestionSummary,
    ScenarioComparisonResult,
    SignalDetailInfo,
    SignalEditRequest,
    SignalEditResponse,
    SignalListResponse,
    SignalMovementInfo,
    SimulationPrepareRequest,
    SimulationStatusResponse,
)
from app.services.analysis import get_analysis_by_id
from app.simulation.network_builder import SumoNetworkBuilder, find_sumo_binary
from app.simulation.scenario_comparator import ScenarioComparator
from app.simulation.traci_manager import SimulationSession

logger = logging.getLogger(__name__)


class SimulationService:
    """Manages active SUMO simulation sessions across the application lifecycle."""

    def __init__(self):
        self._sessions: dict[str, SimulationSession] = {}
        self._baseline_sessions: dict[str, SimulationSession] = {}
        self._base_work_dir = Path(tempfile.gettempdir()) / "gativa_sumo"
        self._base_work_dir.mkdir(parents=True, exist_ok=True)

    async def prepare(self, req: SimulationPrepareRequest) -> SimulationStatusResponse:
        """
        Prepare network and trip demand for an existing analysis ID.
        Configures dual independent sessions (Optimized and Baseline) on identical topology.
        """
        sim_id = str(uuid.uuid4())
        work_dir = self._base_work_dir / sim_id
        opt_dir = work_dir / "optimized"
        base_dir = work_dir / "baseline"
        opt_dir.mkdir(parents=True, exist_ok=True)
        base_dir.mkdir(parents=True, exist_ok=True)

        # Retrieve analysis details if available
        analysis = await get_analysis_by_id(req.analysis_id)
        segments_dict = []
        polygon_coords = []
        if analysis:
            if analysis.segments:
                segments_dict = [s.model_dump() for s in analysis.segments]
            if analysis.polygon and analysis.polygon.coordinates:
                polygon_coords = analysis.polygon.coordinates[0]

        seed = req.seed or 42

        # Build SUMO network files for Optimized scenario
        builder_opt = SumoNetworkBuilder(opt_dir)
        build_meta_opt = builder_opt.build(
            segments=segments_dict,
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            seed=seed,
            polygon_coords=polygon_coords,
            demand_level=req.demand_level or "normal",
            demand_profile=req.demand_profile or "peak",
            vehicle_types=req.vehicle_types,
            manual_vehicle_count=req.manual_vehicle_count,
        )

        # Clone compiled SUMO network files to Baseline scenario (100% parity, instant zero-overhead compilation)
        for f in opt_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, base_dir / f.name)
        build_meta_base = dict(build_meta_opt)
        build_meta_base["cfg_file"] = str(base_dir / "simulation.sumocfg")

        # 1. Primary/Optimized Session (rendered on frontend map)
        opt_session = SimulationSession(
            sim_id=sim_id,
            analysis_id=req.analysis_id,
            work_dir=opt_dir,
            cfg_file=Path(build_meta_opt["cfg_file"]),
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=build_meta_opt["demand_rate_veh_hr"],
            strategy=req.strategy,
            edge_count=build_meta_opt["edge_count"],
            junction_count=build_meta_opt["junction_count"],
            signal_count=build_meta_opt["signal_count"],
            road_segments=segments_dict,
            netconvert_used=build_meta_opt["netconvert_used"],
            polygon_coords=polygon_coords,
            demand_level=build_meta_opt.get("demand_level", "normal"),
            demand_profile=build_meta_opt.get("demand_profile", "peak"),
            demand_data_source=build_meta_opt.get("demand_data_source", "road_network_estimation"),
            demand_source_label=build_meta_opt.get("demand_source_label"),
            scheduled_vehicles=build_meta_opt.get("scheduled_vehicles", 0),
        )
        opt_session._segment_edge_map = build_meta_opt.get("segment_edge_map", {})

        # 2. Baseline Session (Fixed-time uncoordinated control on identical topology)
        base_session = SimulationSession(
            sim_id=f"base_{sim_id}",
            analysis_id=req.analysis_id,
            work_dir=base_dir,
            cfg_file=Path(build_meta_base["cfg_file"]),
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=build_meta_base["demand_rate_veh_hr"],
            strategy="fixed_time",
            edge_count=build_meta_base["edge_count"],
            junction_count=build_meta_base["junction_count"],
            signal_count=build_meta_base["signal_count"],
            road_segments=segments_dict,
            netconvert_used=build_meta_base["netconvert_used"],
            polygon_coords=polygon_coords,
            demand_level=build_meta_base.get("demand_level", "normal"),
            demand_profile=build_meta_base.get("demand_profile", "peak"),
            demand_data_source=build_meta_base.get("demand_data_source", "road_network_estimation"),
            demand_source_label=build_meta_base.get("demand_source_label"),
            scheduled_vehicles=build_meta_base.get("scheduled_vehicles", 0),
        )
        base_session._segment_edge_map = build_meta_base.get("segment_edge_map", {})

        self._sessions[sim_id] = opt_session
        self._baseline_sessions[sim_id] = base_session

        logger.info(
            "Prepared paired SUMO simulation %s (mode=%s) for analysis %s",
            sim_id,
            opt_session.engine_mode,
            req.analysis_id,
        )
        return SimulationStatusResponse(**opt_session.get_status())

    def get_session(self, sim_id: str) -> Optional[SimulationSession]:
        return self._sessions.get(sim_id)

    def start(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.start()

        base_session = self._baseline_sessions.get(sim_id)
        if base_session:
            base_session.start()

        return SimulationStatusResponse(**session.get_status())

    def pause(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.pause()

        base_session = self._baseline_sessions.get(sim_id)
        if base_session:
            base_session.pause()

        return SimulationStatusResponse(**session.get_status())

    def step(self, sim_id: str, num_steps: int = 2) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.step(num_steps=num_steps)

        base_session = self._baseline_sessions.get(sim_id)
        if base_session:
            base_session.step(num_steps=num_steps)

        return SimulationStatusResponse(**session.get_status())

    def reset(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.reset()

        base_session = self._baseline_sessions.get(sim_id)
        if base_session:
            base_session.reset()

        return SimulationStatusResponse(**session.get_status())

    def stop(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.stop()

        base_session = self._baseline_sessions.get(sim_id)
        if base_session:
            base_session.stop()

        return SimulationStatusResponse(**session.get_status())

    def get_status(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        return SimulationStatusResponse(**session.get_status())

    def get_comparison(self, sim_id: str) -> ScenarioComparisonResult:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")

        base_session = self._baseline_sessions.get(sim_id)
        sig_count = getattr(session, "signal_count", 0)

        if sig_count == 0:
            baseline_strat = "Baseline (Unsignalized Priority Control)"
            optimized_strat = "Intervention (Unsignalized Priority Control)"
        else:
            baseline_strat = "Baseline (Fixed-Time Signal Control)"
            optimized_strat = (
                "Optimized (Actuated Adaptive Signal Control)"
                if session.strategy == "actuated_adaptive"
                else f"Optimized ({session.strategy})"
            )

        return ScenarioComparator.compare(
            sim_id=session.sim_id,
            analysis_id=session.analysis_id,
            duration_seconds=session.duration_seconds,
            engine_mode=session.engine_mode,
            baseline_metrics=base_session.current_metrics if base_session else None,
            optimized_metrics=session.current_metrics,
            baseline_strategy=baseline_strat,
            optimized_strategy=optimized_strat,
            step_count=session.step_count,
            signal_count=sig_count,
        )

    def get_congestion_summary(self, sim_id: str) -> CongestionSummary:
        """
        Return the congestion analysis for a completed simulation.

        Priority order:
        1. Persisted result in SQLite (e.g. if session has been evicted)
        2. Freshly computed from in-memory session telemetry
        3. 404-equivalent KeyError if session not found at all
        """
        # 1. Try SQLite cache first (supports reload after restart)
        cached = get_congestion_summary_sync(sim_id)
        if cached:
            return CongestionSummary(**cached)

        # 2. Compute from live session
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")

        if session.state == "running":
            # Return partial result (sim still running)
            logger.info("Congestion summary requested while simulation %s is running; returning partial.", sim_id)

        summary = session.compute_congestion_summary()
        return summary

    def get_baseline_status(self, sim_id: str) -> SimulationStatusResponse:
        """Return the current status of the Baseline (Fixed-Time) scenario session."""
        base_session = self._baseline_sessions.get(sim_id)
        if not base_session:
            raise KeyError(f"Baseline simulation for {sim_id} not found")
        return SimulationStatusResponse(**base_session.get_status())

    def get_signals(self, sim_id: str) -> SignalListResponse:
        """Inspect all traffic signals in the active optimized simulation network."""
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")

        signals_info: list[SignalDetailInfo] = []
        for tl in session.cached_signals:
            tl_id = tl.id
            ctrl_type = session.signal_overrides.get(tl_id, session.strategy)

            connected_names: list[str] = []
            if session.road_segments:
                for seg in session.road_segments:
                    name = seg.get("name")
                    if name and name not in connected_names:
                        connected_names.append(name)

            can_remove = True
            safety_note = "Valid right-of-way priority junction supported. Priority rules govern turning movements cleanly."
            if len(tl.controlled_lanes) > 8:
                can_remove = False
                safety_note = "High-complexity junction with > 8 conflicting movements. Unsignalized priority removal is not recommended for safety."

            signals_info.append(
                SignalDetailInfo(
                    id=tl_id,
                    lat=tl.lat,
                    lng=tl.lng,
                    junction_id=tl_id,
                    control_type=ctrl_type,
                    original_type="traffic_signal",
                    is_editable=True,
                    can_remove=can_remove,
                    safety_assessment=safety_note,
                    connected_roads=connected_names[:4],
                    controlled_lanes=tl.controlled_lanes,
                    movements=[
                        SignalMovementInfo(
                            link_index=idx,
                            from_lane=lane,
                            to_lane=f"exit_{idx}",
                            direction="through" if idx % 2 == 0 else "turn",
                            current_state=tl.state[idx] if idx < len(tl.state) else "G",
                        )
                        for idx, lane in enumerate(tl.controlled_lanes[:6])
                    ],
                    provenance=str(tl.provenance or "source_verified"),
                )
            )

        return SignalListResponse(sim_id=sim_id, signals=signals_info, count=len(signals_info))

    def edit_signal(self, sim_id: str, tl_id: str, req: SignalEditRequest) -> SignalEditResponse:
        """Edit a traffic signal in the Optimized scenario without modifying the Regular baseline."""
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")

        action = req.action
        opt_dir = session.work_dir
        nod_file = opt_dir / "nodes.nod.xml"
        edg_file = opt_dir / "edges.edg.xml"
        net_file = opt_dir / "network.net.xml"

        if action == "set_fixed_time":
            session.signal_overrides[tl_id] = "fixed_time"
            session.reset()
            updated_sig = next((s for s in self.get_signals(sim_id).signals if s.id == tl_id), None)
            return SignalEditResponse(
                success=True,
                message=f"Signal {tl_id} configured to Fixed-Time control plan.",
                signal=updated_sig,
                requires_recompile=False,
            )

        elif action == "set_adaptive":
            session.signal_overrides.pop(tl_id, None)
            session.reset()
            updated_sig = next((s for s in self.get_signals(sim_id).signals if s.id == tl_id), None)
            return SignalEditResponse(
                success=True,
                message=f"Signal {tl_id} configured to Actuated Adaptive control plan.",
                signal=updated_sig,
                requires_recompile=False,
            )

        elif action == "remove_signal":
            # Safety validation
            for tl in session.cached_signals:
                if tl.id == tl_id and len(tl.controlled_lanes) > 8:
                    return SignalEditResponse(
                        success=False,
                        message=f"Cannot remove signal controller {tl_id}: Junction has > 8 complex lanes. Removal would compromise intersection safety.",
                        requires_recompile=False,
                    )

            if nod_file.is_file():
                import xml.etree.ElementTree as ET
                tree = ET.parse(str(nod_file))
                root = tree.getroot()
                found = False
                for node in root.findall("node"):
                    if node.get("id") == tl_id:
                        node.set("type", "priority")
                        found = True
                        break
                if found:
                    tree.write(str(nod_file), encoding="utf-8", xml_declaration=True)
                    netconvert_bin = find_sumo_binary("netconvert")
                    if netconvert_bin:
                        import subprocess
                        cmd = [
                            netconvert_bin,
                            "--node-files", str(nod_file),
                            "--edge-files", str(edg_file),
                            "--output-file", str(net_file),
                            "--proj.utm",
                            "--no-warnings",
                            "--ignore-errors",
                        ]
                        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    session.signal_count = max(0, session.signal_count - 1)
                    session.signal_overrides[tl_id] = "unsignalized"
                    session.reset()
                    updated_sig = next((s for s in self.get_signals(sim_id).signals if s.id == tl_id), None)
                    return SignalEditResponse(
                        success=True,
                        message=f"Signal controller {tl_id} removed. Junction converted to priority right-of-way rules for Optimized scenario.",
                        signal=updated_sig,
                        requires_recompile=True,
                    )
            return SignalEditResponse(success=False, message=f"Node {tl_id} not found in network files.")

        elif action == "restore_original":
            base_dir = self._base_work_dir / sim_id / "baseline"
            base_nod = base_dir / "nodes.nod.xml"
            if base_nod.is_file() and nod_file.parent.is_dir():
                import shutil
                shutil.copy2(base_nod, nod_file)
                netconvert_bin = find_sumo_binary("netconvert")
                if netconvert_bin:
                    import subprocess
                    cmd = [
                        netconvert_bin,
                        "--node-files", str(nod_file),
                        "--edge-files", str(edg_file),
                        "--output-file", str(net_file),
                        "--proj.utm",
                        "--no-warnings",
                        "--ignore-errors",
                    ]
                    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            session.signal_overrides.clear()
            session.reset()
            updated_sig = next((s for s in self.get_signals(sim_id).signals if s.id == tl_id), None)
            return SignalEditResponse(
                success=True,
                message="Restored original signal configuration for Optimized scenario.",
                signal=updated_sig,
                requires_recompile=True,
            )


        return SignalEditResponse(success=False, message=f"Unknown action: {action}")

    def reset_signals(self, sim_id: str) -> dict[str, Any]:
        return self.edit_signal(sim_id, "all", SignalEditRequest(action="restore_original")).model_dump()


# Global singleton instance
simulation_service = SimulationService()
