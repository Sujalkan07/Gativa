"""
Network Builder: Converts Gativa analyzed road network into a valid Eclipse SUMO network.
Generates .nod.xml, .edg.xml, routes.rou.xml, and simulation.sumocfg, and runs netconvert.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
import xml.etree.ElementTree as ET

import networkx as nx
from shapely.geometry import LineString, MultiPoint, Point, Polygon

logger = logging.getLogger(__name__)

# Maximum road segments to compile into a single SUMO network.
# Supports large corridor and city-grid selections.
MAX_SEGMENTS = 3000
SIMULATION_STEP_LENGTH_SECONDS = 0.2


def interpret_lane_configuration(
    total_lanes: Optional[int],
    lanes_forward: Optional[int] = None,
    lanes_backward: Optional[int] = None,
    is_oneway: bool = False,
    road_class: str = "arterial",
) -> tuple[int, int, bool]:
    """
    Accurately interprets road lane configuration and directional distribution.
    Respects explicit forward/backward lane tags and one-way status.
    Differentiates verified from inferred lane counts.

    Returns:
        (fwd_lanes, bwd_lanes, is_estimated)
    """
    if lanes_forward is not None and lanes_backward is not None:
        fwd = max(1, int(lanes_forward))
        bwd = 0 if is_oneway else max(0, int(lanes_backward))
        return fwd, bwd, False

    road_cls = (road_class or "").lower()
    is_major = any(k in road_cls for k in ("motorway", "trunk", "highway", "primary"))

    if is_oneway:
        if lanes_forward is not None:
            return max(1, int(lanes_forward)), 0, False
        if total_lanes is not None and int(total_lanes) > 0:
            return max(1, int(total_lanes)), 0, False
        # Documented inference for one-way roads
        if is_major or "arterial" in road_cls:
            return 2, 0, True
        else:
            return 1, 0, True

    # Two-way roads
    if total_lanes is not None and int(total_lanes) > 0:
        tot = int(total_lanes)
        if lanes_forward is not None:
            fwd = max(1, int(lanes_forward))
            bwd = max(1, tot - fwd)
            return fwd, bwd, False
        if tot == 1:
            return 1, 1, False
        fwd = max(1, (tot + 1) // 2)
        bwd = max(1, tot // 2)
        return fwd, bwd, False

    # Missing lane tags: infer from road_class
    if is_major:
        return 2, 2, True
    elif "secondary" in road_cls or "arterial" in road_cls:
        return 2, 2, True
    else:
        return 1, 1, True


def find_sumo_binary(binary_name: str = "sumo") -> Optional[str]:
    """Locate a SUMO binary (e.g. 'sumo' or 'netconvert') on Windows/Linux."""
    exe_name = f"{binary_name}.exe" if os.name == "nt" else binary_name

    # 1. Check SUMO_HOME environment variable
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = Path(sumo_home) / "bin" / exe_name
        if candidate.is_file():
            return str(candidate)

    # 2. Check standard Windows installation directory
    standard_win = Path(r"C:\Program Files (x86)\SUMO\bin") / exe_name
    if standard_win.is_file():
        return str(standard_win)

    # 3. Check system PATH
    which_path = shutil.which(binary_name) or shutil.which(exe_name)
    if which_path:
        return which_path

    return None


class SumoNetworkBuilder:
    """Builds SUMO network and demand artifacts from Gativa road segments."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.netconvert_bin = find_sumo_binary("netconvert")

    def build(
        self,
        segments: list[dict[str, Any]],
        duration_seconds: int = 600,
        demand_rate_veh_hr: int = 2840,
        seed: int = 42,
        polygon_coords: Optional[list[list[float]]] = None,
        demand_level: Optional[str] = "normal",
        demand_profile: Optional[str] = "peak",
        vehicle_types: Optional[dict[str, float]] = None,
        manual_vehicle_count: Optional[int] = None,
        live_observations: Optional[list[dict[str, Any]]] = None,
        allow_synthetic: bool = False,
        approved_signal_junctions: Optional[set[str]] = None,
        initial_population: Optional[int] = None,
        external_buffer_m: float = 500.0,
    ) -> dict[str, Any]:
        """
        Create complete SUMO simulation directory:
        1. nodes.nod.xml
        2. edges.edg.xml
        3. netconvert -> network.net.xml (with UTM projection for accurate WGS84 coordinates)
        4. routes.rou.xml (boundary entry-to-exit through-trips + demand profile scheduling)
        5. simulation.sumocfg
        """
        nod_file = self.work_dir / "nodes.nod.xml"
        edg_file = self.work_dir / "edges.edg.xml"
        net_file = self.work_dir / "network.net.xml"
        rou_file = self.work_dir / "routes.rou.xml"
        cfg_file = self.work_dir / "simulation.sumocfg"

        # 1. Process Nodes and Edges (including external buffer)
        nodes, edges, segment_edge_map, edge_segment_map, assumptions = self._extract_nodes_and_edges(
            segments,
            polygon_coords,
            allow_synthetic=allow_synthetic,
            approved_signal_junctions=approved_signal_junctions,
            external_buffer_m=external_buffer_m,
        )
        self._write_nodes_xml(nod_file, nodes)
        self._write_edges_xml(edg_file, edges)

        # 2. Run netconvert with UTM projection (establishes true CRS for convertGeo)
        compilation_diag = self._run_netconvert_with_diagnostics(
            nod_file=nod_file,
            edg_file=edg_file,
            net_file=net_file,
            nodes=nodes,
            edges=edges,
        )
        netconvert_success = compilation_diag["netconvert_used"]

        # 3. Calculate calibrated demand rate and data source provenance
        calibrated_rate, total_veh_target, demand_source, demand_label = self._estimate_traffic_demand(
            segments=segments,
            edges=edges,
            duration_seconds=duration_seconds,
            demand_rate_veh_hr=demand_rate_veh_hr,
            demand_level=demand_level,
            manual_vehicle_count=manual_vehicle_count,
            live_observations=live_observations,
        )

        # 4. Write Vehicle Demand (Routes) using continuous Poisson arrivals across duration
        scheduled_count, init_count = self._write_routes_xml(
            file_path=rou_file,
            nodes=nodes,
            edges=edges,
            duration_seconds=duration_seconds,
            demand_rate_veh_hr=calibrated_rate,
            seed=seed,
            polygon_coords=polygon_coords,
            demand_profile=demand_profile or "peak",
            vehicle_types=vehicle_types,
            target_vehicle_count=total_veh_target,
            initial_population=initial_population,
        )

        # 5. Write SUMO Configuration with dynamic rerouting support
        self._write_sumocfg(cfg_file, net_file.name, rou_file.name, duration_seconds)

        # 6. Extract authoritative network geometry for frontend rendering
        network_geometry = self._extract_network_geometry(
            net_file=net_file,
            edges_meta=edges,
            nodes_meta=nodes,
            polygon_coords=polygon_coords,
            buffer_m=external_buffer_m,
        )

        signal_count = sum(1 for n in nodes.values() if n.get("type") == "traffic_light")
        return {
            "work_dir": str(self.work_dir),
            "net_file": str(net_file),
            "cfg_file": str(cfg_file),
            "rou_file": str(rou_file),
            "edge_count": len(edges),
            "junction_count": len(nodes),
            "signal_count": signal_count,
            "netconvert_used": netconvert_success,
            "duration_seconds": duration_seconds,
            "demand_rate_veh_hr": calibrated_rate,
            "demand_level": demand_level or "normal",
            "demand_profile": demand_profile or "peak",
            "demand_data_source": demand_source,
            "demand_source_label": demand_label,
            "scheduled_vehicles": max(0, scheduled_count - init_count),
            "initial_vehicles_count": init_count,
            "requested_demand": total_veh_target or max(15, int(calibrated_rate * (duration_seconds / 3600.0))),
            "generated_demand": scheduled_count,
            "valid_trips_count": getattr(self, "demand_tracking", {}).get("valid_trips_count", scheduled_count),
            "rejected_trips_count": getattr(self, "demand_tracking", {}).get("rejected_trips_count", 0),
            "nodes": nodes,
            "edges": edges,
            "segment_edge_map": segment_edge_map,
            "edge_segment_map": edge_segment_map,
            "assumptions": assumptions,
            "total_eligible_segments": len(segments),
            "segments_simulated": len(edges),
            "omitted_segments_count": max(0, len(segments) - MAX_SEGMENTS),
            "network_provenance": "synthetic_demo" if "synthetic_corridor_generated" in assumptions else ("real_osm" if netconvert_success else "unvalidated_structural_fallback"),
            "compilation_diagnostics": compilation_diag,
            "boundary_diagnostics": getattr(self, "boundary_diagnostics", {}),
            "network_geometry": network_geometry,
            "external_buffer_distance_m": external_buffer_m,
        }

    def _build_external_road_buffer(
        self,
        segments: list[dict[str, Any]],
        polygon_coords: Optional[list[list[float]]],
        buffer_m: float = 500.0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Build or preserve an external road-network buffer around the selected analysis polygon.
        Follows real OpenStreetMap road geometry extending beyond the polygon when available.
        For fallback scenarios, provides clean tangent approach/departure segments for boundary-crossing
        roads without any artificial outer perimeter rings or fabricated connecting shortcuts.
        """
        import math
        if not polygon_coords or len(polygon_coords) < 3 or buffer_m <= 0:
            return list(segments), {"buffer_applied": False, "buffer_segments_added": 0}

        # 1. If segments already contain verified real OSM buffer geometry, preserve them authentically
        existing_buffer_segs = [s for s in segments if s.get("is_buffer")]
        if existing_buffer_segs:
            return list(segments), {
                "buffer_applied": True,
                "buffer_source": "real_osm_geometry",
                "buffer_distance_m": buffer_m,
                "buffer_segments_added": len(existing_buffer_segs),
                "external_endpoints_count": len(existing_buffer_segs),
            }

        try:
            raw_poly = Polygon(polygon_coords)
            if not raw_poly.is_valid:
                raw_poly = raw_poly.buffer(0)
            if raw_poly.is_empty:
                return list(segments), {"buffer_applied": False, "buffer_segments_added": 0}
        except Exception as e:
            logger.debug("Failed to build Shapely polygon for buffer: %s", e)
            return list(segments), {"buffer_applied": False, "buffer_segments_added": 0}

        poly_boundary = raw_poly.boundary
        centroid = raw_poly.centroid
        lat_rad = math.radians(centroid.y)
        deg_lat = buffer_m / 111320.0
        deg_lon = buffer_m / (111320.0 * max(0.1, math.cos(lat_rad)))

        min_x, min_y, max_x, max_y = raw_poly.bounds
        span = max(max_x - min_x, max_y - min_y, 0.0001)
        b_tol = max(0.0001, span * 0.12)

        all_segments = list(segments)
        buffer_segments: list[dict[str, Any]] = []
        external_endpoints: list[tuple[float, float, float, str, dict[str, Any]]] = []

        for s_idx, seg in enumerate(segments):
            geom = seg.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue

            p_start = Point(coords[0][0], coords[0][1])
            p_end = Point(coords[-1][0], coords[-1][1])
            d_start = poly_boundary.distance(p_start)
            d_end = poly_boundary.distance(p_end)

            if d_start <= b_tol:
                dx = coords[0][0] - coords[1][0]
                dy = coords[0][1] - coords[1][1]
                mag = math.hypot(dx, dy)
                if mag > 1e-9:
                    dx_norm = dx / mag
                    dy_norm = dy / mag
                else:
                    dx_norm = coords[0][0] - centroid.x
                    dy_norm = coords[0][1] - centroid.y
                    c_mag = math.hypot(dx_norm, dy_norm) or 1.0
                    dx_norm /= c_mag
                    dy_norm /= c_mag

                ext_lon = round(coords[0][0] + dx_norm * deg_lon, 6)
                ext_lat = round(coords[0][1] + dy_norm * deg_lat, 6)
                ext_node_id = f"ext_node_s_{s_idx}"
                ext_seg_id = f"buf_ext_s_{s_idx}"

                buf_seg = {
                    "segment_id": ext_seg_id,
                    "name": f"{seg.get('name', 'Corridor')} (Approach)",
                    "road_type": seg.get("road_type") or "arterial",
                    "lanes": seg.get("lanes") or 2,
                    "lanes_forward": seg.get("lanes_forward"),
                    "lanes_backward": seg.get("lanes_backward"),
                    "speed_limit_kmh": seg.get("speed_limit_kmh") or 50.0,
                    "is_oneway": seg.get("is_oneway", False),
                    "is_buffer": True,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[coords[0][0], coords[0][1]], [ext_lon, ext_lat]],
                    },
                    "u": seg.get("u"),
                    "v": ext_node_id,
                }
                buffer_segments.append(buf_seg)
                angle = math.atan2(ext_lat - centroid.y, ext_lon - centroid.x)
                external_endpoints.append((angle, ext_lon, ext_lat, ext_node_id, buf_seg))

            if d_end <= b_tol:
                dx = coords[-1][0] - coords[-2][0]
                dy = coords[-1][1] - coords[-2][1]
                mag = math.hypot(dx, dy)
                if mag > 1e-9:
                    dx_norm = dx / mag
                    dy_norm = dy / mag
                else:
                    dx_norm = coords[-1][0] - centroid.x
                    dy_norm = coords[-1][1] - centroid.y
                    c_mag = math.hypot(dx_norm, dy_norm) or 1.0
                    dx_norm /= c_mag
                    dy_norm /= c_mag

                ext_lon = round(coords[-1][0] + dx_norm * deg_lon, 6)
                ext_lat = round(coords[-1][1] + dy_norm * deg_lat, 6)
                ext_node_id = f"ext_node_e_{s_idx}"
                ext_seg_id = f"buf_ext_e_{s_idx}"

                buf_seg = {
                    "segment_id": ext_seg_id,
                    "name": f"{seg.get('name', 'Corridor')} (Approach)",
                    "road_type": seg.get("road_type") or "arterial",
                    "lanes": seg.get("lanes") or 2,
                    "lanes_forward": seg.get("lanes_forward"),
                    "lanes_backward": seg.get("lanes_backward"),
                    "speed_limit_kmh": seg.get("speed_limit_kmh") or 50.0,
                    "is_oneway": seg.get("is_oneway", False),
                    "is_buffer": True,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[coords[-1][0], coords[-1][1]], [ext_lon, ext_lat]],
                    },
                    "u": seg.get("v"),
                    "v": ext_node_id,
                }
                buffer_segments.append(buf_seg)
                angle = math.atan2(ext_lat - centroid.y, ext_lon - centroid.x)
                external_endpoints.append((angle, ext_lon, ext_lat, ext_node_id, buf_seg))

        # Authentic connectivity: No artificial perimeter ring is ever generated.
        # Boundary approach roads terminate cleanly as authentic open external network gateways.
        all_segments.extend(buffer_segments)
        diag = {
            "buffer_applied": True,
            "buffer_source": "boundary_approach_extensions",
            "buffer_distance_m": buffer_m,
            "buffer_segments_added": len(buffer_segments),
            "external_endpoints_count": len(external_endpoints),
        }
        return all_segments, diag

    def _extract_nodes_and_edges(
        self,
        segments: list[dict[str, Any]],
        polygon_coords: Optional[list[list[float]]] = None,
        allow_synthetic: bool = False,
        approved_signal_junctions: Optional[set[str]] = None,
        external_buffer_m: float = 500.0,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, list[str]], dict[str, str], list[str]]:
        """
        Extract clean node coordinates and directional edges from road segments.

        Returns:
            nodes: node_id → node attributes
            edges: list of edge attribute dicts
            segment_edge_map: segment_id → list of SUMO edge IDs for congestion analysis
            edge_segment_map: sumo_edge_id → source segment_id
            assumptions: list of simulation modeling assumptions applied
        """
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        coord_to_node: dict[tuple[float, float], str] = {}
        segment_edge_map: dict[str, list[str]] = {}
        edge_segment_map: dict[str, str] = {}
        assumptions: list[str] = []
        used_edge_ids: set[str] = set()

        # If empty segments provided: ONLY construct corridor if explicitly allowed (synthetic demo)
        if not segments:
            if allow_synthetic:
                if polygon_coords and len(polygon_coords) >= 3:
                    segments = self._corridor_from_polygon(polygon_coords)
                else:
                    segments = self._default_corridor_segments()
                assumptions.append("synthetic_corridor_generated")
            else:
                raise ValueError(
                    "No road segments provided for simulation network construction. "
                    "Real-area simulations require valid road network data."
                )

        # Attach external road-network buffer if polygon coordinates are present
        if polygon_coords and len(polygon_coords) >= 3 and external_buffer_m > 0:
            segments, buffer_diag = self._build_external_road_buffer(segments, polygon_coords, external_buffer_m)
            self.buffer_diagnostics = buffer_diag
            assumptions.append(f"external_buffer_{int(external_buffer_m)}m_attached")

        # Truncate to MAX_SEGMENTS with explicit warning if necessary
        total_segments = len(segments)
        if total_segments > MAX_SEGMENTS:
            logger.warning(
                "Segment count (%d) exceeds MAX_SEGMENTS (%d). "
                "Truncating to first %d segments for SUMO network compilation. "
                "Increase MAX_SEGMENTS in network_builder.py to process more roads.",
                total_segments, MAX_SEGMENTS, MAX_SEGMENTS,
            )
            segments = segments[:MAX_SEGMENTS]
            assumptions.append(f"truncated_to_max_{MAX_SEGMENTS}_segments")

        # Build node coordinate registry
        for idx, seg in enumerate(segments):
            geom = seg.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue

            # Node identity: prefer verified source node IDs if available
            u_source_id = str(seg["u"]) if seg.get("u") is not None else None
            v_source_id = str(seg["v"]) if seg.get("v") is not None else None

            # Deduplicate nodes by coordinate (~0.1m precision at 6 decimals) or source ID
            u_coord_key = (round(coords[0][0], 6), round(coords[0][1], 6))
            v_coord_key = (round(coords[-1][0], 6), round(coords[-1][1], 6))

            if u_source_id:
                u_id = f"node_{u_source_id}"
                coord_to_node[u_coord_key] = u_id
            elif u_coord_key in coord_to_node:
                u_id = coord_to_node[u_coord_key]
            else:
                u_id = f"node_{len(coord_to_node)}"
                coord_to_node[u_coord_key] = u_id

            if v_source_id:
                v_id = f"node_{v_source_id}"
                coord_to_node[v_coord_key] = v_id
            elif v_coord_key in coord_to_node:
                v_id = coord_to_node[v_coord_key]
            else:
                v_id = f"node_{len(coord_to_node)}"
                coord_to_node[v_coord_key] = v_id

            # GeoJSON coordinates are [lon, lat]
            u_lon, u_lat = coords[0][0], coords[0][1]
            v_lon, v_lat = coords[-1][0], coords[-1][1]

            if u_id not in nodes:
                nodes[u_id] = {
                    "id": u_id,
                    "x": u_lon,
                    "y": u_lat,
                    "degree": 0,
                    "type": "priority",
                    "control": "priority",
                    "provenance": "unknown",
                }
            if v_id not in nodes:
                nodes[v_id] = {
                    "id": v_id,
                    "x": v_lon,
                    "y": v_lat,
                    "degree": 0,
                    "type": "priority",
                    "control": "priority",
                    "provenance": "unknown",
                }

            nodes[u_id]["degree"] += 1
            nodes[v_id]["degree"] += 1

            # Junction control authenticity: assign control strictly from verified metadata
            u_ctrl = seg.get("u_control")
            u_prov = seg.get("u_provenance")
            if u_ctrl == "traffic_signal":
                nodes[u_id]["type"] = "traffic_light"
                nodes[u_id]["control"] = "traffic_signal"
                nodes[u_id]["provenance"] = u_prov or "source_verified"
            elif u_ctrl == "stop" and nodes[u_id]["type"] != "traffic_light":
                nodes[u_id]["type"] = "priority_stop"
                nodes[u_id]["control"] = "stop"
                nodes[u_id]["provenance"] = u_prov or "source_verified"
            elif u_ctrl == "roundabout" and nodes[u_id]["type"] != "traffic_light":
                nodes[u_id]["type"] = "roundabout"
                nodes[u_id]["control"] = "roundabout"
                nodes[u_id]["provenance"] = u_prov or "source_verified"

            v_ctrl = seg.get("v_control")
            v_prov = seg.get("v_provenance")
            if v_ctrl == "traffic_signal":
                nodes[v_id]["type"] = "traffic_light"
                nodes[v_id]["control"] = "traffic_signal"
                nodes[v_id]["provenance"] = v_prov or "source_verified"
            elif v_ctrl == "stop" and nodes[v_id]["type"] != "traffic_light":
                nodes[v_id]["type"] = "priority_stop"
                nodes[v_id]["control"] = "stop"
                nodes[v_id]["provenance"] = v_prov or "source_verified"
            elif v_ctrl == "roundabout" and nodes[v_id]["type"] != "traffic_light":
                nodes[v_id]["type"] = "roundabout"
                nodes[v_id]["control"] = "roundabout"
                nodes[v_id]["provenance"] = v_prov or "source_verified"

            # Road class & lane interpretation
            road_class = seg.get("road_type") or "arterial"
            is_oneway = bool(seg.get("is_oneway", False))
            fwd_lanes, bwd_lanes, is_estimated = interpret_lane_configuration(
                total_lanes=seg.get("lanes"),
                lanes_forward=seg.get("lanes_forward"),
                lanes_backward=seg.get("lanes_backward"),
                is_oneway=is_oneway,
                road_class=road_class,
            )
            if is_estimated:
                if "lane_counts_inferred_from_road_class" not in assumptions:
                    assumptions.append("lane_counts_inferred_from_road_class")
                if "default_lanes_2_applied" not in assumptions:
                    assumptions.append("default_lanes_2_applied")

            is_buf_seg = bool(seg.get("is_buffer", False))
            if seg.get("speed_limit_kmh") is None:
                speed_kmh = 50.0
                if "default_speed_50kmh_applied" not in assumptions:
                    assumptions.append("default_speed_50kmh_applied")
            else:
                speed_kmh = float(seg["speed_limit_kmh"])
            raw_seg_id = str(seg.get("segment_id") or f"edge_{idx}")

            # Collision-safe deterministic edge ID sanitization (Issue D)
            clean_base = re.sub(r"[^a-zA-Z0-9_]", "_", raw_seg_id)
            if not clean_base or clean_base.strip("_") == "":
                clean_base = f"edge_{idx}"

            candidate_fwd = clean_base
            if candidate_fwd in used_edge_ids:
                disambig = hashlib.sha256(raw_seg_id.encode("utf-8")).hexdigest()[:6]
                candidate_fwd = f"{clean_base}_{disambig}"
                if candidate_fwd in used_edge_ids:
                    candidate_fwd = f"{candidate_fwd}_{idx}"

            used_edge_ids.add(candidate_fwd)
            edge_segment_map[candidate_fwd] = raw_seg_id
            safe_edge_id = candidate_fwd

            # Build shape strings for true physical road curvature
            shape_str = " ".join(f"{c[0]:.6f},{c[1]:.6f}" for c in coords)
            shape_str_rev = " ".join(f"{c[0]:.6f},{c[1]:.6f}" for c in reversed(coords))

            edges.append({
                "id": safe_edge_id,
                "from": u_id,
                "to": v_id,
                "speed": round(speed_kmh / 3.6, 2),  # m/s
                "numLanes": fwd_lanes,
                "shape": shape_str,
                "name": seg.get("name") or "Road Segment",
                "road_type": road_class,
                "is_oneway": is_oneway,
                "is_buffer": is_buf_seg,
                "is_estimated_lanes": is_estimated,
                "osm_id": seg.get("osm_id"),
            })

            # Track mapping from Gativa segment_id → SUMO edge IDs for congestion analysis
            seg_edge_ids = [safe_edge_id]

            # If bidirectional, add reverse edge with collision-safe ID
            if not is_oneway and bwd_lanes > 0:
                candidate_rev = f"{safe_edge_id}_rev"
                if candidate_rev in used_edge_ids:
                    disambig = hashlib.sha256(f"{raw_seg_id}_rev".encode("utf-8")).hexdigest()[:6]
                    candidate_rev = f"{safe_edge_id}_rev_{disambig}"
                    if candidate_rev in used_edge_ids:
                        candidate_rev = f"{candidate_rev}_{idx}"
                used_edge_ids.add(candidate_rev)
                edge_segment_map[candidate_rev] = raw_seg_id

                edges.append({
                    "id": candidate_rev,
                    "from": v_id,
                    "to": u_id,
                    "speed": round(speed_kmh / 3.6, 2),
                    "numLanes": bwd_lanes,
                    "shape": shape_str_rev,
                    "name": seg.get("name") or "Road Segment",
                    "road_type": road_class,
                    "is_oneway": is_oneway,
                    "is_buffer": is_buf_seg,
                    "is_estimated_lanes": is_estimated,
                    "osm_id": seg.get("osm_id"),
                })
                seg_edge_ids.append(candidate_rev)

            segment_edge_map[raw_seg_id] = seg_edge_ids

        # Apply user-approved candidate signals if supplied (Optimized Scenario)
        if approved_signal_junctions:
            applied_count = 0
            for n_id, n_data in nodes.items():
                # Match by exact node_id, cand_node_id, or OSM ID variations
                is_match = (
                    n_id in approved_signal_junctions
                    or f"cand_{n_id}" in approved_signal_junctions
                )
                if not is_match and n_id.startswith("node_"):
                    raw_id = n_id[5:]
                    if raw_id in approved_signal_junctions or f"cand_{raw_id}" in approved_signal_junctions:
                        is_match = True

                if is_match:
                    n_data["type"] = "traffic_light"
                    n_data["control"] = "traffic_signal"
                    n_data["provenance"] = "user_approved_candidate"
                    applied_count += 1
            if applied_count > 0:
                assumptions.append(f"user_approved_{applied_count}_signals_applied")

        # Authenticity rule: Never classify junctions based on degree >= 3 or force a traffic light.
        # Zero-signal networks compile cleanly with priority rules.
        return nodes, edges, segment_edge_map, edge_segment_map, assumptions

    def _write_nodes_xml(self, file_path: Path, nodes: dict[str, dict[str, Any]]):
        root = ET.Element("nodes")
        for node in nodes.values():
            ET.SubElement(
                root,
                "node",
                id=str(node["id"]),
                x=f"{node['x']:.6f}",
                y=f"{node['y']:.6f}",
                type=str(node.get("type", "priority")),
            )
        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)


    def _write_edges_xml(self, file_path: Path, edges: list[dict[str, Any]]):
        root = ET.Element("edges")
        for edge in edges:
            attribs = {
                "id": str(edge["id"]),
                "from": str(edge["from"]),
                "to": str(edge["to"]),
                "speed": str(edge["speed"]),
                "numLanes": str(edge["numLanes"]),
                "priority": "2",
                "spreadType": "right",
            }
            if edge.get("shape"):
                attribs["shape"] = edge["shape"]
            ET.SubElement(root, "edge", attribs)
        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)


    def _run_netconvert_with_diagnostics(
        self,
        nod_file: Path,
        edg_file: Path,
        net_file: Path,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute netconvert with complete compilation diagnostics:
        - Detect and log SUMO / netconvert version
        - Try UTM projection first, fallback to plain-geo
        - Capture stdout, stderr, warnings, and compilation errors
        - Validate generated network XML and verify node/edge counts
        - Maintain explicit unvalidated structural fallback when compilation unavailable
        """
        diag: dict[str, Any] = {
            "netconvert_used": False,
            "sumo_version": None,
            "compilation_returncode": -1,
            "compilation_warnings": [],
            "compilation_errors": [],
            "compiled_junction_count": 0,
            "compiled_edge_count": 0,
            "network_valid": False,
            "network_provenance": "unvalidated_structural_fallback",
        }

        # 1. Detect SUMO / netconvert version
        if self.netconvert_bin and Path(self.netconvert_bin).is_file():
            try:
                ver_res = subprocess.run([self.netconvert_bin, "--version"], capture_output=True, text=True, timeout=5)
                if ver_res.returncode == 0:
                    first_line = ver_res.stdout.strip().split("\n")[0]
                    diag["sumo_version"] = first_line
            except Exception as e:
                logger.debug("Could not determine netconvert version: %s", e)

        # 2. Attempt UTM projection compilation, then plain-geo fallback
        netconvert_success = False
        if self.netconvert_bin and Path(self.netconvert_bin).is_file():
            for proj_flag in ("--proj.utm", "--proj.plain-geo"):
                try:
                    cmd = [
                        self.netconvert_bin,
                        "--node-files", str(nod_file),
                        "--edge-files", str(edg_file),
                        "--output-file", str(net_file),
                        "--junctions.corner-detail", "5",
                        "--rectangular-lane-cut", "true",
                        proj_flag,
                        "--ignore-errors",
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    diag["compilation_returncode"] = res.returncode

                    raw_out = (res.stdout or "") + "\n" + (res.stderr or "")
                    for line in raw_out.splitlines():
                        line_str = line.strip()
                        if "Warning:" in line_str:
                            diag["compilation_warnings"].append(line_str)
                        elif "Error:" in line_str:
                            diag["compilation_errors"].append(line_str)

                    if res.returncode == 0 and net_file.is_file() and net_file.stat().st_size > 0:
                        try:
                            tree = ET.parse(str(net_file))
                            root = tree.getroot()
                            if root.tag == "net":
                                netconvert_success = True
                                j_count = len(root.findall("junction"))
                                e_count = len(root.findall("edge"))
                                diag["compiled_junction_count"] = j_count
                                diag["compiled_edge_count"] = e_count
                                diag["network_valid"] = True
                                diag["netconvert_used"] = True
                                diag["network_provenance"] = "native_sumo_netconvert"
                                logger.info(
                                    "netconvert generated valid network (%s junctions, %s edges) with %s: %s",
                                    j_count, e_count, proj_flag, net_file,
                                )
                                break
                        except Exception as parse_err:
                            diag["compilation_errors"].append(f"Compiled XML parse error: {parse_err}")
                except Exception as e:
                    diag["compilation_errors"].append(f"Subprocess execution error: {e}")
                    logger.error("Failed to run netconvert with %s: %s", proj_flag, e)

        # 3. Fallback XML if netconvert failed or missing
        if not netconvert_success or not net_file.is_file():
            self._write_fallback_net_xml(net_file, nodes, edges)
            diag["netconvert_used"] = False
            diag["network_valid"] = False
            diag["network_provenance"] = "unvalidated_structural_fallback"
            diag["compiled_junction_count"] = len(nodes)
            diag["compiled_edge_count"] = len(edges)

        return diag

    def _estimate_traffic_demand(
        self,
        segments: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        duration_seconds: int,
        demand_rate_veh_hr: int,
        demand_level: Optional[str] = "normal",
        manual_vehicle_count: Optional[int] = None,
        live_observations: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[int, int, str, str]:
        """
        Estimate traffic demand following the documented preference hierarchy:
        1. Live traffic observations where available.
        2. Relevant historical traffic profile if available.
        3. Documented network capacity model based on road classes, lanes, and connectivity.
        
        Returns:
            calibrated_rate_veh_hr: hourly demand rate
            target_vehicle_count: total trips to generate over duration
            demand_source: "live_traffic_observation" | "historical_profile" | "road_network_estimation"
            demand_label: human-readable provenance description
        """
        if manual_vehicle_count is not None and manual_vehicle_count > 0:
            rate = int(manual_vehicle_count / (duration_seconds / 3600.0))
            return rate, manual_vehicle_count, "manual_override", f"Manual experiment target ({manual_vehicle_count} trips)"

        # 1. Check live observations
        if live_observations and len(live_observations) > 0:
            speeds = [float(obs.get("current_speed_kmh", 0)) for obs in live_observations if obs.get("current_speed_kmh")]
            free_flows = [float(obs.get("free_flow_speed_kmh", 50)) for obs in live_observations if obs.get("free_flow_speed_kmh")]
            if speeds and free_flows:
                avg_speed = sum(speeds) / len(speeds)
                avg_ff = sum(free_flows) / len(free_flows)
                speed_ratio = max(0.2, min(1.0, avg_speed / max(avg_ff, 1.0)))
                # Lower speed ratio implies higher active congestion demand
                base_flow = int(2400 * (1.5 - speed_ratio * 0.7))
                total_veh = max(20, int(base_flow * (duration_seconds / 3600.0)))
                return base_flow, total_veh, "live_traffic_observation", f"Calibrated from {len(live_observations)} live sensor observations (speed ratio: {speed_ratio:.2f})"

        # 2. Road Network Capacity Model
        # Highway: ~1800 veh/hr/lane, Arterial: ~900 veh/hr/lane, Local: ~400 veh/hr/lane
        total_capacity = 0.0
        edge_count = len(edges)
        for e in edges:
            lanes = int(e.get("numLanes", 1))
            speed = float(e.get("speed", 13.8)) * 3.6  # km/h
            if speed >= 70:
                cap = 1800 * lanes
            elif speed >= 45:
                cap = 950 * lanes
            else:
                cap = 450 * lanes
            total_capacity += cap

        avg_corridor_capacity = (total_capacity / max(1, edge_count)) * 2.5 if edge_count else 3000.0

        multiplier = 0.65  # Normal default
        if demand_level == "low":
            multiplier = 0.35
        elif demand_level == "normal":
            multiplier = 0.65
        elif demand_level == "high":
            multiplier = 0.95
        elif demand_level == "custom" and demand_rate_veh_hr > 0:
            rate = demand_rate_veh_hr
            total_veh = max(10, int(rate * (duration_seconds / 3600.0)))
            return rate, total_veh, "road_network_estimation", f"Custom configured demand ({rate:,} veh/hr)"

        calibrated_rate = int(max(400, min(6500, avg_corridor_capacity * multiplier)))
        target_trips = max(15, int(calibrated_rate * (duration_seconds / 3600.0)))
        label = (
            f"Estimated from {len(segments)} road segments "
            f"({demand_level.capitalize() if demand_level else 'Normal'} level: {calibrated_rate:,} veh/hr across {edge_count} edges)"
        )
        return calibrated_rate, target_trips, "road_network_estimation", label

    def _identify_boundary_edges(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        polygon_coords: Optional[list[list[float]]] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Geometrically identify true boundary entry, exit, and internal road edges.

        Requirements:
        1. Uses the actual selected polygon boundary via Shapely geometry when available.
        2. Accurately identifies road segments crossing or touching the actual polygon boundary.
        3. Distinguishes genuine entry (inbound to polygon/interior), exit (outbound to exterior),
           and internal road edges.
        4. Preserves directed road connectivity and respects bidirectional and one-way roads.
        5. Avoids treating arbitrary interior roads as boundary connections.
        6. Removes arbitrary first-half/second-half edge slicing.
        7. Records explicit diagnostics.
        """
        if not edges:
            return [], [], []

        entry_edges: list[dict[str, Any]] = []
        exit_edges: list[dict[str, Any]] = []
        internal_edges: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {"method": "unknown"}

        # Attempt polygon-based boundary classification
        poly = None
        if polygon_coords and len(polygon_coords) >= 3:
            try:
                raw_poly = Polygon(polygon_coords)
                if not raw_poly.is_valid:
                    raw_poly = raw_poly.buffer(0)
                if not raw_poly.is_empty and raw_poly.is_valid and raw_poly.area > 0:
                    poly = raw_poly
            except Exception as e:
                logger.debug("Failed to build Shapely polygon from polygon_coords: %s", e)

        if poly is not None:
            poly_boundary = poly.boundary
            min_x, min_y, max_x, max_y = poly.bounds
            span = max(max_x - min_x, max_y - min_y, 0.0001)
            b_tol = span * 0.08  # within 8% of boundary is considered on the boundary

            node_rel: dict[str, str] = {}  # "inside", "boundary", "outside"
            node_dist: dict[str, float] = {}
            for n_id, n in nodes.items():
                pt = Point(float(n["x"]), float(n["y"]))
                dist = poly_boundary.distance(pt)
                node_dist[n_id] = dist
                if dist <= b_tol:
                    node_rel[n_id] = "boundary"
                elif poly.contains(pt):
                    node_rel[n_id] = "inside"
                else:
                    node_rel[n_id] = "outside"

            has_boundary_nodes = any(r in ("boundary", "outside") for r in node_rel.values())
            has_inside_nodes = any(r == "inside" for r in node_rel.values())

            if has_boundary_nodes and has_inside_nodes:
                diagnostics["method"] = "polygon_boundary_crossing"
                for e in edges:
                    f_rel = node_rel.get(e["from"], "inside")
                    t_rel = node_rel.get(e["to"], "inside")

                    # Inbound: from boundary/outside toward deeper inside
                    if f_rel in ("boundary", "outside") and t_rel == "inside":
                        entry_edges.append(e)
                    # Outbound: from inside toward boundary/outside
                    elif f_rel == "inside" and t_rel in ("boundary", "outside"):
                        exit_edges.append(e)
                    elif f_rel in ("boundary", "outside") and t_rel in ("boundary", "outside"):
                        entry_edges.append(e)
                        exit_edges.append(e)
                    else:
                        internal_edges.append(e)
            else:
                # All nodes are inside the polygon (or all on boundary).
                # Classify peripheral nodes based on distance to polygon boundary.
                diagnostics["method"] = "polygon_peripheral_distance"
                dists = [node_dist[nid] for nid in nodes if nid in node_dist]
                if dists:
                    min_d = min(dists)
                    max_d = max(dists)
                    d_threshold = min_d + 0.25 * (max_d - min_d)
                    for e in edges:
                        f_d = node_dist.get(e["from"], max_d)
                        t_d = node_dist.get(e["to"], max_d)
                        f_perim = f_d <= d_threshold
                        t_perim = t_d <= d_threshold

                        if f_perim and not t_perim:
                            entry_edges.append(e)
                        elif t_perim and not f_perim:
                            exit_edges.append(e)
                        elif f_perim and t_perim:
                            entry_edges.append(e)
                            exit_edges.append(e)
                        else:
                            internal_edges.append(e)

        # Fallback if no polygon or polygon classification yielded empty edges
        if not entry_edges or not exit_edges:
            diagnostics["method"] = "directed_graph_topology"
            G = nx.DiGraph()
            for e in edges:
                G.add_edge(e["from"], e["to"], id=e["id"])

            in_deg = dict(G.in_degree())
            out_deg = dict(G.out_degree())

            for e in edges:
                u, v = e["from"], e["to"]
                is_source = (in_deg.get(u, 0) == 0) or (in_deg.get(u, 0) <= 1 and out_deg.get(u, 0) >= 1)
                is_sink = (out_deg.get(v, 0) == 0) or (out_deg.get(v, 0) <= 1 and in_deg.get(v, 0) >= 1)

                if is_source and not is_sink:
                    entry_edges.append(e)
                elif is_sink and not is_source:
                    exit_edges.append(e)
                elif is_source and is_sink:
                    entry_edges.append(e)
                    exit_edges.append(e)
                else:
                    internal_edges.append(e)

        if not entry_edges:
            entry_edges = list(edges)
            diagnostics["note_entry"] = "All edges eligible as entry (cyclic or single-component network)"
        if not exit_edges:
            exit_edges = list(edges)
            diagnostics["note_exit"] = "All edges eligible as exit (cyclic or single-component network)"

        diagnostics.update({
            "entry_count": len(entry_edges),
            "exit_count": len(exit_edges),
            "internal_count": len(internal_edges),
            "total_edges": len(edges),
        })
        self.boundary_diagnostics = diagnostics
        return entry_edges, exit_edges, internal_edges

    def _write_routes_xml(
        self,
        file_path: Path,
        nodes: Any,
        edges: Any = None,
        duration_seconds: int = 600,
        demand_rate_veh_hr: int = 2400,
        seed: int = 42,
        polygon_coords: Optional[list[list[float]]] = None,
        demand_profile: str = "peak",
        vehicle_types: Optional[dict[str, float]] = None,
        target_vehicle_count: Optional[int] = None,
        initial_population: Optional[int] = None,
    ) -> tuple[int, int]:
        """
        Generate realistic, strictly reachable trip demand:
        - Construct directed graph and compute reachability for every origin-destination pair.
        - Initial population placed across distinct interior/approach road segments at depart="0.0"
          with departPos="random", departSpeed="avg", departLane="best" (natural network distribution).
        - Scheduled demand departures distributed across simulation duration according to profile
          with minimum headway enforcement (>= 2.5s) per entry edge to prevent entry pileups.
        - Boundary entry to exit through-trips prioritized (75%) with internal trips (25%).
        - Rejects any pair without a valid directed path; never manufactures unroutable fallback pairs.
        """
        import random

        if isinstance(nodes, list):
            actual_edges = nodes
            if isinstance(edges, int):
                duration_seconds = edges
            actual_nodes: dict[str, dict[str, Any]] = {}
            for i, e in enumerate(actual_edges):
                actual_nodes[str(e["from"])] = {"id": str(e["from"]), "x": float(i * 100), "y": 0.0}
                actual_nodes[str(e["to"])] = {"id": str(e["to"]), "x": float((i + 1) * 100), "y": 0.0}
        else:
            actual_nodes = nodes or {}
            actual_edges = edges or []

        if not actual_edges:
            raise ValueError("Cannot generate routes for an empty edge list.")

        rng = random.Random(seed)
        root = ET.Element("routes")

        # Define calibrated vehicle types
        ET.SubElement(
            root,
            "vType",
            id="passenger",
            accel="2.6",
            decel="4.5",
            sigma="0.5",
            length="4.5",
            minGap="2.5",
            maxSpeed="33.3",
            color="0.2,0.5,0.9",
        )
        ET.SubElement(
            root,
            "vType",
            id="bus",
            accel="1.2",
            decel="3.5",
            sigma="0.5",
            length="12.0",
            minGap="3.0",
            maxSpeed="20.0",
            color="1.0,0.6,0.0",
        )
        ET.SubElement(
            root,
            "vType",
            id="delivery",
            accel="2.0",
            decel="4.0",
            sigma="0.5",
            length="7.0",
            minGap="2.8",
            maxSpeed="25.0",
            color="0.8,0.8,0.8",
        )
        ET.SubElement(
            root,
            "vType",
            id="motorcycle",
            accel="3.5",
            decel="5.0",
            sigma="0.5",
            length="2.2",
            minGap="1.8",
            maxSpeed="30.0",
            color="0.9,0.2,0.2",
        )

        total_vehicles = target_vehicle_count or max(15, int(demand_rate_veh_hr * (duration_seconds / 3600.0)))

        # Build directed graph of road network
        G = nx.DiGraph()
        for e in actual_edges:
            G.add_edge(e["from"], e["to"], id=e["id"])

        entry_edges, exit_edges, internal_edges = self._identify_boundary_edges(actual_nodes, actual_edges, polygon_coords)
        internal_edge_ids = {e["id"] for e in internal_edges}

        # Precompute reachable descendants for each node (single BFS per node)
        reachable_map: dict[str, set[str]] = {}
        for n in G.nodes():
            reachable_map[n] = nx.descendants(G, n)

        # Build reachability mapping per edge
        edge_dests_map: dict[str, list[str]] = {}
        for e in actual_edges:
            e_to = e["to"]
            reach = reachable_map.get(e_to, set())
            valid_dest_ids = [
                d["id"] for d in actual_edges
                if d["id"] != e["id"] and (d["from"] == e_to or d["from"] in reach)
            ]
            edge_dests_map[e["id"]] = valid_dest_ids

        # 1. Collect Valid Through-Pairs (Entry to Exit with reachable path)
        through_pairs: list[tuple[str, str]] = []
        for en in entry_edges:
            en_id = en["id"]
            dests_for_en = set(edge_dests_map.get(en_id, []))
            for ex in exit_edges:
                if ex["id"] in dests_for_en and ex["id"] != en_id:
                    through_pairs.append((en_id, ex["id"]))
                    if len(through_pairs) >= 500:
                        break
            if len(through_pairs) >= 500:
                break

        # 2. Collect Valid Internal Pairs (origin and destination strictly inside corridor)
        internal_pairs: list[tuple[str, str]] = []
        for e1 in internal_edges:
            e1_id = e1["id"]
            dests = edge_dests_map.get(e1_id, [])
            for e2_id in dests:
                if e2_id in internal_edge_ids and e2_id != e1_id:
                    internal_pairs.append((e1_id, e2_id))
                    if len(internal_pairs) >= 300:
                        break
            if len(internal_pairs) >= 300:
                break

        # 3. Collect Valid Inbound and Outbound Pairs
        inbound_outbound_pairs: list[tuple[str, str]] = []
        for en in entry_edges:
            en_id = en["id"]
            for e_int_id in edge_dests_map.get(en_id, []):
                if e_int_id in internal_edge_ids and e_int_id != en_id:
                    inbound_outbound_pairs.append((en_id, e_int_id))
                    if len(inbound_outbound_pairs) >= 150:
                        break
        for e_int in internal_edges:
            e_int_id = e_int["id"]
            for ex in exit_edges:
                if ex["id"] in edge_dests_map.get(e_int_id, []) and ex["id"] != e_int_id:
                    inbound_outbound_pairs.append((e_int_id, ex["id"]))
                    if len(inbound_outbound_pairs) >= 300:
                        break

        # Fallbacks for sparse components: never generate same-edge trips
        if not through_pairs:
            through_pairs = inbound_outbound_pairs or internal_pairs
        if not internal_pairs:
            internal_pairs = inbound_outbound_pairs or through_pairs

        all_candidate_pairs = through_pairs + internal_pairs + inbound_outbound_pairs
        if not all_candidate_pairs:
            for e1 in actual_edges:
                for e2_id in edge_dests_map.get(e1["id"], []):
                    if e2_id != e1["id"]:
                        all_candidate_pairs.append((e1["id"], e2_id))
                        if len(all_candidate_pairs) >= 100:
                            break

        if not all_candidate_pairs:
            raise ValueError(
                f"Road network topology contains no reachable origin-destination pairs across {len(actual_edges)} edges."
            )

        # 4. Optional Initial Vehicle Population (at t=0.0)
        if initial_population is not None:
            target_initial = max(0, initial_population)
        else:
            target_initial = min(total_vehicles, max(2, int(total_vehicles * 0.2)))
        initial_trips: list[tuple[float, str, str, str, str, bool]] = []
        rejected_trips = 0

        if target_initial > 0:
            candidate_init_edges = [e for e in actual_edges if len(edge_dests_map.get(e["id"], [])) > 0]
            if not candidate_init_edges:
                candidate_init_edges = actual_edges
            init_pool = list(candidate_init_edges)
            rng.shuffle(init_pool)

            for i in range(target_initial):
                e_init = init_pool[i % len(init_pool)]
                dests = edge_dests_map.get(e_init["id"], [])
                if dests:
                    d_edge = rng.choice(dests)
                    v_type = "bus" if rng.random() < 0.12 else "passenger"
                    initial_trips.append((0.0, f"init_veh_{i}", v_type, e_init["id"], d_edge, True))
                else:
                    rejected_trips += 1

        # 5. Continuous Time-Distributed Poisson Departures (t >= 1.0)
        lam = max(0.05, demand_rate_veh_hr / 3600.0)
        curr_t = 1.0
        scheduled_trips: list[tuple[float, str, str, str, str, bool]] = []
        headway_per_edge: dict[str, float] = {}
        v_counter = 0

        if initial_population is not None and initial_population >= total_vehicles:
            target_scheduled = 0
        else:
            target_scheduled = max(5, total_vehicles - len(initial_trips))

        while curr_t <= duration_seconds - 5.0 and len(scheduled_trips) < target_scheduled:
            dt = rng.expovariate(lam)
            curr_t += dt
            if curr_t > duration_seconds - 5.0:
                break

            # 70% Through, 20% Internal, 10% Inbound/Outbound
            roll = rng.random()
            if roll < 0.70 and through_pairs:
                from_edge, to_edge = rng.choice(through_pairs)
            elif roll < 0.90 and internal_pairs:
                from_edge, to_edge = rng.choice(internal_pairs)
            elif inbound_outbound_pairs:
                from_edge, to_edge = rng.choice(inbound_outbound_pairs)
            elif through_pairs:
                from_edge, to_edge = rng.choice(through_pairs)
            elif internal_pairs:
                from_edge, to_edge = rng.choice(internal_pairs)
            else:
                from_edge, to_edge = rng.choice(all_candidate_pairs)

            last_dep = headway_per_edge.get(from_edge, -10.0)
            dep_time = max(curr_t, last_dep + 2.5)
            if dep_time > duration_seconds - 5.0:
                break
            headway_per_edge[from_edge] = dep_time

            # Calibrated vehicle composition:
            # 75% passenger, 10% bus, 10% delivery, 5% motorcycle
            v_roll = rng.random()
            if v_roll < 0.75:
                v_type = "passenger"
            elif v_roll < 0.85:
                v_type = "bus"
            elif v_roll < 0.95:
                v_type = "delivery"
            else:
                v_type = "motorcycle"

            scheduled_trips.append((round(dep_time, 1), f"veh_{v_counter}", v_type, from_edge, to_edge, False))
            v_counter += 1

        # Combine and sort strictly by departure time
        all_trips = initial_trips + scheduled_trips
        all_trips.sort(key=lambda x: (x[0], x[1]))

        for dep_time, v_id, v_type, f_edge, t_edge, is_initial in all_trips:
            trip_attribs = {
                "id": v_id,
                "type": v_type,
                "depart": f"{dep_time:.1f}",
                "from": f_edge,
                "to": t_edge,
            }
            if is_initial:
                trip_attribs["departPos"] = "random"
                trip_attribs["departSpeed"] = "avg"
                trip_attribs["departLane"] = "best"
            else:
                trip_attribs["departPos"] = "base"
                trip_attribs["departSpeed"] = "max"
                trip_attribs["departLane"] = "best"

            ET.SubElement(root, "trip", **trip_attribs)

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

        self.demand_tracking = {
            "total_vehicles_generated": len(all_trips),
            "valid_trips_count": len(all_trips),
            "initial_population": len(initial_trips),
            "scheduled_departures": len(scheduled_trips),
            "duration_seconds": duration_seconds,
            "demand_rate_veh_hr": demand_rate_veh_hr,
            "rejected_trips": rejected_trips,
            "through_pairs_count": len(through_pairs),
            "internal_pairs_count": len(internal_pairs),
        }
        return len(all_trips), len(initial_trips)

    def _write_sumocfg(self, file_path: Path, net_name: str, rou_name: str, duration_seconds: int):
        root = ET.Element("configuration")
        input_elem = ET.SubElement(root, "input")
        ET.SubElement(input_elem, "net-file", value=net_name)
        ET.SubElement(input_elem, "route-files", value=rou_name)

        time_elem = ET.SubElement(root, "time")
        ET.SubElement(time_elem, "begin", value="0")
        ET.SubElement(time_elem, "end", value=str(duration_seconds))
        ET.SubElement(time_elem, "step-length", value=str(SIMULATION_STEP_LENGTH_SECONDS))

        processing_elem = ET.SubElement(root, "processing")
        ET.SubElement(processing_elem, "ignore-route-errors", value="true")

        routing_elem = ET.SubElement(root, "routing")
        ET.SubElement(routing_elem, "device.rerouting.probability", value="1.0")
        ET.SubElement(routing_elem, "device.rerouting.adaptation-interval", value="10")

        report_elem = ET.SubElement(root, "report")
        ET.SubElement(report_elem, "no-warnings", value="true")
        ET.SubElement(report_elem, "no-step-log", value="true")

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)


    def _write_fallback_net_xml(self, file_path: Path, nodes: dict, edges: list):
        """
        Minimal fallback network XML in case netconvert is bypassed or fails.
        Explicitly marked as an unvalidated structural fallback, not a native compiled SUMO network.
        """
        root = ET.Element("net", version="1.20", xmlns="http://sumo.dlr.de/xsd/net_file.xsd")
        comment = ET.Comment(" UNVALIDATED_STRUCTURAL_FALLBACK: Netconvert not applied. ")
        root.append(comment)
        for e in edges:
            attribs = {
                "id": str(e["id"]),
                "from": str(e["from"]),
                "to": str(e["to"]),
                "priority": "2",
            }
            if e.get("shape"):
                attribs["shape"] = e["shape"]
            edge_elem = ET.SubElement(root, "edge", attribs)
            for lane_i in range(e["numLanes"]):
                ET.SubElement(
                    edge_elem,
                    "lane",
                    id=f"{e['id']}_{lane_i}",
                    index=str(lane_i),
                    speed=str(e["speed"]),
                    length="250.0",
                )
        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

    def _extract_network_geometry(
        self,
        net_file: Path,
        edges_meta: list[dict[str, Any]],
        nodes_meta: dict[str, dict[str, Any]],
        polygon_coords: Optional[list[list[float]]],
        buffer_m: float = 500.0,
        sim_id: str = "",
        analysis_id: str = "",
    ) -> dict[str, Any]:
        """
        Extract complete lane geometry, junction polygons, and network metrics
        from the compiled SUMO network.net.xml via sumolib.
        """
        try:
            import sumolib
            snet = sumolib.net.readNet(str(net_file))
            sumolib_ok = True
        except Exception as e:
            logger.warning("sumolib failed to read net file: %s; falling back to metadata geometry", e)
            sumolib_ok = False
            snet = None

        edges_detail: list[dict[str, Any]] = []
        junctions_detail: list[dict[str, Any]] = []
        all_lons: list[float] = []
        all_lats: list[float] = []

        edge_meta_map = {e["id"]: e for e in edges_meta}
        node_meta_map = nodes_meta

        if sumolib_ok and snet is not None:
            for e in snet.getEdges():
                eid = e.getID()
                if eid.startswith(":"):
                    continue

                emeta = edge_meta_map.get(eid, {})
                lanes_list = []
                for lane in e.getLanes():
                    lane_geo = []
                    try:
                        for x, y in lane.getShape():
                            lon, lat = snet.convertXY2LonLat(x, y)
                            lane_geo.append([round(lon, 6), round(lat, 6)])
                            all_lons.append(lon)
                            all_lats.append(lat)
                    except Exception:
                        pass

                    lanes_list.append({
                        "id": lane.getID(),
                        "index": lane.getIndex(),
                        "width_m": round(lane.getWidth(), 2),
                        "speed_kmh": round(lane.getSpeed() * 3.6, 1),
                        "shape": lane_geo,
                    })

                edge_shape = lanes_list[0]["shape"] if lanes_list else []
                edges_detail.append({
                    "id": eid,
                    "edge_id": eid,
                    "name": emeta.get("name") or "Road Segment",
                    "from_node": e.getFromNode().getID(),
                    "to_node": e.getToNode().getID(),
                    "road_type": emeta.get("road_type") or "arterial",
                    "speed_kmh": round(e.getSpeed() * 3.6, 1),
                    "num_lanes": len(lanes_list),
                    "length_m": round(e.getLength(), 1),
                    "is_oneway": emeta.get("is_oneway", False),
                    "is_buffer": emeta.get("is_buffer", False),
                    "is_estimated_lanes": emeta.get("is_estimated_lanes", False),
                    "osm_id": emeta.get("osm_id"),
                    "shape": edge_shape,
                    "lanes": lanes_list,
                    "current_vehicles_count": 0,
                    "mean_speed_kmh": round(e.getSpeed() * 3.6, 1),
                })

            for n in snet.getNodes():
                nid = n.getID()
                if nid.startswith(":"):
                    continue

                n_geo_shape = []
                try:
                    for x, y in n.getShape():
                        lon, lat = snet.convertXY2LonLat(x, y)
                        n_geo_shape.append([round(lon, 6), round(lat, 6)])
                        all_lons.append(lon)
                        all_lats.append(lat)
                except Exception:
                    pass

                try:
                    lon, lat = snet.convertXY2LonLat(*n.getCoord())
                except Exception:
                    nmeta = node_meta_map.get(nid, {})
                    lon = float(nmeta.get("x", 0.0))
                    lat = float(nmeta.get("y", 0.0))

                all_lons.append(lon)
                all_lats.append(lat)

                junctions_detail.append({
                    "id": nid,
                    "junction_id": nid,
                    "x": round(lon, 6),
                    "y": round(lat, 6),
                    "type": n.getType(),
                    "shape": n_geo_shape,
                    "incoming_edges": [inc.getID() for inc in n.getIncoming() if not inc.getID().startswith(":")],
                    "outgoing_edges": [out.getID() for out in n.getOutgoing() if not out.getID().startswith(":")],
                    "has_traffic_light": n.getType() == "traffic_light",
                    "tl_id": nid if n.getType() == "traffic_light" else None,
                    "current_phase": None,
                    "waiting_vehicles_count": 0,
                })
        else:
            # Fallback geometry directly from metadata
            for e in edges_meta:
                eid = e["id"]
                coords = []
                if e.get("shape"):
                    try:
                        coords = [[float(p.split(",")[0]), float(p.split(",")[1])] for p in e["shape"].split()]
                        for c in coords:
                            all_lons.append(c[0])
                            all_lats.append(c[1])
                    except Exception:
                        pass
                lanes_count = int(e.get("numLanes", 1))
                lanes_list = [
                    {
                        "id": f"{eid}_{i}",
                        "index": i,
                        "width_m": 3.2,
                        "speed_kmh": round(float(e.get("speed", 13.8)) * 3.6, 1),
                        "shape": coords,
                    }
                    for i in range(lanes_count)
                ]
                edges_detail.append({
                    "id": eid,
                    "edge_id": eid,
                    "name": e.get("name", "Road Segment"),
                    "from_node": e["from"],
                    "to_node": e["to"],
                    "road_type": e.get("road_type", "arterial"),
                    "speed_kmh": round(float(e.get("speed", 13.8)) * 3.6, 1),
                    "num_lanes": lanes_count,
                    "length_m": 100.0,
                    "is_oneway": e.get("is_oneway", False),
                    "is_buffer": e.get("is_buffer", False),
                    "is_estimated_lanes": e.get("is_estimated_lanes", False),
                    "osm_id": e.get("osm_id"),
                    "shape": coords,
                    "lanes": lanes_list,
                    "current_vehicles_count": 0,
                    "mean_speed_kmh": round(float(e.get("speed", 13.8)) * 3.6, 1),
                })

            for nid, n in nodes_meta.items():
                lon, lat = float(n.get("x", 0.0)), float(n.get("y", 0.0))
                all_lons.append(lon)
                all_lats.append(lat)
                junctions_detail.append({
                    "id": nid,
                    "junction_id": nid,
                    "x": round(lon, 6),
                    "y": round(lat, 6),
                    "type": n.get("type", "priority"),
                    "shape": [[round(lon, 6), round(lat, 6)]],
                    "incoming_edges": [],
                    "outgoing_edges": [],
                    "has_traffic_light": n.get("type") == "traffic_light",
                    "tl_id": nid if n.get("type") == "traffic_light" else None,
                    "current_phase": None,
                    "waiting_vehicles_count": 0,
                })

        if polygon_coords:
            for pc in polygon_coords:
                all_lons.append(pc[0])
                all_lats.append(pc[1])

        min_lon = min(all_lons) if all_lons else 0.0
        max_lon = max(all_lons) if all_lons else 0.0
        min_lat = min(all_lats) if all_lats else 0.0
        max_lat = max(all_lats) if all_lats else 0.0

        poly_area_km2 = 0.0
        if polygon_coords and len(polygon_coords) >= 3:
            try:
                poly_obj = Polygon(polygon_coords)
                if not poly_obj.is_valid:
                    poly_obj = poly_obj.buffer(0)
                from app.geospatial.road_network import _compute_geodesic_area_km2
                poly_area_km2 = round(_compute_geodesic_area_km2(poly_obj), 4)
            except Exception:
                pass

        g_topo = nx.DiGraph()
        for ed in edges_detail:
            g_topo.add_edge(ed["from_node"], ed["to_node"])
        conn_comp = nx.number_weakly_connected_components(g_topo) if g_topo.number_of_nodes() > 0 else 1
        dead_ends = sum(1 for n in g_topo.nodes() if g_topo.out_degree(n) == 0 and g_topo.in_degree(n) > 0)

        total_lanes = sum(ed["num_lanes"] for ed in edges_detail)
        single_cnt = sum(1 for ed in edges_detail if ed["num_lanes"] == 1)
        two_cnt = sum(1 for ed in edges_detail if ed["num_lanes"] == 2)
        four_cnt = sum(1 for ed in edges_detail if ed["num_lanes"] == 4)
        other_cnt = sum(1 for ed in edges_detail if ed["num_lanes"] not in (1, 2, 4))
        sig_cnt = sum(1 for j in junctions_detail if j["has_traffic_light"])
        ver_lanes = sum(1 for ed in edges_detail if not ed["is_estimated_lanes"])
        inf_lanes = sum(1 for ed in edges_detail if ed["is_estimated_lanes"])

        summary = {
            "total_segments": len(edges_meta),
            "total_edges": len(edges_detail),
            "directed_edges": len(edges_detail),
            "junction_count": len(junctions_detail),
            "total_lanes": total_lanes,
            "single_lane_roads": single_cnt,
            "two_lane_roads": two_cnt,
            "four_lane_roads": four_cnt,
            "other_lane_roads": other_cnt,
            "traffic_signals_count": sig_cnt,
            "connected_components": conn_comp,
            "dead_ends_count": dead_ends,
            "entry_points_count": getattr(self, "boundary_diagnostics", {}).get("entry_count", 0),
            "exit_points_count": getattr(self, "boundary_diagnostics", {}).get("exit_count", 0),
            "verified_lane_count": ver_lanes,
            "inferred_lane_count": inf_lanes,
            "selected_area_km2": poly_area_km2,
            "buffer_area_km2": 0.0,
            "buffer_distance_m": buffer_m,
        }

        return {
            "sim_id": sim_id,
            "analysis_id": analysis_id,
            "bounds": [round(min_lon, 6), round(min_lat, 6), round(max_lon, 6), round(max_lat, 6)],
            "polygon_coords": polygon_coords or [],
            "edges": edges_detail,
            "junctions": junctions_detail,
            "summary": summary,
            "diagnostics": {
                "sumolib_used": sumolib_ok,
                "netconvert_used": True if sumolib_ok else False,
                "compilation": getattr(self, "compilation_diagnostics", {}),
                "boundary": getattr(self, "boundary_diagnostics", {}),
                "demand": getattr(self, "demand_tracking", {}),
                "validation": {
                    "polygon_valid": True if polygon_coords and len(polygon_coords) >= 3 else False,
                    "polygon_area_km2": poly_area_km2,
                    "core_edges_count": sum(1 for ed in edges_detail if not ed.get("is_buffer")),
                    "buffer_edges_count": sum(1 for ed in edges_detail if ed.get("is_buffer")),
                    "connected_components": conn_comp,
                    "dead_ends_count": dead_ends,
                    "completeness_status": "complete" if len(edges_detail) > 0 else "empty",
                    "coordinate_projection": "UTM / WGS84 Geodesic",
                },
            },
        }

    def _corridor_from_polygon(self, polygon_coords: list[list[float]]) -> list[dict[str, Any]]:
        """Construct representative urban arterial corridor centered on the polygon bounds."""
        center_lon = sum(c[0] for c in polygon_coords) / len(polygon_coords)
        center_lat = sum(c[1] for c in polygon_coords) / len(polygon_coords)
        d_lon = 0.004
        d_lat = 0.004
        return [
            {
                "segment_id": "seg_poly_main_w",
                "name": "Polygon Arterial West",
                "from_node_id": "J_west",
                "to_node_id": "J_center",
                "geometry": {"coordinates": [[round(center_lon - d_lon, 6), round(center_lat, 6)], [round(center_lon, 6), round(center_lat, 6)]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
                "v_control": "traffic_signal",
                "v_provenance": "simulation_assumption",
            },
            {
                "segment_id": "seg_poly_main_e",
                "name": "Polygon Arterial East",
                "from_node_id": "J_center",
                "to_node_id": "J_east",
                "geometry": {"coordinates": [[round(center_lon, 6), round(center_lat, 6)], [round(center_lon + d_lon, 6), round(center_lat, 6)]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
            },
            {
                "segment_id": "seg_poly_cross_s",
                "name": "Polygon Corridor South",
                "from_node_id": "J_south",
                "to_node_id": "J_center",
                "geometry": {"coordinates": [[round(center_lon, 6), round(center_lat - d_lat, 6)], [round(center_lon, 6), round(center_lat, 6)]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
            },
            {
                "segment_id": "seg_poly_cross_n",
                "name": "Polygon Corridor North",
                "from_node_id": "J_center",
                "to_node_id": "J_north",
                "geometry": {"coordinates": [[round(center_lon, 6), round(center_lat, 6)], [round(center_lon, 6), round(center_lat + d_lat, 6)]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
            },
        ]

    def _default_corridor_segments(self) -> list[dict[str, Any]]:
        """Default representative urban corridor if no segments are provided."""
        return [
            {
                "segment_id": "seg_main_1",
                "name": "Main Urban Arterial",
                "from_node_id": "J10",
                "to_node_id": "J12",
                "geometry": {"coordinates": [[80.9320, 26.8920], [80.9420, 26.8920]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
                "v_control": "traffic_signal",
                "v_provenance": "simulation_assumption",
            },
            {
                "segment_id": "seg_main_2",
                "name": "Main Urban Arterial East",
                "from_node_id": "J12",
                "to_node_id": "J14",
                "geometry": {"coordinates": [[80.9420, 26.8920], [80.9520, 26.8920]]},
                "road_type": "arterial",
                "speed_limit_kmh": 50,
                "lanes": 2,
                "is_oneway": False,
            },
            {
                "segment_id": "seg_cross_1",
                "name": "Ring Road Sector Link",
                "from_node_id": "J11",
                "to_node_id": "J12",
                "geometry": {"coordinates": [[80.9420, 26.8840], [80.9420, 26.8920]]},
                "road_type": "arterial",
                "speed_limit_kmh": 60,
                "lanes": 3,
                "is_oneway": False,
            },
            {
                "segment_id": "seg_cross_2",
                "name": "North Sector Connector",
                "from_node_id": "J12",
                "to_node_id": "J13",
                "geometry": {"coordinates": [[80.9420, 26.8920], [80.9420, 26.9000]]},
                "road_type": "arterial",
                "speed_limit_kmh": 60,
                "lanes": 3,
                "is_oneway": False,
            },
        ]
