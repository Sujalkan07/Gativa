"""
Spatial matching utilities for Gativa.
Validates TomTom flow observations against OSM road segments and
links traffic incidents (Point and LineString) to affected road network segments.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Any
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points

from app.models.schemas import RoadSegment, TrafficObservation, TrafficIncident

logger = logging.getLogger(__name__)

# FRC to Road Type Compatibility Mapping
# TomTom Functional Road Classes:
# FRC0: Motorway / Freeway
# FRC1: Major International Road
# FRC2: Other Major Road
# FRC3: Secondary Road
# FRC4: Local Connecting Road
# FRC5: Local Road of High Importance
# FRC6: Local Road
FRC_ROAD_TYPE_COMPATIBILITY = {
    "highway": {"FRC0", "FRC1", "FRC2"},
    "arterial": {"FRC1", "FRC2", "FRC3", "FRC4"},
    "local": {"FRC4", "FRC5", "FRC6"},
}


def _lat_lon_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Fast, accurate equirectangular approximation of distance in meters between two WGS84 points."""
    avg_lat = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111139.0 * math.cos(avg_lat)
    dy = (lat2 - lat1) * 111139.0
    return math.hypot(dx, dy)


def _compute_linestring_bearing(coords: list[list[float]]) -> Optional[float]:
    """
    Compute overall bearing in degrees [0, 360) for a coordinate sequence [[lng, lat], ...].
    Returns None if line is too short.
    """
    if not coords or len(coords) < 2:
        return None
    start = coords[0]
    end = coords[-1]
    dx = (end[0] - start[0]) * math.cos(math.radians((start[1] + end[1]) / 2.0))
    dy = end[1] - start[1]
    if abs(dx) < 1e-7 and abs(dy) < 1e-7:
        return None
    angle = math.degrees(math.atan2(dy, dx))
    return (angle + 360.0) % 360.0


def _bearing_difference_degrees(bearing1: float, bearing2: float, is_oneway: bool = False) -> float:
    """
    Compute minimal angular difference between two bearings in degrees [0, 180].
    If the road is bidirectional (is_oneway=False), traffic can move in opposite directions,
    so difference is computed modulo 180 (range [0, 90]).
    """
    diff = abs(bearing1 - bearing2) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    if not is_oneway:
        if diff > 90.0:
            diff = 180.0 - diff
    return diff


def _point_to_linestring_distance_meters(
    pt_lng: float, pt_lat: float, line_coords: list[list[float]]
) -> float:
    """Calculate minimum distance in meters from a point [lng, lat] to a LineString."""
    if not line_coords:
        return float("inf")
    if len(line_coords) == 1:
        return _lat_lon_distance_meters(pt_lat, pt_lng, line_coords[0][1], line_coords[0][0])

    try:
        pt = Point(pt_lng, pt_lat)
        line = LineString([(c[0], c[1]) for c in line_coords])
        nearest_pt = line.interpolate(line.project(pt))
        return _lat_lon_distance_meters(pt_lat, pt_lng, nearest_pt.y, nearest_pt.x)
    except Exception as exc:
        logger.debug("Point-to-linestring distance calculation error: %s", exc)
        return min(
            _lat_lon_distance_meters(pt_lat, pt_lng, c[1], c[0]) for c in line_coords
        )


def validate_flow_match(
    observation: TrafficObservation,
    segment: RoadSegment,
    max_distance_meters: float = 60.0,
) -> tuple[bool, str, float]:
    """
    Validate whether a TomTom flow observation corresponds to the intended OSM road segment.
    Checks:
    1. Spatial proximity between segment geometry and TomTom fragment/query point.
    2. Directional compatibility if fragment geometry is available.
    3. FRC functional class compatibility.

    Returns:
        (is_valid, match_quality, match_distance_m)
        where match_quality is one of: "exact", "high", "medium", "low", "unmatched"
    """
    if not segment.geometry or not segment.geometry.coordinates:
        # Without segment geometry, cannot reliably match
        return False, "unmatched", float("inf")

    seg_coords = segment.geometry.coordinates
    tt_coords = observation.coordinates

    # 1. Spatial Proximity
    if tt_coords and len(tt_coords) >= 2:
        # Distance between segment midpoint and TomTom fragment
        mid_idx = len(seg_coords) // 2
        seg_mid = seg_coords[mid_idx]
        dist_m = _point_to_linestring_distance_meters(seg_mid[0], seg_mid[1], tt_coords)
    elif tt_coords and len(tt_coords) == 1:
        mid_idx = len(seg_coords) // 2
        seg_mid = seg_coords[mid_idx]
        dist_m = _lat_lon_distance_meters(seg_mid[1], seg_mid[0], tt_coords[0][1], tt_coords[0][0])
    else:
        # No fragment geometry returned - query was placed at segment midpoint
        dist_m = 0.0

    if dist_m > max_distance_meters:
        return False, "unmatched", round(dist_m, 1)

    # 2. Directional Compatibility
    angle_diff = 0.0
    directional_check_performed = False
    if tt_coords and len(tt_coords) >= 2 and len(seg_coords) >= 2:
        seg_bearing = _compute_linestring_bearing(seg_coords)
        tt_bearing = _compute_linestring_bearing(tt_coords)
        if seg_bearing is not None and tt_bearing is not None:
            directional_check_performed = True
            angle_diff = _bearing_difference_degrees(
                seg_bearing, tt_bearing, is_oneway=segment.is_oneway
            )
            # Threshold: crossing perpendicular road (> 50 deg difference) is a mismatch
            if angle_diff > 50.0:
                logger.debug(
                    "Directional mismatch for segment %s: angle diff %.1f° > 50°",
                    segment.segment_id,
                    angle_diff,
                )
                return False, "unmatched", round(dist_m, 1)

    # 3. FRC vs Road Class Compatibility
    frc_penalty = False
    if observation.frc:
        frc_clean = observation.frc.strip().upper()
        allowed_frcs = FRC_ROAD_TYPE_COMPATIBILITY.get(segment.road_type, set())
        if allowed_frcs and frc_clean not in allowed_frcs:
            # Severe mismatch: local road matched to motorway FRC0/FRC1 (e.g. flyover)
            if segment.road_type == "local" and frc_clean in ("FRC0", "FRC1"):
                logger.debug(
                    "Severe FRC mismatch for segment %s (%s vs %s)",
                    segment.segment_id,
                    segment.road_type,
                    frc_clean,
                )
                return False, "unmatched", round(dist_m, 1)
            frc_penalty = True

    # 4. Determine Quality Label
    if dist_m <= 15.0 and (not directional_check_performed or angle_diff <= 25.0) and not frc_penalty:
        quality = "exact" if dist_m <= 5.0 else "high"
    elif dist_m <= 35.0 and (not directional_check_performed or angle_diff <= 40.0):
        quality = "medium"
    elif dist_m <= max_distance_meters and not frc_penalty:
        quality = "low"
    else:
        quality = "unmatched"

    is_valid = quality in ("exact", "high", "medium", "low")
    return is_valid, quality, round(dist_m, 1)


def match_incidents_to_segments(
    incidents: list[TrafficIncident],
    segments: list[RoadSegment],
    proximity_threshold_m: float = 40.0,
) -> None:
    """
    Connect traffic incidents to OSM road segments using spatial geometry analysis.
    Mutates incidents in-place to populate affected_segment_ids and match_quality.
    Also updates seg.traffic.has_incident = True for affected segments.
    """
    if not incidents or not segments:
        return

    # Index segments with valid geometry
    valid_segments: list[tuple[RoadSegment, LineString, list[list[float]]]] = []
    for seg in segments:
        if seg.geometry and seg.geometry.coordinates and len(seg.geometry.coordinates) >= 2:
            try:
                line = LineString([(c[0], c[1]) for c in seg.geometry.coordinates])
                valid_segments.append((seg, line, seg.geometry.coordinates))
            except Exception:
                continue

    if not valid_segments:
        return

    for inc in incidents:
        confirmed_ids: set[str] = set()
        likely_ids: set[str] = set()
        nearby_ids: set[str] = set()
        best_dist = float("inf")

        # Check incident geometry
        geom_type = "Point"
        geom_coords = None
        if inc.geometry and isinstance(inc.geometry, dict):
            geom_type = inc.geometry.get("type", "Point")
            geom_coords = inc.geometry.get("coordinates")

        inc_bearing: Optional[float] = None
        if geom_type == "LineString" and geom_coords and len(geom_coords) >= 2:
            try:
                inc_bearing = _compute_linestring_bearing(geom_coords)
                inc_line = LineString([(c[0], c[1]) for c in geom_coords])
                for seg, seg_line, coords in valid_segments:
                    p_seg, p_inc = nearest_points(seg_line, inc_line)
                    dist_m = _lat_lon_distance_meters(p_seg.y, p_seg.x, p_inc.y, p_inc.x)
                    if dist_m > proximity_threshold_m:
                        continue

                    if dist_m < best_dist:
                        best_dist = dist_m

                    # Bearing alignment check
                    angle_diff: Optional[float] = None
                    if inc_bearing is not None and len(coords) >= 2:
                        seg_bearing = _compute_linestring_bearing(coords)
                        if seg_bearing is not None:
                            angle_diff = _bearing_difference_degrees(
                                seg_bearing, inc_bearing, is_oneway=seg.is_oneway
                            )

                    # Road name / corridor identifier matching
                    name_match = False
                    if inc.road_numbers and seg.name:
                        name_match = any(rn.lower() in seg.name.lower() for rn in inc.road_numbers)

                    # 4-tier classification: CONFIRMED_AFFECTED, LIKELY_AFFECTED, NEARBY
                    if dist_m <= 15.0 and (angle_diff is None or angle_diff <= 35.0 or name_match):
                        confirmed_ids.add(seg.segment_id)
                    elif dist_m <= 25.0 and (angle_diff is None or angle_diff <= 45.0 or name_match):
                        likely_ids.add(seg.segment_id)
                    else:
                        nearby_ids.add(seg.segment_id)
            except Exception as exc:
                logger.debug("LineString incident matching error for %s: %s", inc.incident_id, exc)

        # Fallback to Point proximity (or if geom_type is Point)
        if not confirmed_ids and not likely_ids and not nearby_ids:
            pt_lat = inc.lat
            pt_lng = inc.lng
            if pt_lat is not None and pt_lng is not None and (pt_lat != 0.0 or pt_lng != 0.0):
                try:
                    inc_pt_geom = Point(pt_lng, pt_lat)
                    for seg, seg_line, coords in valid_segments:
                        p_seg, p_inc = nearest_points(seg_line, inc_pt_geom)
                        dist_m = _lat_lon_distance_meters(p_seg.y, p_seg.x, p_inc.y, p_inc.x)
                        if dist_m > proximity_threshold_m:
                            continue

                        if dist_m < best_dist:
                            best_dist = dist_m

                        name_match = False
                        if inc.road_numbers and seg.name:
                            name_match = any(rn.lower() in seg.name.lower() for rn in inc.road_numbers)

                        if dist_m <= 15.0 or (name_match and dist_m <= 20.0):
                            confirmed_ids.add(seg.segment_id)
                        elif dist_m <= 25.0 or (name_match and dist_m <= 35.0):
                            likely_ids.add(seg.segment_id)
                        else:
                            nearby_ids.add(seg.segment_id)
                except Exception as exc:
                    logger.debug("Point incident matching error for %s: %s", inc.incident_id, exc)

        # Populate incident matching breakdown
        inc.confirmed_segment_ids = sorted(list(confirmed_ids))
        inc.likely_segment_ids = sorted(list(likely_ids))
        inc.nearby_segment_ids = sorted(list(nearby_ids))
        
        # Only confirmed and likely affected segments are considered genuinely affected
        affected = confirmed_ids.union(likely_ids)
        inc.affected_segment_ids = sorted(list(affected))

        if confirmed_ids:
            inc.match_quality = "CONFIRMED_AFFECTED"
        elif likely_ids:
            inc.match_quality = "LIKELY_AFFECTED"
        elif nearby_ids:
            inc.match_quality = "NEARBY"
        else:
            inc.match_quality = "UNMATCHED"

        # Update has_incident flag strictly on confirmed/likely segments
        for seg_id in affected:
            for seg, _, _ in valid_segments:
                if seg.segment_id == seg_id:
                    if seg.traffic:
                        seg.traffic.has_incident = True
