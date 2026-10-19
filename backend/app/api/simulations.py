"""
FastAPI Router for SUMO Traffic Simulation & TraCI Controls.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query, status

from app.models.schemas import (
    CongestionSummary,
    ErrorResponse,
    ScenarioComparisonResult,
    SignalDetailInfo,
    SignalEditRequest,
    SignalEditResponse,
    SignalListResponse,
    SimulationPrepareRequest,
    SimulationStatusResponse,
)
from app.simulation.service import simulation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulations", tags=["Simulation"])


@router.post(
    "/prepare",
    response_model=SimulationStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare a new SUMO traffic simulation for an analysis",
)
async def prepare_simulation(req: SimulationPrepareRequest):
    try:
        return await simulation_service.prepare(req)
    except Exception as e:
        logger.error("Failed to prepare simulation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare simulation: {str(e)}",
        )


@router.post(
    "/{sim_id}/start",
    response_model=SimulationStatusResponse,
    summary="Start or resume SUMO simulation",
)
async def start_simulation(sim_id: str):
    try:
        return simulation_service.start(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.post(
    "/{sim_id}/pause",
    response_model=SimulationStatusResponse,
    summary="Pause running SUMO simulation",
)
async def pause_simulation(sim_id: str):
    try:
        return simulation_service.pause(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.post(
    "/{sim_id}/step",
    response_model=SimulationStatusResponse,
    summary="Advance SUMO simulation by specified steps and retrieve live vehicle coordinates",
)
async def step_simulation(
    sim_id: str,
    steps: int = Query(default=2, ge=1, le=20, description="Number of simulation steps to advance"),
):
    try:
        return simulation_service.step(sim_id, num_steps=steps)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.post(
    "/{sim_id}/reset",
    response_model=SimulationStatusResponse,
    summary="Reset SUMO simulation to initial state",
)
async def reset_simulation(sim_id: str):
    try:
        return simulation_service.reset(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.post(
    "/{sim_id}/stop",
    response_model=SimulationStatusResponse,
    summary="Stop and clean up SUMO simulation session",
)
async def stop_simulation(sim_id: str):
    try:
        return simulation_service.stop(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.get(
    "/{sim_id}",
    response_model=SimulationStatusResponse,
    summary="Get current SUMO simulation status and vehicle positions",
)
async def get_simulation_status(sim_id: str):
    try:
        return simulation_service.get_status(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.get(
    "/{sim_id}/comparison",
    response_model=ScenarioComparisonResult,
    summary="Get Baseline vs Optimized scenario comparison results",
)
async def get_scenario_comparison(sim_id: str):
    try:
        return simulation_service.get_comparison(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.get(
    "/{sim_id}/congestion",
    response_model=CongestionSummary,
    summary="Get post-simulation road-level congestion analysis",
    description=(
        "Returns per-road congestion scores aggregated from SUMO TraCI edge telemetry. "
        "Available immediately after simulation starts (partial data). "
        "Results are persisted to SQLite on simulation completion. "
        "data_quality='measured' requires native SUMO engine; "
        "data_quality='estimated' or 'insufficient' indicates fallback/partial data."
    ),
)
async def get_congestion_results(sim_id: str):
    try:
        return simulation_service.get_congestion_summary(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found or congestion data unavailable",
        )
    except Exception as e:
        logger.error("Failed to compute congestion summary for %s: %s", sim_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute congestion analysis: {str(e)}",
        )


@router.get(
    "/{sim_id}/baseline",
    response_model=SimulationStatusResponse,
    summary="Get current Baseline (Regular traffic) simulation status and vehicle positions",
)
async def get_baseline_status(sim_id: str):
    try:
        return simulation_service.get_baseline_status(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline simulation for {sim_id} not found",
        )


@router.get(
    "/{sim_id}/signals",
    response_model=SignalListResponse,
    summary="List all traffic signals and their current status for the simulation",
)
async def get_simulation_signals(sim_id: str):
    try:
        return simulation_service.get_signals(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )


@router.post(
    "/{sim_id}/signals/{tl_id}/edit",
    response_model=SignalEditResponse,
    summary="Inspect and edit a traffic signal in the Optimized scenario",
)
async def edit_simulation_signal(sim_id: str, tl_id: str, req: SignalEditRequest):
    try:
        return simulation_service.edit_signal(sim_id, tl_id, req)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{sim_id}/signals/reset",
    response_model=SignalListResponse,
    summary="Reset all traffic signals back to their original configuration",
)
async def reset_simulation_signals(sim_id: str):
    try:
        return simulation_service.reset_signals(sim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {sim_id} not found",
        )

