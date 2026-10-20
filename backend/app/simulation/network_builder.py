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

logger = logging.getLogger(__name__)

# Maximum road segments to compile into a single SUMO network.
# Supports large corridor selections (e.g. 354+ segments).
MAX_SEGMENTS = 1000


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

        # 1. Process Nodes and Edges
        nodes, edges, segment_edge_map, edge_segment_map, assumptions = self._extract_nodes_and_edges(
            segments, polygon_coords, allow_synthetic=allow_synthetic
        )
        self._write_nodes_xml(nod_file, nodes)
        self._write_edges_xml(edg_file, edges)

        # 2. Run netconvert with UTM projection (establishes true CRS for convertGeo)
        netconvert_success = False
        if self.netconvert_bin and Path(self.netconvert_bin).is_file():
            try:
                cmd = [
                    self.netconvert_bin,
                    "--node-files", str(nod_file),
                    "--edge-files", str(edg_file),
                    "--output-file", str(net_file),
                    "--proj.utm",
                    "--no-warnings",
                    "--ignore-errors",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and net_file.is_file():
                    netconvert_success = True
                    logger.info("netconvert generated UTM network successfully: %s", net_file)
                else:
                    logger.warning("netconvert with --proj.utm exited %s: %s; trying plain-geo fallback", res.returncode, res.stderr)
                    cmd_fallback = [
                        self.netconvert_bin,
                        "--node-files", str(nod_file),
                        "--edge-files", str(edg_file),
                        "--output-file", str(net_file),
                        "--proj.plain-geo",
                        "--no-warnings",
                        "--ignore-errors",
                    ]
                    res2 = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=30)
                    if res2.returncode == 0 and net_file.is_file():
                        netconvert_success = True
                        logger.info("netconvert generated plain-geo fallback network: %s", net_file)
            except Exception as e:
                logger.error("Failed to run netconvert: %s", e)

        # Fallback XML if netconvert failed or missing
        if not netconvert_success or not net_file.is_file():
            self._write_fallback_net_xml(net_file, nodes, edges)

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

        # 4. Write Vehicle Demand (Routes) using boundary entry/exit through-trips
        scheduled_count = self._write_routes_xml(
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
        )

        # 5. Write SUMO Configuration with dynamic rerouting support
        self._write_sumocfg(cfg_file, net_file.name, rou_file.name, duration_seconds)

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
            "scheduled_vehicles": scheduled_count,
            "nodes": nodes,
            "edges": edges,
            # segment_id → [sumo_edge_id, ...] map used for congestion telemetry
            "segment_edge_map": segment_edge_map,
            # sumo_edge_id → source segment_id map for reverse lookup
            "edge_segment_map": edge_segment_map,
            "assumptions": assumptions,
            "total_eligible_segments": len(segments),
            "segments_simulated": len(edges),
            "omitted_segments_count": max(0, len(segments) - MAX_SEGMENTS),
            "network_provenance": "synthetic_demo" if allow_synthetic and not segments else "real_osm",
        }

    def _extract_nodes_and_edges(
        self,
        segments: list[dict[str, Any]],
        polygon_coords: Optional[list[list[float]]] = None,
        allow_synthetic: bool = False,
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

        # Truncate to MAX_SEGMENTS with explicit warning
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

            # Check and record road attribute assumptions
            if seg.get("speed_limit_kmh") is None and "default_speed_50kmh_applied" not in assumptions:
                assumptions.append("default_speed_50kmh_applied")
            if seg.get("lanes") is None and "default_lanes_2_applied" not in assumptions:
                assumptions.append("default_lanes_2_applied")

            speed_kmh = float(seg.get("speed_limit_kmh") or 50.0)
            lanes = max(1, min(4, int(seg.get("lanes") or 2)))
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
                "numLanes": lanes,
                "shape": shape_str,
                "name": seg.get("name") or "Road Segment",
            })

            # Track mapping from Gativa segment_id → SUMO edge IDs for congestion analysis
            seg_edge_ids = [safe_edge_id]

            # If bidirectional, add reverse edge with collision-safe ID
            if not seg.get("is_oneway", False):
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
                    "numLanes": lanes,
                    "shape": shape_str_rev,
                    "name": seg.get("name") or "Road Segment",
                })
                seg_edge_ids.append(candidate_rev)

            segment_edge_map[raw_seg_id] = seg_edge_ids

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
            }
            if edge.get("shape"):
                attribs["shape"] = edge["shape"]
            ET.SubElement(root, "edge", attribs)
        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

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
        Identify boundary entry edges, boundary exit edges, and internal edges.
        Edges entering from or near the selection perimeter are entry candidates;
        edges heading out towards the perimeter are exit candidates.
        """
        if not edges:
            return [], [], []

        # Find spatial boundary extents
        all_xs = [n["x"] for n in nodes.values()]
        all_ys = [n["y"] for n in nodes.values()]
        min_x, max_x = min(all_xs), max(all_xs)
        min_y, max_y = min(all_ys), max(all_ys)
        dx = max(0.0001, max_x - min_x)
        dy = max(0.0001, max_y - min_y)
        margin_x = dx * 0.15
        margin_y = dy * 0.15

        def is_perimeter_node(n_id: str) -> bool:
            node = nodes.get(n_id)
            if not node:
                return False
            x, y = node["x"], node["y"]
            return (
                x <= min_x + margin_x
                or x >= max_x - margin_x
                or y <= min_y + margin_y
                or y >= max_y - margin_y
            )

        entry_edges = []
        exit_edges = []
        internal_edges = []

        for e in edges:
            from_perim = is_perimeter_node(e["from"])
            to_perim = is_perimeter_node(e["to"])

            if from_perim and not to_perim:
                entry_edges.append(e)
            elif to_perim and not from_perim:
                exit_edges.append(e)
            elif from_perim and to_perim:
                entry_edges.append(e)
                exit_edges.append(e)
            else:
                internal_edges.append(e)

        if not entry_edges:
            entry_edges = edges[: max(1, len(edges) // 2)]
        if not exit_edges:
            exit_edges = edges[len(edges) // 2 :] if len(edges) > 1 else edges

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
    ) -> int:
        """
        Generate trip demand with realistic through-routing:
        - Boundary entry to boundary exit through-trips prioritized
        - Internal origin/destination trips included for realistic balance
        - Immediate departures for initial vehicles so simulation has traffic from step 1
        - Gradual departure scheduling following configured profile (no simultaneous bursts)
        - Vehicle type mix (passenger cars, buses)
        """
        import random
        import networkx as nx

        if isinstance(nodes, list):
            # Called with legacy signature: _write_routes_xml(file_path, edges, duration, demand_rate, seed)
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
            color="1,0.6,0",
        )

        total_vehicles = target_vehicle_count or max(15, int(demand_rate_veh_hr * (duration_seconds / 3600.0)))

        # Build directed graph of road network
        G = nx.DiGraph()
        for e in actual_edges:
            G.add_edge(e["from"], e["to"], id=e["id"])

        entry_edges, exit_edges, internal_edges = self._identify_boundary_edges(actual_nodes, actual_edges, polygon_coords)

        # Precompute reachable descendants for each node (single BFS per node, takes ~0.03s total)
        # Avoids O(E^2) individual nx.has_path calls which caused the 120s timeout on large networks.
        reachable_map: dict[str, set[str]] = {}
        for n in G.nodes():
            reachable_map[n] = nx.descendants(G, n)

        # 1. Collect Valid Through-Pairs (Entry to Exit with reachable path)
        through_pairs: list[tuple[str, str]] = []
        for en in entry_edges:
            en_to = en["to"]
            reachable = reachable_map.get(en_to, set())
            for ex in exit_edges:
                if en["id"] == ex["id"]:
                    continue
                if en_to == ex["from"] or ex["from"] in reachable:
                    through_pairs.append((en["id"], ex["id"]))
                    if len(through_pairs) >= 500:
                        break
            if len(through_pairs) >= 500:
                break

        # 2. Collect Valid Internal Pairs (origin or destination inside corridor)
        internal_pairs: list[tuple[str, str]] = []
        sample_pool = actual_edges if len(actual_edges) <= 100 else rng.sample(actual_edges, 100)
        for e1 in sample_pool:
            e1_to = e1["to"]
            reachable = reachable_map.get(e1_to, set())
            for e2 in sample_pool:
                if e1["id"] == e2["id"]:
                    continue
                if e1_to == e2["from"] or e2["from"] in reachable:
                    internal_pairs.append((e1["id"], e2["id"]))
                    if len(internal_pairs) >= 300:
                        break
            if len(internal_pairs) >= 300:
                break

        if not through_pairs:
            through_pairs = internal_pairs or [(actual_edges[0]["id"], actual_edges[-1]["id"])]
        if not internal_pairs:
            internal_pairs = through_pairs

        # 3. Schedule Departures according to profile
        scheduled_trips: list[tuple[float, str, str, str, str]] = []
        bus_fraction = (vehicle_types or {}).get("bus", 0.12)
        headway_per_edge: dict[str, float] = {}

        for v_idx in range(total_vehicles):
            # Guarantee initial vehicles depart immediately at t=0.0, 0.5, 1.0, 1.5...
            # so the simulation has vehicles active right from the first steps
            if v_idx < min(6, total_vehicles):
                dep_time = float(v_idx * 0.5)
                if through_pairs:
                    from_edge, to_edge = through_pairs[v_idx % len(through_pairs)]
                else:
                    from_edge, to_edge = internal_pairs[v_idx % len(internal_pairs)]
                v_type = "bus" if rng.random() < bus_fraction else "passenger"
                scheduled_trips.append((round(dep_time, 1), f"veh_{v_idx}", v_type, from_edge, to_edge))
                continue

            # Select profile departure time
            if demand_profile == "peak":
                raw_t = rng.gauss(0.42 * duration_seconds, 0.22 * duration_seconds)
                dep_time = max(0.0, min(float(duration_seconds - 5), raw_t))
            elif demand_profile == "ramp_up":
                raw_t = rng.triangular(0.0, duration_seconds - 5, duration_seconds - 5)
                dep_time = max(0.0, min(float(duration_seconds - 5), raw_t))
            elif demand_profile == "morning_peak":
                raw_t = rng.gauss(0.25 * duration_seconds, 0.18 * duration_seconds)
                dep_time = max(0.0, min(float(duration_seconds - 5), raw_t))
            else:  # uniform
                dep_time = (v_idx / max(1, total_vehicles)) * (duration_seconds - 10) + rng.uniform(0.0, 1.5)

            # 75% Through-Trips, 25% Internal
            if rng.random() < 0.75 and through_pairs:
                from_edge, to_edge = rng.choice(through_pairs)
            else:
                from_edge, to_edge = rng.choice(internal_pairs if internal_pairs else through_pairs)

            # Prevent simultaneous collision/jamming on same entry edge with min 2.0s headway
            last_dep = headway_per_edge.get(from_edge, -10.0)
            if dep_time < last_dep + 2.0:
                dep_time = last_dep + 2.0
            headway_per_edge[from_edge] = dep_time

            v_type = "bus" if rng.random() < bus_fraction else "passenger"
            scheduled_trips.append((round(dep_time, 1), f"veh_{v_idx}", v_type, from_edge, to_edge))

        # Sort strictly by departure time for SUMO requirements
        scheduled_trips.sort(key=lambda x: x[0])


        for dep_time, v_id, v_type, f_edge, t_edge in scheduled_trips:
            ET.SubElement(
                root,
                "trip",
                id=v_id,
                type=v_type,
                depart=f"{dep_time:.1f}",
                **{"from": f_edge, "to": t_edge},
            )

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)
        return len(scheduled_trips)

    def _write_sumocfg(self, file_path: Path, net_name: str, rou_name: str, duration_seconds: int):
        root = ET.Element("configuration")
        input_elem = ET.SubElement(root, "input")
        ET.SubElement(input_elem, "net-file", value=net_name)
        ET.SubElement(input_elem, "route-files", value=rou_name)

        time_elem = ET.SubElement(root, "time")
        ET.SubElement(time_elem, "begin", value="0")
        ET.SubElement(time_elem, "end", value=str(duration_seconds))
        ET.SubElement(time_elem, "step-length", value="0.2")

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
