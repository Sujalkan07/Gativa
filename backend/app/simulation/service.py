"""
Simulation Service: High-level orchestrator connecting Gativa Analyses to SUMO simulation sessions.
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
        self._base_work_dir = Path(tempfile.gettempdir()) / "gativa_sumo"
        self._base_work_dir.mkdir(parents=True, exist_ok=True)

    async def prepare(self, req: SimulationPrepareRequest) -> SimulationStatusResponse:
        """Prepare network and trip demand for an existing analysis ID."""
        sim_id = str(uuid.uuid4())
        work_dir = self._base_work_dir / sim_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Retrieve analysis details if available
        analysis = await get_analysis_by_id(req.analysis_id)
        segments_dict = []
        if analysis and analysis.segments:
            segments_dict = [s.model_dump() for s in analysis.segments]

        # Build SUMO network files
        builder = SumoNetworkBuilder(work_dir)
        build_meta = builder.build(
            segments=segments_dict,
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
        )

        session = SimulationSession(
            sim_id=sim_id,
            analysis_id=req.analysis_id,
            work_dir=work_dir,
            cfg_file=Path(build_meta["cfg_file"]),
            duration_seconds=req.duration_seconds,
            demand_rate_veh_hr=req.demand_rate_veh_hr,
            strategy=req.strategy,
            edge_count=build_meta["edge_count"],
            junction_count=build_meta["junction_count"],
            signal_count=build_meta["signal_count"],
        )

        self._sessions[sim_id] = session
        logger.info("Prepared SUMO simulation %s for analysis %s", sim_id, req.analysis_id)
        return SimulationStatusResponse(**session.get_status())

    def get_session(self, sim_id: str) -> Optional[SimulationSession]:
        return self._sessions.get(sim_id)

    def start(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.start()
        return SimulationStatusResponse(**session.get_status())

    def pause(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.pause()
        return SimulationStatusResponse(**session.get_status())

    def step(self, sim_id: str, num_steps: int = 2) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.step(num_steps=num_steps)
        return SimulationStatusResponse(**session.get_status())

    def reset(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.reset()
        return SimulationStatusResponse(**session.get_status())

    def stop(self, sim_id: str) -> SimulationStatusResponse:
        session = self._sessions.get(sim_id)
        if not session:
            raise KeyError(f"Simulation {sim_id} not found")
        session.stop()
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

        # Compile comparison using live metrics
        return ScenarioComparator.compare(
            sim_id=session.sim_id,
            analysis_id=session.analysis_id,
            duration_seconds=session.duration_seconds,
            optimized_metrics=session.current_metrics,
        )


# Global singleton instance
simulation_service = SimulationService()
