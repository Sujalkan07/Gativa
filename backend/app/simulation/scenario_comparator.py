"""
Scenario Comparator: Evaluates Baseline (Fixed-Time) vs Optimized (Adaptive Actuated) strategies.
Calculates honest absolute and percentage variance across core metrics with zero synthetic multipliers.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models.schemas import (
    ComparisonStatus,
    ScenarioComparisonResult,
    ScenarioMetricRow,
    SimulationEngineMode,
    SimulationMetrics,
)

logger = logging.getLogger(__name__)


class ScenarioComparator:
    """Executes or compiles honest comparison between Baseline and Optimized signal control."""

    @staticmethod
    def compare(
        sim_id: str,
        analysis_id: str,
        duration_seconds: int = 600,
        engine_mode: SimulationEngineMode = "unavailable",
        baseline_metrics: Optional[SimulationMetrics] = None,
        optimized_metrics: Optional[SimulationMetrics] = None,
        baseline_strategy: str = "Baseline (Fixed-Time Signal Control)",
        optimized_strategy: str = "Optimized (Actuated Adaptive Signal Control)",
        step_count: int = 0,
    ) -> ScenarioComparisonResult:
        """
        Produce side-by-side scenario comparison table with genuine empirical variance.
        Never synthesizes numbers or applies artificial scaling multipliers.
        """
        empty_metrics = SimulationMetrics(
            avg_speed_kmh=0.0,
            avg_waiting_time_s=0.0,
            avg_queue_length_m=0.0,
            completed_vehicles=0,
            active_vehicles=0,
            elapsed_seconds=0.0,
            total_duration_seconds=float(duration_seconds),
        )

        has_baseline = (
            baseline_metrics is not None
            and (baseline_metrics.elapsed_seconds > 0.0 or baseline_metrics.avg_speed_kmh > 0.0 or baseline_metrics.completed_vehicles > 0)
        )
        has_optimized = (
            optimized_metrics is not None
            and (optimized_metrics.elapsed_seconds > 0.0 or optimized_metrics.avg_speed_kmh > 0.0 or optimized_metrics.completed_vehicles > 0)
        )

        # 1. Check for Pending state (simulation has not stepped yet)
        if not has_baseline and not has_optimized and step_count == 0:
            rows = [
                ScenarioMetricRow(
                    metric="Average Speed",
                    baseline="—",
                    optimized="—",
                    variance="Pending step",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Waiting Time",
                    baseline="—",
                    optimized="—",
                    variance="Pending step",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Queue Length",
                    baseline="—",
                    optimized="—",
                    variance="Pending step",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Completed Vehicles",
                    baseline="—",
                    optimized="—",
                    variance="Pending step",
                    is_improvement=False,
                ),
            ]
            return ScenarioComparisonResult(
                sim_id=sim_id,
                analysis_id=analysis_id,
                duration_seconds=duration_seconds,
                engine_mode=engine_mode,
                comparison_status="pending",
                baseline_strategy=baseline_strategy,
                optimized_strategy=optimized_strategy,
                baseline_metrics=empty_metrics,
                optimized_metrics=empty_metrics,
                rows=rows,
                methodology_notes=f"Comparison pending simulation execution ({engine_mode} engine, seed 42, 0 steps). Advance simulation to collect empirical metrics.",
            )

        # 2. Check for Insufficient Data state
        if baseline_metrics is None or optimized_metrics is None:
            rows = [
                ScenarioMetricRow(
                    metric="Average Speed",
                    baseline=f"{baseline_metrics.avg_speed_kmh:.1f} km/h" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_speed_kmh:.1f} km/h" if optimized_metrics else "—",
                    variance="Insufficient data",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Waiting Time",
                    baseline=f"{baseline_metrics.avg_waiting_time_s:.1f} s" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_waiting_time_s:.1f} s" if optimized_metrics else "—",
                    variance="Insufficient data",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Queue Length",
                    baseline=f"{baseline_metrics.avg_queue_length_m:.1f} m" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_queue_length_m:.1f} m" if optimized_metrics else "—",
                    variance="Insufficient data",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Completed Vehicles",
                    baseline=f"{baseline_metrics.completed_vehicles} vehs" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.completed_vehicles} vehs" if optimized_metrics else "—",
                    variance="Insufficient data",
                    is_improvement=False,
                ),
            ]
            return ScenarioComparisonResult(
                sim_id=sim_id,
                analysis_id=analysis_id,
                duration_seconds=duration_seconds,
                engine_mode=engine_mode,
                comparison_status="insufficient_data",
                baseline_strategy=baseline_strategy,
                optimized_strategy=optimized_strategy,
                baseline_metrics=baseline_metrics or empty_metrics,
                optimized_metrics=optimized_metrics or empty_metrics,
                rows=rows,
                methodology_notes=f"Insufficient simulation data collected under {engine_mode} engine to perform dual scenario evaluation.",
            )

        # 3. Calculate genuine empirical variances
        # 1. Average Speed (Higher is better)
        speed_diff = optimized_metrics.avg_speed_kmh - baseline_metrics.avg_speed_kmh
        if baseline_metrics.avg_speed_kmh > 0:
            speed_pct = (speed_diff / baseline_metrics.avg_speed_kmh) * 100.0
        else:
            speed_pct = 0.0
        optimized_metrics.variance_speed_pct = round(speed_pct, 1)

        # 2. Average Waiting Time (Lower is better)
        wait_diff = optimized_metrics.avg_waiting_time_s - baseline_metrics.avg_waiting_time_s
        if baseline_metrics.avg_waiting_time_s > 0:
            wait_pct = (wait_diff / baseline_metrics.avg_waiting_time_s) * 100.0
        else:
            wait_pct = 0.0
        optimized_metrics.variance_waiting_pct = round(wait_pct, 1)

        # 3. Average Queue Length (Lower is better)
        queue_diff = optimized_metrics.avg_queue_length_m - baseline_metrics.avg_queue_length_m
        if baseline_metrics.avg_queue_length_m > 0:
            queue_pct = (queue_diff / baseline_metrics.avg_queue_length_m) * 100.0
        else:
            queue_pct = 0.0
        optimized_metrics.variance_queue_pct = round(queue_pct, 1)

        # 4. Completed Vehicles (Higher is better)
        veh_diff = optimized_metrics.completed_vehicles - baseline_metrics.completed_vehicles
        if baseline_metrics.completed_vehicles > 0:
            veh_pct = (veh_diff / baseline_metrics.completed_vehicles) * 100.0
        else:
            veh_pct = 0.0
        optimized_metrics.variance_completed_pct = round(veh_pct, 1)

        rows = [
            ScenarioMetricRow(
                metric="Average Speed",
                baseline=f"{baseline_metrics.avg_speed_kmh:.1f} km/h",
                optimized=f"{optimized_metrics.avg_speed_kmh:.1f} km/h",
                variance=f"↑ +{speed_pct:.1f}%" if speed_pct >= 0 else f"↓ {speed_pct:.1f}%",
                is_improvement=speed_pct >= 0,
            ),
            ScenarioMetricRow(
                metric="Average Waiting Time",
                baseline=f"{baseline_metrics.avg_waiting_time_s:.1f} s/veh",
                optimized=f"{optimized_metrics.avg_waiting_time_s:.1f} s/veh",
                variance=f"↓ {wait_pct:.1f}% delay" if wait_pct < 0 else f"↑ +{wait_pct:.1f}% delay",
                is_improvement=wait_pct <= 0,
            ),
            ScenarioMetricRow(
                metric="Average Queue Length",
                baseline=f"{baseline_metrics.avg_queue_length_m:.1f} m",
                optimized=f"{optimized_metrics.avg_queue_length_m:.1f} m",
                variance=f"↓ {queue_pct:.1f}% spillback" if queue_pct < 0 else f"↑ +{queue_pct:.1f}%",
                is_improvement=queue_pct <= 0,
            ),
            ScenarioMetricRow(
                metric="Completed Vehicles",
                baseline=f"{baseline_metrics.completed_vehicles} vehs",
                optimized=f"{optimized_metrics.completed_vehicles} vehs",
                variance=f"↑ +{veh_pct:.1f}% throughput" if veh_pct >= 0 else f"↓ {veh_pct:.1f}%",
                is_improvement=veh_pct >= 0,
            ),
        ]

        notes = (
            f"Empirical evaluation under {engine_mode} engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
            f"(seed 42, {step_count} simulation steps). "
            f"Baseline: Fixed-Time vs Optimized: Actuated Adaptive."
        )

        return ScenarioComparisonResult(
            sim_id=sim_id,
            analysis_id=analysis_id,
            duration_seconds=duration_seconds,
            engine_mode=engine_mode,
            comparison_status="completed",
            baseline_strategy=baseline_strategy,
            optimized_strategy=optimized_strategy,
            baseline_metrics=baseline_metrics,
            optimized_metrics=optimized_metrics,
            rows=rows,
            methodology_notes=notes,
        )
