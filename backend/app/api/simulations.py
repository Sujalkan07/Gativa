"""
FastAPI Router for SUMO Traffic Simulation & TraCI Controls.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query, status

from app.models.schemas import (
    ErrorResponse,
    ScenarioComparisonResult,
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
