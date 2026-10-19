"""
Simulation Service: High-level orchestrator connecting Gativa Analyses to SUMO simulation sessions.
Executes dual independent simulation sessions (Baseline: Fixed-Time vs Optimized: Actuated Adaptive)
to guarantee honest, empirical comparative analytics without synthesized metrics.
"""
from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from app.models.schemas import (
    ScenarioComparisonResult,
    SimulationPrepareRequest,
    SimulationStatusResponse,
)
from app.services.analysis import get_analysis_by_id
from app.simulation.network_builder import SumoNetworkBuilder
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

        # Build SUMO network files for Optimized scenario
        builder_opt = SumoNetworkBuilder(opt_dir)
        build_meta_opt = builder_opt.build(
            segments=segments_dict,
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            polygon_coords=polygon_coords,
        )

        # Build SUMO network files for Baseline scenario (identical topology & seed)
        builder_base = SumoNetworkBuilder(base_dir)
        build_meta_base = builder_base.build(
            segments=segments_dict,
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            polygon_coords=polygon_coords,
        )

        # 1. Primary/Optimized Session (rendered on frontend map)
        opt_session = SimulationSession(
            sim_id=sim_id,
            analysis_id=req.analysis_id,
            work_dir=opt_dir,
            cfg_file=Path(build_meta_opt["cfg_file"]),
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            strategy=req.strategy,
            edge_count=build_meta_opt["edge_count"],
            junction_count=build_meta_opt["junction_count"],
            signal_count=build_meta_opt["signal_count"],
            road_segments=segments_dict,
            netconvert_used=build_meta_opt["netconvert_used"],
            polygon_coords=polygon_coords,
        )

        # 2. Baseline Session (Fixed-time uncoordinated control on identical topology)
        base_session = SimulationSession(
            sim_id=f"base_{sim_id}",
            analysis_id=req.analysis_id,
            work_dir=base_dir,
            cfg_file=Path(build_meta_base["cfg_file"]),
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            strategy="fixed_time",
            edge_count=build_meta_base["edge_count"],
            junction_count=build_meta_base["junction_count"],
            signal_count=build_meta_base["signal_count"],
            road_segments=segments_dict,
            netconvert_used=build_meta_base["netconvert_used"],
            polygon_coords=polygon_coords,
        )

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

        return ScenarioComparator.compare(
            sim_id=session.sim_id,
            analysis_id=session.analysis_id,
            duration_seconds=session.duration_seconds,
            engine_mode=session.engine_mode,
            baseline_metrics=base_session.current_metrics if base_session else None,
            optimized_metrics=session.current_metrics,
            baseline_strategy="Baseline (Fixed-Time Signal Control)",
            optimized_strategy=(
                "Optimized (Actuated Adaptive Signal Control)"
                if session.strategy == "actuated_adaptive"
                else f"Optimized ({session.strategy})"
            ),
            step_count=session.step_count,
        )


# Global singleton instance
simulation_service = SimulationService()
