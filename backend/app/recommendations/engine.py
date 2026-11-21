"""
Evidence-based recommendation engine.

Converts bottleneck candidates, road segments, and traffic observations into ranked,
evidence-linked infrastructure recommendations organized into Traffic Optimization
and Physical Infrastructure Planning.

IMPORTANT: All recommendations include:
- The evidence that supports them (telemetry, road topology, OSM ground truth)
- Congestion cause diagnosis (incident, closure, junction, structural, unverified)
- Transparent priority screening score breakdown (not guaranteed improvement percentages)
- Explicit missing data and unverified assumptions
- Mandatory engineering validation requirements (MUTCD/IRC warrants, surveys, geotechnical)
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
    CongestionCause,
    TrafficIncident,
    ConfidenceLevel,
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


def _diagnose_congestion_cause(
    obs: Optional[TrafficObservation],
    b: Optional[BottleneckCandidate],
    seg: Optional[RoadSegment] = None,
    seg_incidents: Optional[list[TrafficIncident]] = None,
    historical_snapshots_count: int = 1,
) -> tuple[CongestionCause, str]:
    """
    Diagnose the probable cause of congestion based on available telemetry and topology.
    Returns (cause, explanation).
    
    Causes:
    - road_closure: Physical blockage / closure reported
    - incident_related: Active accident, road work, or hazard
    - junction_approach: Congestion concentrated at intersection conflict / signal approach
    - recurring_corridor: Confirmed across multiple time intervals (never on a single snapshot)
    - structural_connectivity: Topological bottleneck without active incident
    - insufficient_evidence: Telemetry missing, low confidence, or speeds near free-flow
    """
    has_incidents = (
        (obs is not None and obs.has_incident)
        or (seg_incidents is not None and len(seg_incidents) > 0)
    )
    is_closed = (
        obs is not None
        and (obs.road_closure or obs.congestion_level == "closed")
    )

    # 1. Road Closure
    if is_closed:
        return (
            "road_closure",
            "Physical road closure or complete corridor blockage reported by traffic feed.",
        )

    # 2. Incident-Related Congestion
    if has_incidents:
        inc_desc = (
            seg_incidents[0].type
            if seg_incidents and seg_incidents[0].type
            else "Active incident"
        )
        return (
            "incident_related",
            f"Active incident ({inc_desc}) reported on or immediately adjacent to this corridor.",
        )

    # 3. Junction / Approach Congestion
    is_junction_segment = (
        seg is not None
        and (
            seg.u_control is not None
            or seg.v_control is not None
            or seg.osm_highway in ("traffic_signals", "mini_roundabout")
        )
    )
    is_junction_bottleneck = (
        b is not None
        and b.centrality_score is not None
        and b.centrality_score >= 0.05
    )
    has_traffic_delay = (
        obs is not None
        and (
            (obs.speed_reduction_ratio is not None and obs.speed_reduction_ratio >= 0.25)
            or (obs.delay_seconds is not None and obs.delay_seconds >= 15.0)
            or obs.congestion_level in ("severe", "moderate")
        )
    )

    if (is_junction_segment or is_junction_bottleneck) and has_traffic_delay:
        return (
            "junction_approach",
            "Delay is concentrated at an intersection approach or multi-leg junction conflict point.",
        )

    # 4. Recurring Corridor Congestion (STRICT: Only when multiple historical snapshots exist)
    if historical_snapshots_count > 1 and has_traffic_delay:
        return (
            "recurring_corridor",
            f"Sustained throughput degradation confirmed across {historical_snapshots_count} independent observation periods.",
        )

    # 5. Structural Connectivity Issue
    if b is not None and b.bottleneck_type in ("network_structural", "combined"):
        if b.centrality_score and b.centrality_score >= 0.08:
            return (
                "structural_connectivity",
                "High network betweenness centrality with limited alternative parallel corridors.",
            )

    # 6. Insufficient Evidence Default
    if obs is None:
        return (
            "insufficient_evidence",
            "No live traffic telemetry available; diagnosis is based solely on road network topology.",
        )

    if obs.confidence is not None and obs.confidence < 0.5:
        return (
            "insufficient_evidence",
            "TomTom observation confidence is low (< 50%) or telemetry is unverified.",
        )

    if obs.congestion_level in ("free_flow", "unknown") and (obs.speed_reduction_ratio or 0) < 0.20:
        return (
            "insufficient_evidence",
            "Traffic conditions operate near free-flow; no significant operational defect detected.",
        )

    return (
        "insufficient_evidence",
        "Single-snapshot speed reduction observed; recurrence and specific root cause require field verification.",
    )


def _score_bottleneck(
    b: BottleneckCandidate,
    obs: Optional[TrafficObservation],
    seg: Optional[RoadSegment] = None,
    seg_incidents: Optional[list[TrafficIncident]] = None,
) -> tuple[float, str, dict[str, float]]:
    """
    Score a recommendation candidate for screening priority.
    Returns (priority_score: 0-10, priority_level: high/medium/low, breakdown_dict).
    
    This is an engineering screening / priority score, NOT a measured percentage improvement.
    """
    # 1. Congestion Factor (max 3.0 pts)
    congestion_factor = 0.0
    if obs is not None:
        if obs.road_closure or obs.congestion_level == "closed":
            congestion_factor = 3.0
        elif obs.speed_reduction_ratio is not None:
            congestion_factor += min(obs.speed_reduction_ratio * 3.0, 2.5)
            if obs.congestion_level == "severe":
                congestion_factor += 0.5
            elif obs.congestion_level == "moderate":
                congestion_factor += 0.25
    congestion_factor = min(congestion_factor, 3.0)

    # 2. Travel-Time Delay Factor (max 2.0 pts)
    delay_factor = 0.0
    if obs is not None:
        if obs.road_closure or obs.congestion_level == "closed":
            delay_factor = 2.0
        elif obs.delay_seconds is not None and obs.delay_seconds > 0:
            delay_factor = min((obs.delay_seconds / 60.0) * 1.0, 2.0)

    # 3. Road Importance Factor (max 2.5 pts)
    road_importance = 0.5  # default baseline
    road_type = seg.road_type if seg else "local"
    if road_type == "highway":
        road_importance = 1.8
    elif road_type == "arterial":
        road_importance = 1.3
    elif road_type in ("collector", "secondary"):
        road_importance = 0.9

    if b.centrality_score is not None:
        road_importance += min(b.centrality_score * 8.0, 0.7)
    road_importance = min(road_importance, 2.5)

    # 4. Data Quality Factor (max 1.5 pts)
    data_quality = 0.5  # baseline
    if obs is not None:
        if obs.confidence is not None:
            data_quality = obs.confidence * 1.0
        if obs.match_quality == "high":
            data_quality += 0.5
        elif obs.match_quality == "medium":
            data_quality += 0.3
        elif obs.match_quality in ("low", "unmatched"):
            data_quality -= 0.2
        if obs.is_stale:
            data_quality -= 0.3
    data_quality = max(0.0, min(data_quality, 1.5))

    # 5. Incident Factor (max 1.0 pt)
    incident_factor = 0.0
    if (obs and obs.has_incident) or (seg_incidents and len(seg_incidents) > 0):
        incident_factor = 1.0

    raw_total = congestion_factor + delay_factor + road_importance + data_quality + incident_factor

    # Structural severity modifier
    if b.severity == "high":
        raw_total *= 1.0
    elif b.severity == "medium":
        raw_total *= 0.8
    else:
        raw_total *= 0.6

    score = min(round(raw_total, 1), 10.0)

    if score >= 7.0:
        priority = "high"
    elif score >= 4.0:
        priority = "medium"
    else:
        priority = "low"

    breakdown = {
        "congestion_factor": round(congestion_factor, 1),
        "delay_factor": round(delay_factor, 1),
        "road_importance": round(road_importance, 1),
        "data_quality": round(data_quality, 1),
        "incident_modifier": round(incident_factor, 1),
    }

    return score, priority, breakdown


def _calculate_confidence(
    obs: Optional[TrafficObservation],
    cause: CongestionCause,
    seg: Optional[RoadSegment] = None,
) -> ConfidenceLevel:
    """
    Calculate evidence confidence independently of problem severity.
    A severe problem can have LOW confidence if data is incomplete.
    """
    if obs is None:
        return "low"

    # Severe data defects force low confidence
    if obs.is_stale or obs.match_quality in ("low", "unmatched"):
        return "low"

    if obs.confidence is not None and obs.confidence < 0.6:
        return "low"

    if cause == "insufficient_evidence":
        return "low"

    # High confidence requires strong telemetry, known match, and complete OSM attributes
    has_high_telemetry = (obs.confidence is not None and obs.confidence >= 0.8) and (
        obs.match_quality in ("high", None)
    )
    has_complete_osm = (
        seg is not None
        and seg.road_type in ("highway", "arterial")
        and (seg.lanes is not None or seg.speed_limit_kmh is not None)
    )

    if has_high_telemetry and has_complete_osm:
        return "high"

    return "medium"


def _choose_intervention(
    b: BottleneckCandidate,
    obs: Optional[TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
    seg: Optional[RoadSegment] = None,
    cause: Optional[CongestionCause] = None,
    seg_incidents: Optional[list[TrafficIncident]] = None,
) -> tuple[InterventionType, str, str, RecommendationCategory]:
    """
    Choose intervention type, title, description, and category based on diagnosed cause and evidence.
    Returns:
        (intervention_type, title, description, category)
    """
    if cause is None:
        cause, _ = _diagnose_congestion_cause(obs, b, seg, seg_incidents)
    # 1. Road Closure
    if cause == "road_closure":
        return (
            "signal_optimization",
            "Temporary Traffic Diversion & Route Guidance Assessment",
            "A physical road closure or complete blockage was reported on this corridor. "
            "Prioritize temporary variable-message detour signage and adjust signal cycle splits "
            "on adjacent parallel corridors to manage diverted traffic volume rather than initiating permanent civil modifications.",
            "traffic_optimization",
        )

    # 2. Incident-Related Congestion
    if cause == "incident_related":
        inc_type = seg_incidents[0].type if seg_incidents and seg_incidents[0].type else "Traffic Incident"
        return (
            "signal_optimization",
            f"Incident Traffic Management & Clearance Monitoring: {inc_type}",
            f"Active incident ({inc_type}) is the primary source of observed delay on this corridor. "
            "Immediate operational response should focus on queue protection, incident clearance, and localized signal adjustments. "
            "Permanent infrastructure modifications (such as road widening or flyovers) must not be initiated for temporary incident congestion.",
            "traffic_optimization",
        )

    # 3. Junction / Approach-Related Congestion
    if cause == "junction_approach":
        is_explicitly_unsignalized = (
            seg is not None
            and seg.u_control is not None
            and seg.u_control != "traffic_signal"
            and seg.v_control is not None
            and seg.v_control != "traffic_signal"
        )
        if is_explicitly_unsignalized:
            return (
                "signal_installation",
                "Traffic Signal Installation Warrant Investigation",
                "This intersection currently operates unsignalized while experiencing heavy traffic delay and high network centrality. "
                "A formal warrant analysis (MUTCD Warrant 1 / Warrant 3) and 12-hour turning movement counts are recommended to evaluate if traffic signal installation is justified. "
                "A signal cannot be installed based solely on speed snapshots without volume warrant satisfaction.",
                "infrastructure_planning",
            )
        return (
            "signal_optimization",
            "Adaptive Signal Phasing & Cycle Length Optimization",
            "This signalized intersection demonstrates high approach delay and strategic network importance. "
            "An engineering assessment of signal phasing, green splits, and cycle lengths is recommended. "
            "Actual timing modifications must be validated by field observations and intersection queue measurements.",
            "traffic_optimization",
        )

    # 4. Structural Connectivity
    if cause == "structural_connectivity":
        return (
            "geometry_improvement",
            "Intersection Geometry & Channelization Review",
            "This node carries a high proportion of network paths (high betweenness centrality). "
            "A geometric review for channelized turning islands, lane alignment, and pedestrian refuge is recommended. "
            "High centrality reflects network routing importance, not necessarily an inherent geometric defect.",
            "traffic_optimization",
        )

    # 5. Default / Insufficient Evidence
    return (
        "signal_optimization",
        "Corridor Telemetry Verification & Baseline Survey",
        "Traffic telemetry is limited or inconclusive for this location. "
        "A field data collection survey (automated volume counts and turning movement counts) is recommended "
        "to establish a verified baseline before considering infrastructure capital interventions.",
        "traffic_optimization",
    )


def _get_intervention_specification(
    intervention_type: InterventionType,
    cause: CongestionCause,
    b: BottleneckCandidate,
    seg: Optional[RoadSegment] = None,
    obs: Optional[TrafficObservation] = None,
) -> tuple[list[str], list[str], str]:
    """
    Generate missing evidence, engineering validation checklist, and rationale for an intervention.
    Returns:
        (missing_evidence, engineering_validation, rationale)
    """
    if cause == "road_closure":
        return (
            [
                "Expected road closure duration from municipal authorities",
                "Available spare capacity on designated parallel relief corridors",
                "Emergency response vehicle access routing",
            ],
            [
                "Temporary Traffic Control Plan (TTCP) compliant with IRC:SP:55 / MUTCD Part 6",
                "Real-time signal offset adjustments on alternate arterial routes",
            ],
            "Physical closures require immediate operational traffic management and diversion rather than structural construction.",
        )

    if cause == "incident_related":
        return (
            [
                "Incident clearance verification timestamp",
                "Queue dissipation tracking post-incident resolution",
                "Secondary incident occurrence risk data",
            ],
            [
                "Incident management protocol deployment with traffic police",
                "Post-clearance corridor travel-time verification before secondary intervention evaluation",
            ],
            "Observed speed reduction is temporary and incident-driven; capital infrastructure changes are technically unjustified.",
        )

    if intervention_type == "signal_installation":
        return (
            [
                "12-hour or 24-hour directional Turning Movement Counts (TMC)",
                "Peak hour volume warrants satisfaction (MUTCD Warrant 1 / Warrant 3 / IRC:93)",
                "Pedestrian crossing volume and gap acceptance survey",
                "3-year collision history diagram",
            ],
            [
                "Formal MUTCD / IRC Warrant Assessment by a licensed traffic engineer",
                "Intersection sight distance triangle verification (AASHTO / IRC:66)",
                "Power supply and traffic controller cabinet siting survey",
            ],
            "Unsignalized junctions with approach delay warrant formal signalization investigation, subject to strict volume warrants.",
        )

    if intervention_type == "signal_optimization":
        return (
            [
                "Existing controller signal timing sheet (phase splits, cycle length, offsets)",
                "Queue lengths per lane approach at end of green phase",
                "Turn pocket storage occupancy",
            ],
            [
                "Field delay survey and split adjustment evaluation using microscopic traffic simulation",
                "Actuation loop / camera detector health check",
            ],
            "Approach delay at controlled junctions is most effectively addressed through timing optimization before civil modification.",
        )

    if intervention_type == "geometry_improvement":
        return (
            [
                "Accurate intersection curb-to-curb topographic survey",
                "AutoTURN swept-path analysis for design vehicles (WB-15 trucks and city buses)",
                "Turning movement counts per approach leg",
            ],
            [
                "Channelization design conforming to IRC:65 standards",
                "Corner curb radius and pedestrian crosswalk visibility inspection",
            ],
            "Network betweenness centrality indicates structural importance; channelization reduces vehicle conflict angles.",
        )

    return (
        [
            "Continuous 7-day traffic speed and volume profiles",
            "Vehicle classification distribution (two-wheelers, cars, heavy commercial vehicles)",
            "Accident and obstruction history records",
        ],
        [
            "Field reconnaissance and automated pneumatic tube or camera traffic count survey",
        ],
        "Available evidence is insufficient to justify capital civil interventions.",
    )


def _screen_infrastructure_candidates(
    segments: list[RoadSegment],
    bottlenecks: list[BottleneckCandidate],
    traffic_by_segment: dict[str, TrafficObservation],
    metrics: Optional[RoadNetworkMetrics],
    existing_recs: list[Recommendation],
    incidents_by_segment: dict[str, list[TrafficIncident]],
) -> list[Recommendation]:
    """
    Screen road segments for physical infrastructure feasibility candidates with strict evidence gates.
    Generates evidence-backed recommendations for:
    - Flyover feasibility study (strictly gated against temporary incidents/closures)
    - Underpass feasibility investigation (strictly gated against temporary incidents/closures)
    - Road divider / central median assessment
    - Traffic signal installation (warrant study)
    - Junction redesign & geometric channelization
    - Dedicated turning lane assessment
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
    # Candidate criteria: Major highway/arterial trunk with sustained severe delay NOT caused by an accident or closure
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

        # STRICT EVIDENCE GATE: Do not recommend flyover for incidents or road closures
        is_closed = obs.road_closure or obs.congestion_level == "closed"
        has_incident = obs.has_incident or len(incidents_by_segment.get(s.segment_id, [])) > 0
        if is_closed or has_incident:
            continue

        speed_drop = obs.speed_reduction_ratio or 0.0
        delay_sec = obs.delay_seconds or 0.0

        if speed_drop >= 0.45 or delay_sec >= 45.0 or obs.congestion_level == "severe":
            flyover_candidates.append((speed_drop, s, obs))

    flyover_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in flyover_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "flyover"):
            continue
        loc_name = _get_segment_location_name(s)
        priority_score = min(9.2, round(7.0 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.50 else "medium"

        evidence = [
            f"Corridor Classification: {s.road_type.capitalize()} ({s.osm_highway or 'arterial trunk'})",
            f"Corridor Length: {s.length_m:.0f} m, Lanes: {s.lanes or 'unrecorded'} per carriageway",
        ]
        if obs.observed_speed_kmh is not None:
            evidence.append(
                f"Observed Speed: {obs.observed_speed_kmh:.0f} km/h (Free-flow: {obs.free_flow_speed_kmh or 50:.0f} km/h)"
            )
        if speed_drop > 0:
            evidence.append(f"Throughput Delay: {speed_drop * 100:.0f}% speed reduction below free-flow")
        if obs.delay_seconds is not None and obs.delay_seconds > 0:
            evidence.append(f"Measured Delay: +{obs.delay_seconds:.0f} seconds over free-flow travel time")
        evidence.append("High through-traffic volume conflicts with intersecting at-grade turning traffic")

        missing_evidence = [
            "24-hour directional Turning Movement Counts (TMC) and classified volume counts",
            "Peak hour volume warrant satisfaction (IRC:SP:90 / AASHTO Grade Separation Guidelines)",
            "Right-of-Way (ROW) boundary survey confirming minimum 30m corridor width",
            "Subsurface utility conflict audit (gas, water, high-voltage electric, drainage)",
            "Geotechnical borehole soil testing for pier foundation bearing capacity",
        ]

        engineering_validation = [
            "Complete Traffic Impact Assessment (TIA) with micro-simulation of surface vs elevated flow",
            "Environmental and noise impact screening on adjacent residential/commercial zones",
            "Pier placement structural design and ramp gradient limit compliance (max 4-5%)",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Grade-Separated Flyover Feasibility Study: {loc_name}",
                intervention_type="flyover",
                description=(
                    "Preliminary screening indicates sustained corridor congestion and severe throughput degradation on this major corridor. "
                    "An elevated grade-separation feasibility study is recommended to determine whether separating through-traffic from surface intersection turning traffic is justified. "
                    "Construction must not be initiated without comprehensive volume warrants and ROW verification."
                ),
                priority=priority,
                impact_score=priority_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence=_calculate_confidence(obs, "junction_approach", s),
                uncertainty_notes=(
                    "Screening-level assessment based on network topology and traffic telemetry. "
                    "Requires comprehensive Right-of-Way (ROW) survey (min 30m corridor), vertical clearance verification (min 5.5m), "
                    "geotechnical soil borehole testing for foundation load capacity, and 24-hour directional Turning Movement Counts (TMC) prior to detailed design."
                ),
                requires_engineering_review=True,
                priority_score=priority_score,
                cause="junction_approach",
                screening_score_breakdown={
                    "congestion_factor": round(min(speed_drop * 3.0, 3.0), 1),
                    "delay_factor": round(min((obs.delay_seconds or 0) / 60.0, 2.0), 1),
                    "road_importance": 2.2,
                    "data_quality": 1.2 if obs.confidence and obs.confidence > 0.7 else 0.8,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="Telemetry represents live snapshot; 7-day automated traffic counts required for warrant approval.",
            )
        )

    # 2. Underpass Feasibility Screening
    # Candidate criteria: Urban arterial crossings where subterranean passage preserves surface access (NOT caused by incidents/closures)
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

        # STRICT EVIDENCE GATE: Do not recommend underpass for incidents or road closures
        is_closed = obs.road_closure or obs.congestion_level == "closed"
        has_incident = obs.has_incident or len(incidents_by_segment.get(s.segment_id, [])) > 0
        if is_closed or has_incident:
            continue

        speed_drop = obs.speed_reduction_ratio or 0.0
        delay_sec = obs.delay_seconds or 0.0
        if speed_drop >= 0.40 or delay_sec >= 35.0 or obs.congestion_level == "severe":
            underpass_candidates.append((speed_drop, s, obs))

    underpass_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in underpass_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "underpass"):
            continue
        loc_name = _get_segment_location_name(s)
        priority_score = min(8.6, round(6.5 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.48 else "medium"

        evidence = [
            f"Corridor Type: {s.road_type.capitalize()} ({s.osm_highway or 'urban arterial'})",
            f"Segment Length: {s.length_m:.0f} m",
        ]
        if speed_drop > 0:
            evidence.append(f"Observed Congestion: {speed_drop * 100:.0f}% speed reduction")
        if obs.delay_seconds is not None and obs.delay_seconds > 0:
            evidence.append(f"Travel-Time Delay: +{obs.delay_seconds:.0f}s above free-flow")
        evidence.append("Cross-corridor surface congestion warrants subterranean grade separation to preserve surface pedestrian access")

        missing_evidence = [
            "Subterranean utility mapping (water, gas, electric, telecommunications, sewage mains)",
            "Hydrological modeling and stormwater drainage catchment study (including dedicated pump basin design)",
            "Geotechnical water table elevation and soil stratification testing",
            "Cross-corridor turning movement counts and pedestrian desire lines",
        ]

        engineering_validation = [
            "Structural box girder / cut-and-cover structural design",
            "Stormwater pump station capacity and gravity drainage outfall confirmation",
            "Vertical clearance verification (min 5.0m for commercial vehicles, 3.5m for light vehicles)",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Subterranean Underpass Feasibility Investigation: {loc_name}",
                intervention_type="underpass",
                description=(
                    "Substantial cross-corridor conflict and persistent intersection delay indicate candidate viability for an underpass feasibility investigation. "
                    "Subsurface grade separation would permit continuous arterial flow while maintaining surface-level turning movements and local pedestrian access. "
                    "Feasibility is strictly subject to utility clearance and drainage engineering."
                ),
                priority=priority,
                impact_score=priority_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence=_calculate_confidence(obs, "junction_approach", s),
                uncertainty_notes=(
                    "Screening-level recommendation. Detailed engineering requires subterranean utility conflict mapping (water mains, high-voltage electric, telecoms, gas), "
                    "hydrological and stormwater drainage catchment modeling (including dedicated sump pump design), and water table level investigation."
                ),
                requires_engineering_review=True,
                priority_score=priority_score,
                cause="junction_approach",
                screening_score_breakdown={
                    "congestion_factor": round(min(speed_drop * 3.0, 3.0), 1),
                    "delay_factor": round(min((obs.delay_seconds or 0) / 60.0, 2.0), 1),
                    "road_importance": 1.8,
                    "data_quality": 1.0 if obs.confidence and obs.confidence > 0.7 else 0.7,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="Requires subsurface ground-penetrating radar (GPR) utility survey before design approval.",
            )
        )

    # 3. Road Divider / Central Median Screening
    # Candidate criteria: Multi-lane undivided roads where head-on and mid-block turning friction occurs
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
        # STRICT EVIDENCE GATE: Do not recommend central median for road closures or active incidents
        is_closed = obs and (obs.road_closure or obs.congestion_level == "closed")
        has_incident = obs and (obs.has_incident or len(incidents_by_segment.get(s.segment_id, [])) > 0)
        if is_closed or has_incident:
            continue
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
        priority_score = min(8.2, round(6.0 + speed_drop * 3.0, 1))
        priority = "high" if ((s.lanes and s.lanes >= 4) or speed_drop >= 0.40) else "medium"

        evidence = [
            f"Undivided Two-Way Cross Section: {s.lanes or 2}+ lanes on {s.road_type.capitalize()}",
            f"Segment Length: {s.length_m:.0f} m",
        ]
        if s.speed_limit_kmh:
            evidence.append(f"Operating Speed Limit: {s.speed_limit_kmh:.0f} km/h")
        if speed_drop > 0:
            evidence.append(f"Flow Disruption: {speed_drop * 100:.0f}% speed reduction from mid-block turning friction")
        evidence.append("OSM records two-way traffic without physical central division, exposing traffic to opposing flow friction")

        missing_evidence = [
            "Physical carriageway width measurement across the entire segment (OSM lacks exact curb-to-curb meters)",
            "Commercial driveway cut inventory and property access frequency",
            "Emergency vehicle turnaround frequency and U-turn demand survey",
            "Verification that a physical divider is not already present but unrecorded in OSM",
        ]

        engineering_validation = [
            "Carriageway width check: minimum 3.5m per lane remaining after 1.2m-1.8m median barrier installation (IRC:86)",
            "U-turn channelization pocket design and pedestrian refuge island placement",
            "Street lighting median pole mount design",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Raised Central Median & Access Management Assessment: {loc_name}",
                intervention_type="road_median",
                description=(
                    "This multi-lane two-way corridor operates without physical median division according to road-network records. "
                    "Installation of a raised concrete median barrier with channelized U-turn cuts and pedestrian refuge islands is recommended to eliminate opposing-flow conflicts. "
                    "Carriageway width must be physically measured to verify minimum lane widths post-installation."
                ),
                priority=priority,
                impact_score=priority_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence="medium" if obs and obs.confidence and obs.confidence > 0.6 else "low",
                uncertainty_notes=(
                    "Screening-level assessment. Requires physical carriageway width measurement to verify remaining lane widths (min 3.5m per lane) after 1.2m-1.8m median installation, "
                    "access management review of commercial driveways, and emergency vehicle turnaround frequency."
                ),
                requires_engineering_review=True,
                priority_score=priority_score,
                cause="junction_approach" if speed_drop > 0.3 else "structural_connectivity",
                screening_score_breakdown={
                    "congestion_factor": round(min(speed_drop * 3.0, 3.0), 1),
                    "delay_factor": round(min((obs.delay_seconds or 0) / 60.0, 2.0), 1) if obs else 0.0,
                    "road_importance": 1.5,
                    "data_quality": 1.0 if obs else 0.5,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="OSM road cross-section tags require field confirmation before contracting median works.",
            )
        )

    # 4. Traffic Signal Installation Screening (Warrant Assessment)
    # Candidate criteria: Explicitly unsignalized intersections with substantial approach delay
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
        # STRICT EVIDENCE GATE: Do not recommend signal installation for road closures or active incidents
        is_closed = obs.road_closure or obs.congestion_level == "closed"
        has_incident = obs.has_incident or len(incidents_by_segment.get(s.segment_id, [])) > 0
        if is_closed or has_incident:
            continue
        speed_drop = obs.speed_reduction_ratio or 0.0
        if speed_drop >= 0.30 or obs.congestion_level in ("severe", "moderate"):
            signal_candidates.append((speed_drop, s, obs))

    signal_candidates.sort(key=lambda item: item[0], reverse=True)
    for speed_drop, s, obs in signal_candidates[:2]:
        lat, lng = _get_segment_coords(s)
        if _is_duplicate(lat, lng, "signal_installation"):
            continue
        loc_name = _get_segment_location_name(s)
        priority_score = min(8.0, round(5.8 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.45 else "medium"

        evidence = [
            f"Unsignalized Control Configuration: {s.u_control or 'priority'} / {s.v_control or 'priority'}",
            f"Observed Congestion: {speed_drop * 100:.0f}% speed reduction on junction approach",
            "Multi-leg intersection approach delay indicates candidate viability for signalization warrants",
        ]
        if obs.delay_seconds is not None and obs.delay_seconds > 0:
            evidence.append(f"Approach Travel-Time Delay: +{obs.delay_seconds:.0f}s")

        missing_evidence = [
            "12-hour or 24-hour directional Turning Movement Counts (TMC)",
            "Peak hour volume warrants satisfaction (MUTCD Warrant 1 / Warrant 3 / IRC:93)",
            "Pedestrian crossing volume counts across minor and major legs",
            "Historical collision records for past 36 months",
        ]

        engineering_validation = [
            "Formal MUTCD / IRC Warrant Analysis by a certified traffic engineer",
            "Sight distance triangle inspection for all conflicting approaches",
            "Controller cabinet siting, electric utility drop, and ducting feasibility",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Traffic Signal Installation Warrant Investigation: {loc_name}",
                intervention_type="signal_installation",
                description=(
                    "This unsignalized multi-leg junction carries heavy approach traffic with substantial observed delay. "
                    "A formal warrant analysis is recommended to evaluate whether installing a multi-phase traffic signal is justified. "
                    "A traffic signal cannot be installed based solely on speed delay without satisfying established volume warrants."
                ),
                priority=priority,
                impact_score=priority_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence=_calculate_confidence(obs, "junction_approach", s),
                uncertainty_notes=(
                    "A traffic signal cannot be installed based solely on network delay. A comprehensive 12-hour or 24-hour Turning Movement Count (TMC) "
                    "and MUTCD / IRC Warrant analysis (Warrant 1: Eight-Hour Volume, Warrant 2: Four-Hour Volume, Warrant 3: Peak Hour Volume) are mandatory. "
                    "Sight distance triangles and controller cabinet power availability must also be verified."
                ),
                requires_engineering_review=True,
                priority_score=priority_score,
                cause="junction_approach",
                screening_score_breakdown={
                    "congestion_factor": round(min(speed_drop * 3.0, 3.0), 1),
                    "delay_factor": round(min((obs.delay_seconds or 0) / 60.0, 2.0), 1),
                    "road_importance": 1.5,
                    "data_quality": 1.1 if obs.confidence and obs.confidence > 0.7 else 0.8,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="Signal warrants require 12h-24h manual or camera turning movement counts.",
            )
        )

    # 5. Junction Redesign & Geometric Channelization
    # Candidate criteria: Bottlenecks with high centrality or intersections with complex convergence
    redesign_candidates: list[BottleneckCandidate] = [
        b for b in bottlenecks if (b.centrality_score and b.centrality_score >= 0.05) or b.severity in ("high", "medium")
    ]
    redesign_candidates.sort(key=lambda b: (b.centrality_score or 0.0), reverse=True)
    for b in redesign_candidates[:2]:
        if _is_duplicate(b.lat, b.lng, "junction_redesign"):
            continue
        loc_name = b.location_name or "Complex Intersection Node"
        centrality = b.centrality_score or 0.05
        priority_score = min(7.8, round(5.5 + centrality * 12.0, 1))
        priority = "high" if b.severity == "high" else "medium"

        evidence = [
            f"Network Centrality Score: {centrality:.3f} (High betweenness in sub-network)",
            f"Structural Bottleneck Severity: {b.severity.capitalize()}",
            "Strategic convergence point carries a high proportion of sub-area network routes",
        ]

        missing_evidence = [
            "Accurate intersection curb-to-curb geometric survey",
            "AutoTURN swept-path simulation for design vehicles (WB-15 trucks and 12m transit buses)",
            "Turning movement counts per approach leg",
            "Property line and corner setback verification",
        ]

        engineering_validation = [
            "Channelized turning island layout conforming to IRC:65 guidelines",
            "Curb radius redesign (min 9m-12m) and ADA-compliant pedestrian curb ramps",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Intersection Geometric Redesign & Channelization: {loc_name}",
                intervention_type="junction_redesign",
                description=(
                    "High structural centrality and intersecting traffic paths indicate this junction carries strategic network demand. "
                    "A geometric channelization review is recommended to organize turning paths, reduce vehicle conflict angles, and protect pedestrian crossings. "
                    "High centrality is a measure of network importance, not direct proof of geometric defect; swept-path analysis is required."
                ),
                priority=priority,
                impact_score=priority_score,
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
                priority_score=priority_score,
                cause="structural_connectivity",
                screening_score_breakdown={
                    "congestion_factor": 1.2 if b.severity == "high" else 0.8,
                    "delay_factor": 0.5,
                    "road_importance": round(min(centrality * 10.0, 2.0), 1),
                    "data_quality": 1.0,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="Centrality is derived from OSM topology; geometric defects must be field-verified.",
            )
        )

    # 6. Dedicated Turning Lane Assessment
    # Candidate criteria: Multi-lane arterials approaching junctions with delay (NOT caused by incidents)
    turn_candidates: list[tuple[float, RoadSegment, TrafficObservation]] = []
    for s in segments:
        is_candidate_road = s.road_type in ("arterial", "collector", "highway")
        has_multi_lanes = (s.lanes is not None and s.lanes >= 2) or s.road_type == "arterial"
        if not (is_candidate_road and has_multi_lanes):
            continue
        obs = traffic_by_segment.get(s.segment_id) or s.traffic
        if not obs:
            continue
        # Do not propose turning lane for road closures or incidents
        if obs.road_closure or obs.has_incident:
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
        priority_score = min(7.5, round(5.2 + speed_drop * 3.5, 1))
        priority = "high" if speed_drop >= 0.40 else "medium"

        evidence = [
            f"Corridor Profile: {s.lanes or 2}-lane {s.road_type.capitalize()} approach",
            f"Throughput Delay: {speed_drop * 100:.0f}% speed reduction on approach",
            "Observed approach delay suggests potential turning vehicle conflicts; queue spillback must be verified with turning counts",
        ]

        missing_evidence = [
            "Peak 15-minute turning movement counts (TMC) to establish turning volume percentage",
            "Measured queue length per lane during morning and evening peak periods",
            "Right-of-Way and carriageway width check to verify if lane addition requires widening or median flaring",
        ]

        engineering_validation = [
            "Turn bay deceleration length and storage length calculation (IRC:SP:73 / AASHTO)",
            "Approach taper length geometric design (typically 1:8 to 1:15 taper)",
        ]

        infra_recs.append(
            Recommendation(
                recommendation_id=_make_id(),
                title=f"Dedicated Auxiliary Turn Lane Feasibility Study: {loc_name}",
                intervention_type="dedicated_turning_lane",
                description=(
                    "Observed approach delay suggests through-lane capacity may be compromised by turning vehicles. "
                    "A turning movement study is recommended to determine if an exclusive turn pocket (left-turn or right-turn bay) "
                    "with adequate deceleration and storage length is warranted. Queue spillback cannot be asserted without field queue counts."
                ),
                priority=priority,
                impact_score=priority_score,
                category="infrastructure_planning",
                affected_location=loc_name,
                affected_segment_ids=[s.segment_id],
                lat=lat,
                lng=lng,
                supporting_evidence=evidence,
                confidence=_calculate_confidence(obs, "junction_approach", s),
                uncertainty_notes=(
                    "Screening-level recommendation. Detailed engineering requires peak 15-minute turning movement counts to calculate required storage length (AASHTO / IRC standard), "
                    "approach taper length analysis, and verification that right-of-way or carriageway width permits bay construction."
                ),
                requires_engineering_review=True,
                priority_score=priority_score,
                cause="junction_approach",
                screening_score_breakdown={
                    "congestion_factor": round(min(speed_drop * 3.0, 2.5), 1),
                    "delay_factor": round(min((obs.delay_seconds or 0) / 60.0, 2.0), 1),
                    "road_importance": 1.4,
                    "data_quality": 1.0 if obs.confidence and obs.confidence > 0.7 else 0.7,
                    "incident_modifier": 0.0,
                },
                missing_evidence=missing_evidence,
                engineering_validation_required=engineering_validation,
                data_coverage_note="Turning queue measurements and storage length calculations required.",
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
    incidents: Optional[list[TrafficIncident]] = None,
    historical_snapshots_count: int = 1,
) -> RecommendationsResult:
    """
    Generate evidence-backed recommendations organized into:
    - Traffic Optimization (operational management, signal timing, detour guidance)
    - Infrastructure Planning (flyovers, underpasses, medians, new signals, geometric redesign)

    Args:
        analysis_id: The analysis ID.
        bottlenecks: Detected bottleneck candidates.
        traffic_by_segment: Map of segment_id -> traffic observation.
        metrics: Road network metrics.
        weather: Weather context (supplementary).
        segments: Optional list of road segments for geometry and physical screening.
        incidents: Optional list of matched traffic incidents.
        historical_snapshots_count: Number of independent time snapshots observed (default 1).

    Returns:
        Structured recommendations result.
    """
    recommendations: list[Recommendation] = []
    optimization_notes: list[str] = [
        "Methodology: Multi-criteria evidence-based screening balancing network betweenness centrality, "
        "observed relative speed reduction, travel-time delay, active incidents, and functional road classification. "
        "Organized into Traffic Optimization (operational interventions) and Infrastructure Planning (physical civil candidates). "
        "Provides screening-level prioritization. Engineering feasibility studies and micro-simulation "
        "are required before capital allocation."
    ]
    warnings: list[str] = []

    segments_by_id: dict[str, RoadSegment] = {s.segment_id: s for s in segments} if segments else {}

    # Index incidents by affected segment ID
    incidents_by_segment: dict[str, list[TrafficIncident]] = {}
    if incidents:
        for inc in incidents:
            for sid in inc.affected_segment_ids:
                incidents_by_segment.setdefault(sid, []).append(inc)

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
        obs = traffic_by_segment.get(b.segment_id)
        seg = segments_by_id.get(b.segment_id)
        seg_incidents = incidents_by_segment.get(b.segment_id, [])

        cause, cause_explanation = _diagnose_congestion_cause(
            obs=obs,
            b=b,
            seg=seg,
            seg_incidents=seg_incidents,
            historical_snapshots_count=historical_snapshots_count,
        )

        impact_score, priority, score_breakdown = _score_bottleneck(b, obs, seg, seg_incidents)
        (
            intervention_type,
            title,
            description,
            category,
        ) = _choose_intervention(b, obs, metrics, seg, cause, seg_incidents)
        (
            missing_evidence,
            engineering_validation,
            rationale,
        ) = _get_intervention_specification(intervention_type, cause, b, seg, obs)

        # Build evidence list
        evidence = list(b.evidence)
        evidence.append(f"Diagnosis: {cause.replace('_', ' ').capitalize()} — {cause_explanation}")

        if obs:
            if obs.observed_speed_kmh is not None:
                evidence.append(
                    f"Observed speed: {obs.observed_speed_kmh:.0f} km/h"
                    + (f" (free-flow: {obs.free_flow_speed_kmh:.0f} km/h)" if obs.free_flow_speed_kmh else "")
                )
            if obs.speed_reduction_ratio is not None:
                evidence.append(f"Speed reduction: {obs.speed_reduction_ratio * 100:.0f}% below free-flow")
            if obs.delay_seconds is not None and obs.delay_seconds > 0:
                evidence.append(f"Travel-time delay: +{obs.delay_seconds:.0f}s ({obs.delay_percentage or 0:.0f}%)")
            if obs.has_incident:
                evidence.append("Active incident reported by TomTom at or near this location")
            if obs.confidence is not None:
                evidence.append(f"TomTom observation confidence: {obs.confidence * 100:.0f}%")
        else:
            evidence.append("No traffic observation data available for this location from TomTom")

        if seg:
            evidence.append(
                f"OSM Road Attributes: {seg.road_type.capitalize()}, length: {seg.length_m:.0f}m"
                + (f", lanes: {seg.lanes}" if seg.lanes else "")
                + (f", speed limit: {seg.speed_limit_kmh:.0f} km/h" if seg.speed_limit_kmh else "")
            )

        confidence = _calculate_confidence(obs, cause, seg)

        uncertainty = (
            "Screening-level recommendation. This recommendation is based on road network topology"
            + (" and a single TomTom traffic telemetry snapshot" if obs else " only")
            + ". A sustained observation period and on-site engineering traffic survey are required "
            "before committing to any infrastructure capital investment."
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
            cause=cause,
            screening_score_breakdown=score_breakdown,
            missing_evidence=missing_evidence,
            engineering_validation_required=engineering_validation,
            data_coverage_note="Single-snapshot observation; field surveys required to confirm volume warrants.",
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
            incidents_by_segment=incidents_by_segment,
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
