"""
Signal Candidates Management: Generates and manages candidate junctions for traffic signal placement.
Implements user-reviewable, evidence-backed candidate screening with durable SQLite persistence.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from app.core.sqlite_store import (
    get_candidate_decisions_sync,
    reset_candidate_decisions_sync,
    save_candidate_decision_sync,
)
from app.models.schemas import (
    AnalysisResult,
    CandidateStatus,
    RoadSegment,
    SignalCandidate,
    SignalCandidateListResponse,
)

logger = logging.getLogger(__name__)

# A map selection can contain hundreds of topological junctions.  A traffic
# signal is an intervention that needs a focused, human review, so only expose
# a small, spatially independent shortlist rather than every junction that has
# three connecting road segments.
MAX_REVIEW_CANDIDATES = 8
MIN_CANDIDATE_SPACING_METERS = 250.0


def _distance_meters(first: SignalCandidate, second: SignalCandidate) -> float:
    """Return an approximate great-circle distance between two candidates."""
    lat_scale = 111_320.0
    lon_scale = lat_scale * math.cos(math.radians((first.lat + second.lat) / 2.0))
    return math.hypot((first.lat - second.lat) * lat_scale, (first.lng - second.lng) * lon_scale)


def _extract_junction_nodes(
    segments: list[RoadSegment],
) -> dict[str, dict[str, Any]]:
    """
    Group road segments by junction node ID or coordinate key to identify junction topologies.
    """
    nodes: dict[str, dict[str, Any]] = {}
    coord_to_node: dict[tuple[float, float], str] = {}

    for seg in segments:
        geom = seg.geometry
        coords = geom.coordinates if geom else []
        if len(coords) < 2:
            continue

        u_coord = (round(coords[0][0], 5), round(coords[0][1], 5))
        v_coord = (round(coords[-1][0], 5), round(coords[-1][1], 5))

        u_id = f"node_{seg.u}" if seg.u is not None else coord_to_node.get(u_coord, f"node_{len(coord_to_node)}")
        coord_to_node[u_coord] = u_id

        v_id = f"node_{seg.v}" if seg.v is not None else coord_to_node.get(v_coord, f"node_{len(coord_to_node)}")
        coord_to_node[v_coord] = v_id

        u_lon, u_lat = coords[0][0], coords[0][1]
        v_lon, v_lat = coords[-1][0], coords[-1][1]

        for n_id, lon, lat, ctrl, prov in [
            (u_id, u_lon, u_lat, seg.u_control, seg.u_provenance),
            (v_id, v_lon, v_lat, seg.v_control, seg.v_provenance),
        ]:
            if n_id not in nodes:
                nodes[n_id] = {
                    "id": n_id,
                    "lng": float(lon),
                    "lat": float(lat),
                    "degree": 0,
                    "control": ctrl or "priority",
                    "provenance": prov or "unknown",
                    "connected_segments": [],
                    "road_names": set(),
                    "road_types": set(),
                    "approaches": set(),
                    "traffic_observations": [],
                }

            nodes[n_id]["degree"] += 1
            nodes[n_id]["connected_segments"].append(seg.segment_id)
            if seg.name:
                r_name = seg.name.strip()
                nodes[n_id]["road_names"].add(r_name)
                nodes[n_id]["approaches"].add(f"{r_name} ({seg.road_type or 'road'})")
            if seg.road_type:
                nodes[n_id]["road_types"].add(seg.road_type)
            if seg.traffic:
                nodes[n_id]["traffic_observations"].append(seg.traffic)

            # If any segment marks this node as traffic_signal, treat node as existing signal
            if ctrl == "traffic_signal":
                nodes[n_id]["control"] = "traffic_signal"
                nodes[n_id]["provenance"] = prov or "source_verified"

    return nodes


def generate_signal_candidates(analysis: AnalysisResult) -> list[SignalCandidate]:
    """
    Generate evidence-backed candidate junctions for traffic signal placement review.
    Screens junctions based on:
    - Topology & degree (degree >= 3 required)
    - Competing approach classifications (arterial/collector)
    - Traffic delay, speed reduction, and bottleneck evidence
    - Restores existing user approval/rejection decisions from persistent storage
    """
    if not analysis.segments:
        return []

    nodes = _extract_junction_nodes(analysis.segments)
    persisted_decisions = get_candidate_decisions_sync(analysis.analysis_id)

    # Map bottlenecks by proximity
    bottleneck_by_loc: dict[str, Any] = {}
    for b in analysis.bottlenecks:
        loc_key = f"{round(b.lat, 4)},{round(b.lng, 4)}"
        bottleneck_by_loc[loc_key] = b

    candidates: list[SignalCandidate] = []

    for n_id, n_data in nodes.items():
        degree = n_data["degree"]
        current_control = n_data["control"]
        lat = n_data["lat"]
        lng = n_data["lng"]
        candidate_id = f"cand_{n_id}"

        # Distinct road names and types
        road_names = list(n_data["road_names"])
        road_types = list(n_data["road_types"])

        if len(road_names) >= 2:
            jct_name = f"Intersection of {' & '.join(road_names[:3])}"
        elif len(road_names) == 1:
            jct_name = f"Junction along {road_names[0]}"
        else:
            primary_type = road_types[0].capitalize() if road_types else "Road"
            jct_name = f"{primary_type} Junction ({n_id})"

        approach_roads = sorted(list(n_data["approaches"]))[:6]
        if not approach_roads:
            approach_roads = [f"{t.capitalize()} Road" for t in road_types] or ["Corridor Link"]

        # Check for co-located bottleneck
        loc_key = f"{round(lat, 4)},{round(lng, 4)}"
        b_match = bottleneck_by_loc.get(loc_key)

        # Check traffic telemetry on approach segments
        traffics = n_data["traffic_observations"]
        avg_speed_drop = 0.0
        if traffics:
            drops = [t.speed_reduction_ratio for t in traffics if t.speed_reduction_ratio is not None]
            if drops:
                avg_speed_drop = sum(drops) / len(drops)

        # Signalization is only screened for major intersections.  The old
        # degree >= 3 rule treated ordinary residential T-junctions as signal
        # candidates and flooded the map with markers.
        is_already_signal = current_control == "traffic_signal"
        has_major_approach = any(road_type in {"arterial", "highway", "collector"} for road_type in road_types)
        is_eligible = degree >= 4 and has_major_approach and not is_already_signal

        evidence: list[str] = [
            f"Junction Topology: {degree}-way intersection ({', '.join(road_types) if road_types else 'local'})",
            f"Current Right-of-Way: {current_control.capitalize()} control",
        ]

        if avg_speed_drop > 0:
            evidence.append(f"Approach Traffic Delay: {avg_speed_drop * 100:.0f}% speed drop below free-flow")

        if b_match:
            evidence.append(f"Identified Network Bottleneck: Severity {b_match.severity.upper()}")
            if b_match.centrality_score:
                evidence.append(f"Network Centrality Score: {b_match.centrality_score:.3f}")

        # Compute ranking score (0.0 - 10.0)
        score = 0.0
        if is_eligible:
            # Baseline structural points for degree
            score += 3.0 if degree >= 4 else 2.0

            # Functional class contribution
            if "arterial" in road_types or "highway" in road_types:
                score += 2.5
            if "collector" in road_types:
                score += 1.0

            # Traffic delay contribution
            if avg_speed_drop > 0:
                score += min(3.0, avg_speed_drop * 5.0)

            # Bottleneck contribution
            if b_match:
                score += 1.5

            score = min(9.5, round(score, 1))

            reason = (
                f"Multi-branch {degree}-leg junction connecting {', '.join(road_names[:2]) or 'arterial corridors'}. "
                "Installing an engineered traffic signal would resolve conflicting approach movements, "
                "eliminate right-of-way ambiguity, and manage peak queuing."
            )
            confidence = "high" if avg_speed_drop > 0 else "medium"
            evidence_source = "observed_traffic_data" if avg_speed_drop > 0 else "network_geometry_centrality"
        elif is_already_signal:
            score = 5.0
            reason = "Intersection is already signalized in baseline road network. Eligible for timing plan optimization."
            confidence = "high"
            evidence_source = "source_verified_signal"
        else:
            score = 1.0
            reason = f"Ineligible for signal installation (Degree {degree} < 3: simple road segment curvature or dead-end)."
            confidence = "low"
            evidence_source = "network_geometry_centrality"

        uncertainty_notes = (
            "Screening-level candidate evaluation. Signal installation requires field validation with "
            "12-hour or 24-hour Turning Movement Counts (TMC), MUTCD Warrant 1 (Eight-Hour Vehicular Volume) / "
            "Warrant 3 (Peak Hour Volume) compliance, and physical sight distance audits."
        )

        # Determine user decision state
        if not is_eligible:
            status: CandidateStatus = "ineligible"
        elif candidate_id in persisted_decisions:
            status = persisted_decisions[candidate_id]  # "approved", "rejected", "pending"
        else:
            status = "pending"

        candidates.append(
            SignalCandidate(
                candidate_id=candidate_id,
                analysis_id=analysis.analysis_id,
                junction_id=n_id,
                lat=lat,
                lng=lng,
                name=jct_name,
                degree=degree,
                approach_roads=approach_roads,
                current_control=current_control,
                is_eligible=is_eligible,
                priority_score=score,
                reason=reason,
                evidence=evidence,
                evidence_source=evidence_source,
                confidence=confidence,
                uncertainty_notes=uncertainty_notes,
                status=status,
            )
        )

    # Existing source-verified signals are shown by the simulation itself; they
    # do not belong in the installation-candidate review layer.  Keep only
    # high-priority candidates and de-duplicate nearby junctions so a single
    # corridor cannot produce a wall of traffic-light icons.
    eligible = [c for c in candidates if c.is_eligible]
    eligible.sort(
        key=lambda c: (c.priority_score, c.degree),
        reverse=True,
    )

    shortlist: list[SignalCandidate] = []
    for candidate in eligible:
        if any(_distance_meters(candidate, chosen) < MIN_CANDIDATE_SPACING_METERS for chosen in shortlist):
            continue
        shortlist.append(candidate)
        if len(shortlist) == MAX_REVIEW_CANDIDATES:
            break
    return shortlist


def get_signal_candidates_response(analysis: AnalysisResult) -> SignalCandidateListResponse:
    """Compile SignalCandidateListResponse with accurate counts."""
    candidates = generate_signal_candidates(analysis)
    approved = sum(1 for c in candidates if c.status == "approved")
    rejected = sum(1 for c in candidates if c.status == "rejected")
    pending = sum(1 for c in candidates if c.status == "pending")
    eligible = sum(1 for c in candidates if c.is_eligible)

    return SignalCandidateListResponse(
        analysis_id=analysis.analysis_id,
        candidates=candidates,
        total_candidates=len(candidates),
        approved_count=approved,
        rejected_count=rejected,
        pending_count=pending,
        eligible_count=eligible,
    )


def update_candidate_decision(
    analysis_id: str,
    candidate_id: str,
    status: CandidateStatus,
) -> None:
    """Save user approval/rejection decision for a signal candidate."""
    save_candidate_decision_sync(analysis_id, candidate_id, status)
    logger.info("Updated signal candidate decision: %s -> %s for analysis %s", candidate_id, status, analysis_id)


def approve_all_eligible_candidates(analysis: AnalysisResult) -> int:
    """Approve all eligible candidates for an analysis."""
    candidates = generate_signal_candidates(analysis)
    count = 0
    for c in candidates:
        if c.is_eligible:
            save_candidate_decision_sync(analysis.analysis_id, c.candidate_id, "approved")
            count += 1
    logger.info("Approved all %d eligible candidates for analysis %s", count, analysis.analysis_id)
    return count


def reset_candidates(analysis_id: str) -> None:
    """Reset all candidate decisions for an analysis back to pending."""
    reset_candidate_decisions_sync(analysis_id)
    logger.info("Reset all candidate decisions for analysis %s", analysis_id)
