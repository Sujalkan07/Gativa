"""
Evidence-based recommendation engine.

Converts bottleneck candidates, road segments, and traffic observations into ranked,
evidence-linked infrastructure recommendations organized into Traffic Optimization
and Physical Infrastructure Planning.

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
    RoadSegment,
    RecommendationCategory,
    InterventionType,
)

logger = logging.getLogger(__name__)


def _make_id() -> str:
    return str(uuid.uuid4())[:8]


def _get_segment_coords(s: RoadSegment) -> tuple[Optional[float], Optional[float]]:
    """Extract representative (lat, lng) midpoint from segment geometry."""
    if s.geometry and s.geometry.coordinates:
        coords = s.geometry.coordinates
        if coords:
            mid = coords[len(coords) // 2]
            # GeoJSON coordinates are [lng, lat]
            return float(mid[1]), float(mid[0])
    return None, None


def _get_segment_location_name(s: RoadSegment) -> str:
    """Generate human-readable location label for a segment."""
    if s.name and s.name.strip():
        return f"{s.name.strip()} ({s.road_type.capitalize()} Corridor)"
    return f"{s.road_type.capitalize()} Corridor (ID: {s.segment_id[:8]})"


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
    seg: Optional[RoadSegment] = None,
) -> tuple[InterventionType, str, str, RecommendationCategory]:
    """
    Choose intervention type, title, description, and category.
    Returns (intervention_type, title, description, category).
    """
    has_traffic = obs is not None and obs.congestion_level in ("severe", "moderate")
    is_structural = b.bottleneck_type in ("network_structural", "combined")

    # Check signal control if segment is available
    is_explicitly_unsignalized = (
        seg is not None
        and seg.u_control is not None
        and seg.u_control != "traffic_signal"
        and seg.v_control is not None
        and seg.v_control != "traffic_signal"
    )

    # Intersection with both structural and traffic evidence
    if has_traffic and is_structural:
        if is_explicitly_unsignalized:
            return (
                "signal_installation",
                "Traffic Signal Installation Warrant Investigation",
                "This intersection currently operates unsignalized while experiencing heavy traffic delay and high network centrality. "
                "A formal warrant analysis (MUTCD Warrant 1 / Warrant 3) and 12-hour turning movement counts are recommended to evaluate if traffic signal installation is justified.",
                "infrastructure_planning",
            )
        return (
            "signal_optimization",
            "Adaptive Signal Timing Investigation",
            "This intersection shows both high network centrality and observed traffic delay. "
            "An engineering assessment of signal phasing and cycle lengths is recommended. "
            "This is a structural observation — actual timing changes must be validated by "
            "traffic engineers with full intersection data.",
            "traffic_optimization",
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
            "traffic_optimization",
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
                "traffic_optimization",
            )
        return (
            "connectivity",
            "Alternative Route Investigation",
            "Moderate traffic delay observed. Improving parallel route capacity or "
            "connectivity may reduce demand concentration. "
            "Confirm with traffic counts before infrastructure investment.",
            "traffic_optimization",
        )

    # Low-evidence default
    return (
        "signal_optimization",
        "Network Node Assessment",
        "This node is structurally significant in the road network. "
        "Further traffic data collection is needed to determine whether "
        "infrastructure intervention is warranted.",
        "traffic_optimization",
    )


def _screen_infrastructure_candidates(
    segments: list[RoadSegment],
    bottlenecks: list[BottleneckCandidate],
    traffic_by_segment: dict[str, TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
    existing_recs: list[Recommendation],
) -> list[Recommendation]:
    """
    Screen road segments and bottlenecks for physical infrastructure feasibility candidates.
    Generates evidence-backed recommendations for:
    - Flyover feasibility
    - Underpass feasibility
    - Road divider / central median
    - Traffic signal installation (warrant study)
    - Junction redesign & geometric channelization
    - Dedicated turning lanes
    """
    infra_recs: list[Recommendation] = []
    seen_locations: set[tuple[int, int, str]] = set()

    for r in existing_recs:
        if r.lat is not None and r.lng is not None:
            seen_locations.add((round(r.lat * 1000), round(r.lng * 1000), r.intervention_type))

    def _is_duplicate(lat: Optional[float], lng: Optional[float], itype: str) -> bool:
        if lat is None or lng is None:
            return False
        key = (round(lat * 1000), round(lng * 1000), itype)
        if key in seen_locations:
            return True
        seen_locations.add(key)
        return False

    # 1. Flyover Feasibility Screening
    # Candidate criteria: Highway or major arterial corridor with severe observed delay (speed reduction >= 40%)
    flyover_candidates: list[tuple[float, RoadSegment, TrafficObservation]] = []
    for s in segments:
        is_major = s.road_type in ("highway", "arterial") or (
            s.osm_highway and s.osm_highway in ("motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link")
        )
        if not is_major:
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        if not obs:
            continue
        speed_drop = obs.speed_reduction_ratio or 0.0
        if speed_drop >= 0.38 or obs.congestion_level == "severe":
            flyover_candidates.append((speed_drop, s, obs))

    flyover_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in flyover_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "flyover"):
            continue
        loc_name = _get_segment_location_name(s)
        impact_score = min(9.4, round(7.2 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.48 else "medium"

        evidence = [
            f"Corridor Classification: {s.road_type.capitalize()} ({s.osm_highway or 'arterial trunk'})",
            f"Corridor Length: {s.length_m:.0f} m, Lanes: {s.lanes or 2} per carriageway",
        ]
        if obs.observed_speed_kmh is not None:
            evidence.append(
                f"Observed Speed: {obs.observed_speed_kmh:.0f} km/h (Free-flow: {obs.free_flow_speed_kmh or 50:.0f} km/h)"
            )
        if speed_drop > 0:
            evidence.append(f"Throughput Delay: {speed_drop * 100:.0f}% speed reduction below free-flow")
        evidence.append("High through-traffic volume conflicts with intersecting at-grade turning traffic")

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Grade-Separated Flyover Feasibility Study: {loc_name}",
                intervention_type="flyover",
                description=(
                    "Preliminary screening indicates high corridor traffic concentration and severe throughput degradation on this major arterial corridor. "
                    "An elevated grade separation (flyover) study is recommended to eliminate at-grade intersection delay and separate through-traffic from localized turning movements."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs.observed_speed_kmh else "low",
                uncertainty_notes=(
                    "Screening-level assessment based on network topology and traffic telemetry. "
                    "Requires comprehensive right-of-way (ROW) boundary survey (min 30m corridor), vertical clearance verification (min 5.5m), "
                    "geotechnical soil borehole testing for foundation load capacity, and 24-hour directional Turning Movement Counts (TMC) prior to detailed design."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    # 2. Underpass Feasibility Screening
    # Candidate criteria: Arterial corridor crossings where subterranean passage eliminates cross-corridor bottlenecks
    underpass_candidates: list[tuple[float, RoadSegment, TrafficObservation]] = []
    for s in segments:
        is_arterial = s.road_type in ("arterial", "collector") or (
            s.osm_highway and s.osm_highway in ("primary", "secondary")
        )
        if not is_arterial:
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        if not obs:
            continue
        speed_drop = obs.speed_reduction_ratio or 0.0
        if speed_drop >= 0.35 or obs.congestion_level in ("severe", "moderate"):
            underpass_candidates.append((speed_drop, s, obs))

    underpass_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in underpass_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "underpass"):
            continue
        loc_name = _get_segment_location_name(s)
        impact_score = min(8.8, round(6.8 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.45 else "medium"

        evidence = [
            f"Corridor Type: {s.road_type.capitalize()} ({s.osm_highway or 'urban arterial'})",
            f"Segment Length: {s.length_m:.0f} m",
        ]
        if speed_drop > 0:
            evidence.append(f"Observed Congestion: {speed_drop * 100:.0f}% speed reduction")
        evidence.append("Cross-corridor surface congestion warrants subterranean grade separation to preserve surface access")

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Subterranean Underpass Feasibility Investigation: {loc_name}",
                intervention_type="underpass",
                description=(
                    "High cross-corridor conflict and persistent intersection delay indicate candidate viability for an underpass. "
                    "Subsurface grade separation would allow continuous arterial flow while preserving surface-level turning movements and local pedestrian access."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs.observed_speed_kmh else "low",
                uncertainty_notes=(
                    "Screening-level recommendation. Detailed engineering requires subterranean utility conflict mapping (water mains, high-voltage electric, telecoms, gas), "
                    "hydrological and stormwater drainage catchment modeling (including dedicated sump pump design), and water table level investigation."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    # 3. Road Divider / Central Median Screening
    # Candidate criteria: Multi-lane undivided roads (lanes >= 3 or two-way arterial) prone to head-on and mid-block turning friction
    median_candidates: list[tuple[float, RoadSegment, Optional[TrafficObservation]]] = []
    for s in segments:
        if s.is_oneway:
            continue
        is_candidate_cross_section = (s.lanes and s.lanes >= 3) or (
            s.road_type in ("arterial", "highway") and not s.is_oneway
        )
        if not is_candidate_cross_section:
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        speed_drop = obs.speed_reduction_ratio if (obs and obs.speed_reduction_ratio is not None) else 0.0
        score = speed_drop * 10.0 + (s.lanes or 2)
        median_candidates.append((score, s, obs))

    median_candidates.sort(key=lambda item: item[0], reverse=True)
    for score, s, obs in median_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "road_median"):
            continue
        loc_name = _get_segment_location_name(s)
        speed_drop = obs.speed_reduction_ratio if (obs and obs.speed_reduction_ratio) else 0.0
        impact_score = min(8.2, round(6.2 + speed_drop * 3.0, 1))
        priority = "high" if ((s.lanes and s.lanes >= 4) or speed_drop >= 0.40) else "medium"

        evidence = [
            f"Undivided Two-Way Cross Section: {s.lanes or 2}+ lanes on {s.road_type.capitalize()}",
            f"Segment Length: {s.length_m:.0f} m",
        ]
        if s.speed_limit_kmh:
            evidence.append(f"Operating Speed Limit: {s.speed_limit_kmh:.0f} km/h")
        if speed_drop > 0:
            evidence.append(f"Flow Disruption: {speed_drop * 100:.0f}% speed reduction from mid-block turning friction")
        evidence.append("Lack of physical median allows uncontrolled mid-block turns and opposing flow friction")

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Raised Central Median & Access Management Assessment: {loc_name}",
                intervention_type="road_median",
                description=(
                    "This multi-lane two-way corridor operates without physical median division, exposing vehicles to mid-block turning friction, head-on conflict risks, and unprotected pedestrian crossings. "
                    "Installation of a raised concrete median barrier with channelized U-turn cuts and pedestrian refuge islands is recommended."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs else "low",
                uncertainty_notes=(
                    "Screening-level assessment. Requires physical carriageway width measurement to verify remaining lane widths (min 3.5m per lane) after 1.2m-1.8m median installation, "
                    "access management review of commercial driveways, and emergency vehicle turnaround frequency."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    # 4. Traffic Signal Installation Screening (Warrant Assessment)
    # Candidate criteria: Unsignalized intersections carrying heavy traffic with substantial observed delay
    signal_candidates: list[tuple[float, RoadSegment, TrafficObservation]] = []
    for s in segments:
        is_unsignalized = (
            (s.u_control is not None and s.u_control != "traffic_signal" and s.v_control is not None and s.v_control != "traffic_signal")
            or (s.u_control in ("stop", "yield", "priority", "uncontrolled") or s.v_control in ("stop", "yield", "priority", "uncontrolled"))
        )
        if not is_unsignalized:
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        if not obs:
            continue
        speed_drop = obs.speed_reduction_ratio or 0.0
        if speed_drop >= 0.32 or obs.congestion_level in ("severe", "moderate"):
            signal_candidates.append((speed_drop, s, obs))

    signal_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in signal_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "signal_installation"):
            continue
        loc_name = _get_segment_location_name(s)
        impact_score = min(8.0, round(5.8 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.45 else "medium"

        evidence = [
            f"Unsignalized Control Configuration: {s.u_control or 'priority'} / {s.v_control or 'priority'}",
            f"Observed Congestion: {speed_drop * 100:.0f}% speed reduction on junction approach",
            "Multi-leg intersection approach delay indicates candidate viability for signalization warrants",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Traffic Signal Installation Warrant Investigation: {loc_name}",
                intervention_type="signal_installation",
                description=(
                    "This unsignalized multi-leg junction carries heavy approach traffic with substantial observed delay and conflict points. "
                    "A formal warrant analysis is recommended to evaluate whether installing a new multi-phase traffic signal is justified."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs.observed_speed_kmh else "low",
                uncertainty_notes=(
                    "A traffic signal cannot be installed based solely on network delay. A comprehensive 12-hour or 24-hour Turning Movement Count (TMC) "
                    "and MUTCD / IRC Warrant analysis (Warrant 1: Eight-Hour Volume, Warrant 2: Four-Hour Volume, Warrant 3: Peak Hour Volume) are mandatory. "
                    "Sight distance triangles and controller cabinet power availability must also be verified."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    # 5. Junction Redesign & Geometric Channelization
    # Candidate criteria: Bottlenecks with high centrality or intersections with complex approach angles
    redesign_candidates: list[BottleneckCandidate] = [
        b for b in bottlenecks if (b.centrality_score and b.centrality_score >= 0.05) or b.severity in ("high", "medium")
    ]
    redesign_candidates.sort(key=lambda b: (b.centrality_score or 0.0), reverse=True)
    for b in redesign_candidates[:2]:
        if _is_duplicate(b.lat, b.lng, "junction_redesign"):
            continue
        loc_name = b.location_name or "Complex Intersection Node"
        centrality = b.centrality_score or 0.05
        impact_score = min(7.8, round(5.5 + centrality * 12.0, 1))
        priority = "high" if b.severity == "high" else "medium"

        evidence = [
            f"Network Centrality Score: {centrality:.3f}",
            f"Structural Bottleneck Severity: {b.severity.capitalize()}",
            "Complex converging traffic paths cause vehicle conflict points and approach queuing",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Intersection Geometric Redesign & Channelization: {loc_name}",
                intervention_type="junction_redesign",
                description=(
                    "High structural centrality and intersecting traffic paths cause friction at this intersection. "
                    "A geometric realignment is recommended, incorporating channelized turn islands, curb radius expansion, and pedestrian curb ramps."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[b.segment_id],
                lat=b.lat,
                lng=b.lng,
                supporting_evidence=evidence,
                confidence="medium",
                uncertainty_notes=(
                    "Screening-level assessment. Requires CAD-based swept path analysis (AutoTURN) for design vehicles (buses and WB-15 freight trucks), "
                    "corner property line verification, and pedestrian curb ramp ADA/universal accessibility compliance."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    # 6. Dedicated Turning Lane Assessment
    # Candidate criteria: Multi-lane arterials approaching intersections where queue spillback blocks through traffic
    turn_candidates: list[tuple[float, RoadSegment, TrafficObservation]] = []
    for s in segments:
        is_candidate_road = s.road_type in ("arterial", "collector", "highway")
        has_multi_lanes = (s.lanes is not None and s.lanes >= 2) or s.road_type == "arterial"
        if not (is_candidate_road and has_multi_lanes):
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        if not obs:
            continue
        speed_drop = obs.speed_reduction_ratio or 0.0
        if speed_drop >= 0.25 or obs.congestion_level in ("severe", "moderate"):
            turn_candidates.append((speed_drop, s, obs))

    turn_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in turn_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "dedicated_turning_lane"):
            continue
        loc_name = _get_segment_location_name(s)
        impact_score = min(7.5, round(5.2 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.40 else "medium"

        evidence = [
            f"Corridor Profile: {s.lanes or 2}-lane {s.road_type.capitalize()} approach",
            f"Throughput Delay: {speed_drop * 100:.0f}% speed reduction from junction queue buildup",
            "Shared through-and-turn lane friction causes queue spillback into through lanes",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Dedicated Auxiliary Turn Lane Feasibility Study: {loc_name}",
                intervention_type="dedicated_turning_lane",
                description=(
                    "Observed queue spillback and delay at junction approaches suggest through-lane capacity is compromised by turning vehicles. "
                    "Installing an exclusive turning pocket (left-turn or right-turn bay) with adequate deceleration and storage length is recommended."
                ),
                priority=priority,
                impact_score=impact_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs.observed_speed_kmh else "low",
                uncertainty_notes=(
                    "Screening-level recommendation. Detailed engineering requires peak 15-minute turning movement counts to calculate required storage length (AASHTO / IRC standard), "
                    "approach taper length analysis, and verification that right-of-way or carriageway width permits bay construction."
                ),
                requires_engineering_review=True,
                priority_score=impact_score,
            )
        )

    return infra_recs


def generate_recommendations(
    analysis_id: str,
    bottlenecks: list[BottleneckCandidate],
    traffic_by_segment: dict[str, TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
    weather: Optional[WeatherContext],
    segments: Optional[list[RoadSegment]] = None,
) -> RecommendationsResult:
    """
    Generate evidence-backed recommendations organized into:
    - Traffic Optimization (operational management, signal timing, lane regulation)
    - Infrastructure Planning (flyovers, underpasses, medians, new signals, geometric redesign)

    Args:
        analysis_id: The analysis ID.
        bottlenecks: Detected bottleneck candidates.
        traffic_by_segment: Map of segment_id -> traffic observation.
        metrics: Road network metrics.
        weather: Weather context (supplementary).
        segments: Optional list of road segments for geometry and physical screening.

    Returns:
        Structured recommendations result.
    """
    recommendations: list[Recommendation] = []
    optimization_notes: list[str] = [
        "Methodology: Multi-criteria heuristic ranking balancing network betweenness centrality, "
        "observed relative speed reduction, active incidents, and functional road classification. "
        "Organized into Traffic Optimization (operational interventions) and Infrastructure Planning (physical civil candidates). "
        "Provides screening-level prioritization. Engineering feasibility studies and micro-simulation "
        "are required before capital allocation."
    ]
    warnings: list[str] = []

    segments_by_id: dict[str, RoadSegment] = {s.segment_id: s for s in segments} if segments else {}

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

    # Process each bottleneck for Traffic Optimization & initial interventions
    for b in bottlenecks:
        # Find best traffic observation for this bottleneck (by segment proximity)
        obs = traffic_by_segment.get(b.segment_id)
        seg = segments_by_id.get(b.segment_id)

        impact_score, priority = _score_bottleneck(b, obs)
        intervention_type, title, description, category = _choose_intervention(b, obs, metrics, seg)

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
            category=category,
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

    # Screen physical infrastructure candidates if segments are available
    if segments:
        infra_candidates = _screen_infrastructure_candidates(
            segments=segments,
            bottlenecks=bottlenecks,
            traffic_by_segment=traffic_by_segment,
            metrics=metrics,
            existing_recs=recommendations,
        )
        recommendations.extend(infra_candidates)

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
