"""
Evidence-based recommendation engine.

Converts bottleneck candidates and traffic observations into ranked,
evidence-linked infrastructure recommendations.

IMPORTANT: All recommendations include:
- The evidence that supports them
- Explicit uncertainty notes
- Engineering review requirement
- Priority scores (not guaranteed impact percentages)
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.schemas import (
    BottleneckCandidate,
    TrafficObservation,
    RoadNetworkMetrics,
    Recommendation,
    RecommendationsResult,
    WeatherContext,
)

logger = logging.getLogger(__name__)


def _make_id() -> str:
    return str(uuid.uuid4())[:8]


def _score_bottleneck(
    b: BottleneckCandidate,
    obs: Optional[TrafficObservation],
) -> tuple[float, str]:
    """
    Score a bottleneck candidate for priority.
    Returns (0-10 impact score, priority level).
    """
    base = 0.0

    # Centrality contribution
    if b.centrality_score is not None:
        base += b.centrality_score * 4.0  # max 4 pts

    # Traffic observation contribution
    if obs is not None:
        if obs.speed_reduction_ratio is not None:
            base += min(obs.speed_reduction_ratio * 4.0, 4.0)
        if obs.congestion_level in ("severe",):
            base += 2.0
        elif obs.congestion_level == "moderate":
            base += 1.0
        if obs.has_incident:
            base += 1.0

    # Severity modifier
    if b.severity == "high":
        base *= 1.0
    elif b.severity == "medium":
        base *= 0.7
    else:
        base *= 0.5

    score = min(round(base, 1), 10.0)

    if score >= 7.0:
        priority = "high"
    elif score >= 4.0:
        priority = "medium"
    else:
        priority = "low"

    return score, priority


def _choose_intervention(
    b: BottleneckCandidate,
    obs: Optional[TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
) -> tuple[str, str, str]:
    """
    Choose intervention type, title, and description.
    Returns (intervention_type, title, description).
    """
    has_traffic = obs is not None and obs.congestion_level in ("severe", "moderate")
    is_structural = b.bottleneck_type in ("network_structural", "combined")

    # Intersection with both structural and traffic evidence
    if has_traffic and is_structural:
        return (
            "signal_optimization",
            "Adaptive Signal Timing Investigation",
            "This intersection shows both high network centrality and observed traffic delay. "
            "An engineering assessment of signal phasing and cycle lengths is recommended. "
            "This is a structural observation — actual timing changes must be validated by "
            "traffic engineers with full intersection data.",
        )

    # Structural bottleneck at high-degree intersection
    if is_structural and b.centrality_score and b.centrality_score > 0.1:
        return (
            "geometry_improvement",
            "Intersection Geometry Review",
            "This intersection carries a disproportionate share of network traffic paths "
            "(high betweenness centrality). A geometric review for dedicated turn lanes, "
            "channelization, or junction redesign is warranted. "
            "Road network structure alone does not confirm congestion at this location.",
        )

    # Traffic-only (observed congestion, no network structural evidence)
    if has_traffic:
        if obs and obs.speed_reduction_ratio and obs.speed_reduction_ratio > 0.5:
            return (
                "road_widening",
                "Capacity Expansion Assessment",
                "Significant speed reduction observed on this road segment. "
                "A traffic demand study is recommended to evaluate whether additional "
                "lane capacity, bus lanes, or parallel route improvements could reduce delay. "
                "Speed observations from TomTom represent a snapshot; patterns should be "
                "confirmed with historical data before committing to capital works.",
            )
        return (
            "connectivity",
            "Alternative Route Investigation",
            "Moderate traffic delay observed. Improving parallel route capacity or "
            "connectivity may reduce demand concentration. "
            "Confirm with traffic counts before infrastructure investment.",
        )

    # Low-evidence default
    return (
        "signal_optimization",
        "Network Node Assessment",
        "This node is structurally significant in the road network. "
        "Further traffic data collection is needed to determine whether "
        "infrastructure intervention is warranted.",
    )


def generate_recommendations(
    analysis_id: str,
    bottlenecks: list[BottleneckCandidate],
    traffic_by_segment: dict[str, TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
    weather: Optional[WeatherContext],
) -> RecommendationsResult:
    """
    Generate evidence-backed infrastructure recommendations from analysis results.

    Args:
        analysis_id: The analysis ID.
        bottlenecks: Detected bottleneck candidates.
        traffic_by_segment: Map of segment_id → traffic observation.
        metrics: Road network metrics.
        weather: Weather context (supplementary).

    Returns:
        Structured recommendations result.
    """
    recommendations: list[Recommendation] = []
    optimization_notes: list[str] = [
        "Methodology: Multi-criteria heuristic ranking balancing network betweenness centrality, "
        "observed relative speed reduction, active incidents, and functional road classification. "
        "Provides screening-level prioritization. Engineering feasibility studies and micro-simulation "
        "are required before capital allocation."
    ]
    warnings: list[str] = []

    if not bottlenecks:
        optimization_notes.append(
            "No significant bottleneck candidates were detected in the selected area. "
            "The road network appears to have no structurally critical nodes above the detection threshold."
        )
        if not traffic_by_segment:
            warnings.append(
                "No traffic observations were available for this area. "
                "Bottleneck detection relied solely on road network structure."
            )

    # Weather context note
    if weather and weather.precipitation_mm and weather.precipitation_mm > 2:
        optimization_notes.append(
            f"Current precipitation ({weather.precipitation_mm} mm/h) may be affecting traffic speeds. "
            "Recommendations based on current conditions may not reflect typical traffic patterns."
        )

    # Process each bottleneck
    for b in bottlenecks:
        # Find best traffic observation for this bottleneck (by segment proximity)
        obs = traffic_by_segment.get(b.segment_id)

        impact_score, priority = _score_bottleneck(b, obs)
        intervention_type, title, description = _choose_intervention(b, obs, metrics)

        # Build evidence list
        evidence = list(b.evidence)
        if obs:
            if obs.observed_speed_kmh is not None:
                evidence.append(
                    f"Observed speed: {obs.observed_speed_kmh:.0f} km/h"
                    + (f" (free-flow: {obs.free_flow_speed_kmh:.0f} km/h)" if obs.free_flow_speed_kmh else "")
                )
            if obs.speed_reduction_ratio is not None:
                evidence.append(f"Speed reduction: {obs.speed_reduction_ratio * 100:.0f}% below free-flow")
            if obs.has_incident:
                evidence.append("Active incident reported by TomTom at or near this location")
        else:
            evidence.append("No traffic observation data available for this location from TomTom")

        # Confidence
        if obs and b.centrality_score and b.centrality_score > 0.05:
            confidence = "medium"  # Both structural + traffic
        elif obs and obs.congestion_level in ("severe",):
            confidence = "medium"
        else:
            confidence = "low"  # Structural only

        uncertainty = (
            "This recommendation is based on road network structure analysis"
            + (" and a single TomTom traffic observation" if obs else " only")
            + ". A sustained observation period and on-site traffic survey are required "
            "before committing to any infrastructure investment."
        )

        rec = Recommendation(
            recommendation_id=_make_id(),
            title=title,
            intervention_type=intervention_type,
            description=description,
            priority=priority,
            impact_score=impact_score,
            affected_location=b.location_name,
            affected_segment_ids=[b.segment_id],
            lat=b.lat,
            lng=b.lng,
            supporting_evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty,
            requires_engineering_review=True,
            priority_score=impact_score,
        )
        recommendations.append(rec)

    # Sort by priority score descending
    recommendations.sort(key=lambda r: r.priority_score, reverse=True)

    # Add general notes
    if metrics:
        if metrics.road_density_km_per_km2 < 5:
            optimization_notes.append(
                f"Road density is low ({metrics.road_density_km_per_km2:.1f} km/km²). "
                "Improved road connectivity could distribute traffic more evenly."
            )
        if metrics.highway_count == 0:
            optimization_notes.append(
                "No highways or expressways detected in the selected area. "
                "The area relies entirely on arterial and local roads."
            )

    if not traffic_by_segment:
        warnings.append(
            "Traffic observations from TomTom were unavailable for this analysis. "
            "All recommendations are based on road network structure only and carry low confidence. "
            "Configure TOMTOM_API_KEY in backend/.env and re-run the analysis for traffic-informed recommendations."
        )

    return RecommendationsResult(
        analysis_id=analysis_id,
        recommendations=recommendations,
        optimization_notes=optimization_notes,
        data_quality_warnings=warnings,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
