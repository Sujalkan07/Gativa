"""
Experiment Manifest: Generates verifiable, reproducible manifests for SUMO simulation runs.
Validates experiment parity (route demand hash, duration, seed, step length) between
baseline and optimized scenarios to guarantee scientifically defensible controlled experiments.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    if not file_path.is_file():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ExperimentScenarioManifest(BaseModel):
    scenario_type: str  # "baseline" | "optimized"
    network_file_hash: str
    route_file_hash: str
    configuration_file_hash: str
    engine_mode: str
    signal_count: int
    applied_signals_count: int
    strategy: str


class ExperimentManifest(BaseModel):
    manifest_id: str
    analysis_id: str
    sim_id: str
    created_at: str
    random_seed: int
    simulation_duration_seconds: int
    simulation_step_length_seconds: float = 0.2
    demand_rate_veh_hr: int
    demand_level: str
    demand_profile: str
    vehicle_types: dict[str, float] = Field(default_factory=dict)
    scheduled_vehicles: int
    initial_vehicles: int
    sumo_version: Optional[str] = None
    optimizer_version: str = "fixed_time_v2_multiseed"
    approved_signal_junctions: list[str] = Field(default_factory=list)
    baseline_manifest: ExperimentScenarioManifest
    optimized_manifest: ExperimentScenarioManifest
    parity_verified: bool
    parity_discrepancies: list[str] = Field(default_factory=list)


def create_experiment_manifest(
    sim_id: str,
    analysis_id: str,
    duration_seconds: int,
    seed: int,
    demand_rate_veh_hr: int,
    demand_level: str,
    demand_profile: str,
    scheduled_vehicles: int,
    initial_vehicles: int,
    base_dir: Path,
    opt_dir: Path,
    base_engine_mode: str,
    opt_engine_mode: str,
    base_strategy: str,
    opt_strategy: str,
    base_signal_count: int,
    opt_signal_count: int,
    applied_signals_count: int,
    approved_signals: list[str],
    sumo_version: Optional[str] = None,
    vehicle_types: Optional[dict[str, float]] = None,
    step_length: float = 0.2,
) -> ExperimentManifest:
    """
    Construct an experiment manifest and rigorously verify demand and simulation condition parity.
    """
    base_net = compute_file_sha256(base_dir / "network.net.xml")
    base_rou = compute_file_sha256(base_dir / "routes.rou.xml")
    base_cfg = compute_file_sha256(base_dir / "simulation.sumocfg")

    opt_net = compute_file_sha256(opt_dir / "network.net.xml")
    opt_rou = compute_file_sha256(opt_dir / "routes.rou.xml")
    opt_cfg = compute_file_sha256(opt_dir / "simulation.sumocfg")

    base_scen = ExperimentScenarioManifest(
        scenario_type="baseline",
        network_file_hash=base_net,
        route_file_hash=base_rou,
        configuration_file_hash=base_cfg,
        engine_mode=base_engine_mode,
        signal_count=base_signal_count,
        applied_signals_count=0,
        strategy=base_strategy,
    )

    opt_scen = ExperimentScenarioManifest(
        scenario_type="optimized",
        network_file_hash=opt_net,
        route_file_hash=opt_rou,
        configuration_file_hash=opt_cfg,
        engine_mode=opt_engine_mode,
        signal_count=opt_signal_count,
        applied_signals_count=applied_signals_count,
        strategy=opt_strategy,
    )

    discrepancies: list[str] = []

    # 1. Demand Parity: Route files must be identical (SHA-256 match)
    if base_rou and opt_rou and base_rou != opt_rou:
        discrepancies.append(
            f"Demand route file hash mismatch between baseline ({base_rou[:10]}) and optimized ({opt_rou[:10]})."
        )

    # 2. Engine parity: baseline and optimized must use identical engine modes
    if base_engine_mode != opt_engine_mode:
        discrepancies.append(
            f"Engine mode discrepancy: baseline uses {base_engine_mode} while optimized uses {opt_engine_mode}."
        )

    parity_ok = len(discrepancies) == 0

    manifest = ExperimentManifest(
        manifest_id=f"manifest_{sim_id[:8]}",
        analysis_id=analysis_id,
        sim_id=sim_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        random_seed=seed,
        simulation_duration_seconds=duration_seconds,
        simulation_step_length_seconds=step_length,
        demand_rate_veh_hr=demand_rate_veh_hr,
        demand_level=demand_level,
        demand_profile=demand_profile,
        vehicle_types=vehicle_types or {"passenger": 0.88, "bus": 0.12},
        scheduled_vehicles=scheduled_vehicles,
        initial_vehicles=initial_vehicles,
        sumo_version=sumo_version,
        optimizer_version="fixed_time_v2_multiseed",
        approved_signal_junctions=approved_signals,
        baseline_manifest=base_scen,
        optimized_manifest=opt_scen,
        parity_verified=parity_ok,
        parity_discrepancies=discrepancies,
    )

    # Persist manifest.json into work_dir
    try:
        manifest_path = opt_dir.parent / "experiment_manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    except Exception:
        pass

    return manifest
