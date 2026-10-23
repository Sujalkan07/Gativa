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
        baseline_engine_mode: Optional[SimulationEngineMode] = None,
        signal_count: Optional[int] = None,
        approved_signals_count: Optional[int] = None,
        applied_signals_count: Optional[int] = None,
        initial_vehicles_count: Optional[int] = None,
        selected_fixed_time_plan: Optional[Any] = None,
        engine_transitioned: bool = False,
        baseline_engine_transitioned: bool = False,
        optimizer_validation_passed: Optional[bool] = None,
        optimizer_status: Optional[str] = None,
    ) -> ScenarioComparisonResult:
        """
        Produce side-by-side scenario comparison table with genuine empirical variance.
        Never synthesizes numbers or applies artificial scaling multipliers.
        Accurately discloses unsignalized networks when signal_count == 0.
        """
        if signal_count == 0:
            if baseline_strategy == "Baseline (Fixed-Time Signal Control)":
                baseline_strategy = "Baseline (Unsignalized Priority Control)"
            if optimized_strategy == "Optimized (Actuated Adaptive Signal Control)":
                optimized_strategy = "Intervention (Unsignalized Priority Control)"

        approved_signals_count = approved_signals_count if approved_signals_count is not None else 0
        applied_signals_count = applied_signals_count if applied_signals_count is not None else 0
        initial_vehicles_count = initial_vehicles_count if initial_vehicles_count is not None else 0

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

        if engine_transitioned or baseline_engine_transitioned:
            transition_rows = [
                ScenarioMetricRow(
                    metric="Average Speed",
                    baseline=f"{baseline_metrics.avg_speed_kmh:.1f} km/h" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_speed_kmh:.1f} km/h" if optimized_metrics else "—",
                    variance="Not comparable (engine transitioned mid-run)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Waiting Time",
                    baseline=f"{baseline_metrics.avg_waiting_time_s:.1f} s" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_waiting_time_s:.1f} s" if optimized_metrics else "—",
                    variance="Not comparable (engine transitioned mid-run)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Queue Length",
                    baseline=f"{baseline_metrics.avg_queue_length_m:.1f} m" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_queue_length_m:.1f} m" if optimized_metrics else "—",
                    variance="Not comparable (engine transitioned mid-run)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Completed Vehicles",
                    baseline=f"{baseline_metrics.completed_vehicles} vehs" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.completed_vehicles} vehs" if optimized_metrics else "—",
                    variance="Not comparable (engine transitioned mid-run)",
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
                rows=transition_rows,
                methodology_notes=(
                    "Scenario comparison invalidated because simulation execution encountered a runtime "
                    "error and transitioned between native SUMO and fallback kinematics. Empirical comparison cannot be established."
                ),
                signal_count=signal_count,
                approved_signals_count=approved_signals_count or 0,
                applied_signals_count=applied_signals_count or 0,
                initial_vehicles_count=initial_vehicles_count or 0,
                selected_fixed_time_plan=selected_fixed_time_plan,
            )

        if baseline_engine_mode is not None and baseline_engine_mode != engine_mode:
            mismatch_rows = [
                ScenarioMetricRow(
                    metric="Average Speed",
                    baseline=f"{baseline_metrics.avg_speed_kmh:.1f} km/h" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_speed_kmh:.1f} km/h" if optimized_metrics else "—",
                    variance="Not comparable (engine mismatch)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Waiting Time",
                    baseline=f"{baseline_metrics.avg_waiting_time_s:.1f} s" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_waiting_time_s:.1f} s" if optimized_metrics else "—",
                    variance="Not comparable (engine mismatch)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Average Queue Length",
                    baseline=f"{baseline_metrics.avg_queue_length_m:.1f} m" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.avg_queue_length_m:.1f} m" if optimized_metrics else "—",
                    variance="Not comparable (engine mismatch)",
                    is_improvement=False,
                ),
                ScenarioMetricRow(
                    metric="Completed Vehicles",
                    baseline=f"{baseline_metrics.completed_vehicles} vehs" if baseline_metrics else "—",
                    optimized=f"{optimized_metrics.completed_vehicles} vehs" if optimized_metrics else "—",
                    variance="Not comparable (engine mismatch)",
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
                rows=mismatch_rows,
                methodology_notes=(
                    "Scenario comparison withheld because the baseline ran with "
                    f"{baseline_engine_mode} while the optimized run used {engine_mode}. "
                    "Engine modes must match before metric variances are meaningful."
                ),
                signal_count=signal_count,
                approved_signals_count=approved_signals_count or 0,
                applied_signals_count=applied_signals_count or 0,
                initial_vehicles_count=initial_vehicles_count or 0,
                selected_fixed_time_plan=selected_fixed_time_plan,
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
                signal_count=signal_count,
                approved_signals_count=approved_signals_count,
                applied_signals_count=applied_signals_count,
                initial_vehicles_count=initial_vehicles_count,
                selected_fixed_time_plan=selected_fixed_time_plan,
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
                signal_count=signal_count,
                approved_signals_count=approved_signals_count,
                applied_signals_count=applied_signals_count,
                initial_vehicles_count=initial_vehicles_count,
                selected_fixed_time_plan=selected_fixed_time_plan,
            )

        # 3. Calculate genuine empirical variances with honest zero-baseline handling
        def calc_metric_variance(
            opt_val: float,
            base_val: float,
            unit: str,
            higher_is_better: bool = True,
            is_int: bool = False,
        ) -> tuple[Optional[float], float, str, bool]:
            diff = round(opt_val - base_val, 2)
            if base_val <= 0.0:
                if opt_val <= 0.0:
                    val_str = "0" if is_int else "0.0"
                    variance_str = f"{val_str} {unit} (no change)"
                    return 0.0, 0.0, variance_str, False
                else:
                    arrow = "↑" if diff > 0 else "↓"
                    diff_str = f"{int(diff):+d}" if is_int else f"{diff:+.1f}"
                    is_improvement = (diff > 0) if higher_is_better else (diff < 0)
                    reg_note = "" if is_improvement else ", regression"
                    variance_str = f"{arrow} {diff_str} {unit} (N/A — zero baseline{reg_note})"
                    return None, diff, variance_str, is_improvement

            diff_str = f"{int(diff):+d}" if is_int else f"{diff:+.1f}"
            if diff == 0.0:
                variance_str = f"0.0% ({diff_str} {unit}, no change)"
                return 0.0, 0.0, variance_str, False

            pct = round((diff / base_val * 100.0), 1)
            if higher_is_better:
                is_improvement = diff > 0
                arrow = "↑" if diff > 0 else "↓"
                reg_str = "" if is_improvement else ", regression"
                variance_str = f"{arrow} {pct:+.1f}% ({diff_str} {unit}{reg_str})"
            else:
                is_improvement = diff < 0
                arrow = "↓" if diff < 0 else "↑"
                reg_str = ", regression" if diff > 0 else ""
                variance_str = f"{arrow} {pct:+.1f}% ({diff_str} {unit}{reg_str})"
            return pct, diff, variance_str, is_improvement

        # 1. Average Speed (Higher is better)
        speed_pct, speed_diff, speed_var, speed_imp = calc_metric_variance(
            optimized_metrics.avg_speed_kmh, baseline_metrics.avg_speed_kmh, "km/h", higher_is_better=True
        )
        optimized_metrics.variance_speed_pct = speed_pct

        # 2. Average Waiting Time (Lower is better)
        wait_pct, wait_diff, wait_var, wait_imp = calc_metric_variance(
            optimized_metrics.avg_waiting_time_s, baseline_metrics.avg_waiting_time_s, "s", higher_is_better=False
        )
        optimized_metrics.variance_waiting_pct = wait_pct

        # 3. Average Queue Length (Lower is better)
        queue_pct, queue_diff, queue_var, queue_imp = calc_metric_variance(
            optimized_metrics.avg_queue_length_m, baseline_metrics.avg_queue_length_m, "m", higher_is_better=False
        )
        optimized_metrics.variance_queue_pct = queue_pct

        # 4. Maximum Queue Length (Lower is better)
        max_q_pct, max_q_diff, max_q_var, max_q_imp = calc_metric_variance(
            optimized_metrics.max_queue_length_m, baseline_metrics.max_queue_length_m, "m", higher_is_better=False
        )
        optimized_metrics.variance_max_queue_pct = max_q_pct

        # 5. Average Travel Time (Lower is better)
        tt_pct, tt_diff, tt_var, tt_imp = calc_metric_variance(
            optimized_metrics.avg_travel_time_s, baseline_metrics.avg_travel_time_s, "s", higher_is_better=False
        )
        optimized_metrics.variance_travel_time_pct = tt_pct

        # 6. Network Throughput (Higher is better)
        tp_pct, tp_diff, tp_var, tp_imp = calc_metric_variance(
            optimized_metrics.throughput_veh_hr, baseline_metrics.throughput_veh_hr, "veh/h", higher_is_better=True
        )
        optimized_metrics.variance_throughput_pct = tp_pct

        # 7. Completed Vehicles (Higher is better)
        veh_pct, veh_diff, veh_var, veh_imp = calc_metric_variance(
            float(optimized_metrics.completed_vehicles), float(baseline_metrics.completed_vehicles), "vehs", higher_is_better=True, is_int=True
        )
        optimized_metrics.variance_completed_pct = veh_pct

        primary_rows = [
            ScenarioMetricRow(
                metric="Average Speed",
                baseline=f"{baseline_metrics.avg_speed_kmh:.1f} km/h",
                optimized=f"{optimized_metrics.avg_speed_kmh:.1f} km/h",
                variance=speed_var,
                is_improvement=speed_imp,
            ),
            ScenarioMetricRow(
                metric="Average Waiting Time",
                baseline=f"{baseline_metrics.avg_waiting_time_s:.1f} s/veh",
                optimized=f"{optimized_metrics.avg_waiting_time_s:.1f} s/veh",
                variance=wait_var,
                is_improvement=wait_imp,
            ),
            ScenarioMetricRow(
                metric="Average Queue Length",
                baseline=f"{baseline_metrics.avg_queue_length_m:.1f} m",
                optimized=f"{optimized_metrics.avg_queue_length_m:.1f} m",
                variance=queue_var,
                is_improvement=queue_imp,
            ),
            ScenarioMetricRow(
                metric="Completed Vehicles",
                baseline=f"{baseline_metrics.completed_vehicles} vehs",
                optimized=f"{optimized_metrics.completed_vehicles} vehs",
                variance=veh_var,
                is_improvement=veh_imp,
            ),
        ]

        extended_rows = [
            ScenarioMetricRow(
                metric="Maximum Queue Length",
                baseline=f"{baseline_metrics.max_queue_length_m:.1f} m",
                optimized=f"{optimized_metrics.max_queue_length_m:.1f} m",
                variance=max_q_var,
                is_improvement=max_q_imp,
            ),
            ScenarioMetricRow(
                metric="Average Travel Time",
                baseline=f"{baseline_metrics.avg_travel_time_s:.1f} s",
                optimized=f"{optimized_metrics.avg_travel_time_s:.1f} s",
                variance=tt_var,
                is_improvement=tt_imp,
            ),
            ScenarioMetricRow(
                metric="Network Throughput",
                baseline=f"{baseline_metrics.throughput_veh_hr:.0f} veh/h",
                optimized=f"{optimized_metrics.throughput_veh_hr:.0f} veh/h",
                variance=tp_var,
                is_improvement=tp_imp,
            ),
            ScenarioMetricRow(
                metric="Teleported Vehicles",
                baseline=f"{baseline_metrics.teleported_count} vehs",
                optimized=f"{optimized_metrics.teleported_count} vehs",
                variance="No gridlock" if (baseline_metrics.teleported_count == 0 and optimized_metrics.teleported_count == 0) else f"{optimized_metrics.teleported_count - baseline_metrics.teleported_count:+d} vehs",
                is_improvement=optimized_metrics.teleported_count <= baseline_metrics.teleported_count,
            ),
        ]

        # 8. Unfinished Trips (Lower is better)
        base_unfin = max(0, baseline_metrics.inserted_vehicles - baseline_metrics.completed_vehicles)
        opt_unfin = max(0, optimized_metrics.inserted_vehicles - optimized_metrics.completed_vehicles)
        unfin_pct, unfin_diff, unfin_var, unfin_imp = calc_metric_variance(
            float(opt_unfin), float(base_unfin), "vehs", higher_is_better=False, is_int=True
        )
        extended_rows.append(
            ScenarioMetricRow(
                metric="Unfinished Trips",
                baseline=f"{base_unfin} vehs",
                optimized=f"{opt_unfin} vehs",
                variance=unfin_var,
                is_improvement=unfin_imp,
            )
        )

        disclosures: list[str] = []
        if baseline_metrics.total_duration_seconds != optimized_metrics.total_duration_seconds:
            disclosures.append(
                f"Duration mismatch: baseline ({baseline_metrics.total_duration_seconds:.0f}s) vs optimized ({optimized_metrics.total_duration_seconds:.0f}s)."
            )
        if "fallback" in engine_mode:
            disclosures.append(
                "Internal kinematics engine estimation mode: values are simulated visual estimates, "
                "not empirical SUMO hardware measurements. Percentage variances must not be presented as empirical improvements."
            )

        disclosures_prefix = f"[{' | '.join(disclosures)}] " if disclosures else ""

        is_validated = False
        optimization_status = "unvalidated"
        comparison_status: ComparisonStatus = "completed"

        is_native = ("native" in engine_mode) and (baseline_engine_mode is None or "native" in baseline_engine_mode)

        if (applied_signals_count or 0) == 0 or signal_count == 0:
            is_validated = False
            optimization_status = "kinematics_estimate_only" if not is_native else "unsignalized_or_unoptimized"
            comparison_status = "completed"
        elif not is_native:
            is_validated = False
            optimization_status = "kinematics_estimate_only"
            comparison_status = "completed_inconclusive"
        else:
            # is_native and applied_signals_count > 0
            if optimizer_validation_passed is True:
                if wait_imp and (speed_imp or queue_imp):
                    is_validated = True
                    optimization_status = "validated_improvement"
                    comparison_status = "completed_validated"
                elif wait_imp or speed_imp or queue_imp:
                    is_validated = True
                    optimization_status = "validated_tradeoff"
                    comparison_status = "completed_validated"
                else:
                    is_validated = False
                    optimization_status = "validated_neutral_or_regression"
                    comparison_status = "completed_inconclusive"
            elif optimizer_validation_passed is False or optimizer_status in ("inconclusive", "failed", "all_evaluations_failed"):
                is_validated = False
                optimization_status = "optimization_inconclusive_baseline_preserved"
                comparison_status = "completed_inconclusive"
            else:
                is_validated = False
                optimization_status = "unvalidated"
                comparison_status = "completed_inconclusive"

        if signal_count == 0 or (applied_signals_count or 0) == 0:
            notes = (
                f"{disclosures_prefix}Empirical evaluation under {engine_mode} engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
                f"(seed 42, {step_count} simulation steps). "
                f"Network contains 0 traffic signal controllers. All junctions operate under standard priority right-of-way rules. "
                f"Actuated signal timing is not applicable to unsignalized intersections."
            )
        elif not is_native:
            notes = (
                f"{disclosures_prefix}Simulation completed under {engine_mode} internal kinematics engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
                f"(seed 42, {step_count} simulation steps). "
                f"Fallback kinematics outputs are visual estimations and cannot validate empirical signal control improvements."
            )
        elif optimizer_validation_passed is not True:
            notes = (
                f"{disclosures_prefix}Empirical evaluation under {engine_mode} engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
                f"(seed 42, {step_count} simulation steps). "
                f"Candidate signal timing optimization did not pass whole-network baseline validation; baseline signal timing was preserved. "
                f"Scenario comparison is not validated."
            )
        elif is_validated:
            notes = (
                f"{disclosures_prefix}Empirical evaluation under {engine_mode} engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
                f"(seed 42, {step_count} simulation steps). "
                f"Fixed-time signal optimization validated against baseline in native SUMO across {applied_signals_count} signal(s)."
            )
        else:
            notes = (
                f"{disclosures_prefix}Empirical evaluation under {engine_mode} engine over {optimized_metrics.elapsed_seconds:.1f}s elapsed "
                f"(seed 42, {step_count} simulation steps). "
                f"Baseline: Fixed-Time vs Optimized: Actuated Adaptive."
            )

        return ScenarioComparisonResult(
            sim_id=sim_id,
            analysis_id=analysis_id,
            duration_seconds=duration_seconds,
            engine_mode=engine_mode,
            comparison_status=comparison_status,
            baseline_strategy=baseline_strategy,
            optimized_strategy=optimized_strategy,
            baseline_metrics=baseline_metrics,
            optimized_metrics=optimized_metrics,
            rows=primary_rows,
            extended_rows=extended_rows,
            methodology_notes=notes,
            signal_count=signal_count,
            approved_signals_count=approved_signals_count,
            applied_signals_count=applied_signals_count,
            initial_vehicles_count=initial_vehicles_count,
            selected_fixed_time_plan=selected_fixed_time_plan,
            is_validated=is_validated,
            optimization_status=optimization_status,
        )

