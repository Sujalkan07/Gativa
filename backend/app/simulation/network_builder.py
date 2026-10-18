"""
Network Builder: Converts Gativa analyzed road network into a valid Eclipse SUMO network.
Generates .nod.xml, .edg.xml, routes.rou.xml, and simulation.sumocfg, and runs netconvert.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        """
        Create complete SUMO simulation directory:
        1. nodes.nod.xml
        2. edges.edg.xml
        3. netconvert -> network.net.xml
        4. routes.rou.xml
        5. simulation.sumocfg
        """
        nod_file = self.work_dir / "nodes.nod.xml"
        edg_file = self.work_dir / "edges.edg.xml"
        net_file = self.work_dir / "network.net.xml"
        rou_file = self.work_dir / "routes.rou.xml"
        cfg_file = self.work_dir / "simulation.sumocfg"

        # 1. Process Nodes and Edges
        nodes, edges = self._extract_nodes_and_edges(segments)
        self._write_nodes_xml(nod_file, nodes)
        self._write_edges_xml(edg_file, edges)

        # 2. Run netconvert
        netconvert_success = False
        if self.netconvert_bin and Path(self.netconvert_bin).is_file():
            try:
                cmd = [
                    self.netconvert_bin,
                    "--node-files", str(nod_file),
                    "--edge-files", str(edg_file),
                    "--output-file", str(net_file),
                    "--proj.plain-geo",
                    "--no-warnings",
                    "--ignore-errors",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and net_file.is_file():
                    netconvert_success = True
                    logger.info("netconvert generated network successfully: %s", net_file)
                else:
                    logger.warning("netconvert exited with code %s: %s", res.returncode, res.stderr)
            except Exception as e:
                logger.error("Failed to run netconvert: %s", e)

        # Fallback XML if netconvert failed or missing
        if not netconvert_success or not net_file.is_file():
            self._write_fallback_net_xml(net_file, nodes, edges)

        # 3. Write Vehicle Demand (Routes)
        valid_edge_ids = [e["id"] for e in edges]
        self._write_routes_xml(rou_file, valid_edge_ids, duration_seconds, demand_rate_veh_hr, seed)

        # 4. Write SUMO Configuration
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
            "demand_rate_veh_hr": demand_rate_veh_hr,
        }

    def _extract_nodes_and_edges(
        self, segments: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Extract clean node coordinates and directional edges from road segments."""
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        # If empty segments provided, construct default corridor representation
        if not segments:
            segments = self._default_corridor_segments()

        # Build node coordinate registry
        for idx, seg in enumerate(segments[:60]):  # Bounded to max 60 segments for responsive simulation
            geom = seg.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue

            u_id = seg.get("from_node_id") or f"node_{idx}_u"
            v_id = seg.get("to_node_id") or f"node_{idx}_v"

            # GeoJSON coordinates are [lon, lat]
            u_lon, u_lat = coords[0][0], coords[0][1]
            v_lon, v_lat = coords[-1][0], coords[-1][1]

            if u_id not in nodes:
                nodes[u_id] = {"id": u_id, "x": u_lon, "y": u_lat, "degree": 0}
            if v_id not in nodes:
                nodes[v_id] = {"id": v_id, "x": v_lon, "y": v_lat, "degree": 0}

            nodes[u_id]["degree"] += 1
            nodes[v_id]["degree"] += 1

            speed_kmh = float(seg.get("speed_limit_kmh") or 50.0)
            lanes = max(1, min(4, int(seg.get("lanes") or 2)))
            edge_id = str(seg.get("segment_id") or f"edge_{idx}")

            edges.append({
                "id": edge_id,
                "from": u_id,
                "to": v_id,
                "speed": round(speed_kmh / 3.6, 2),  # m/s
                "numLanes": lanes,
                "name": seg.get("name") or "Road Segment",
            })

            # If bidirectional, add reverse edge
            if not seg.get("is_oneway", False):
                edges.append({
                    "id": f"{edge_id}_rev",
                    "from": v_id,
                    "to": u_id,
                    "speed": round(speed_kmh / 3.6, 2),
                    "numLanes": lanes,
                    "name": seg.get("name") or "Road Segment",
                })

        # Mark high-degree junctions as traffic lights
        for n in nodes.values():
            if n["degree"] >= 3:
                n["type"] = "traffic_light"
            else:
                n["type"] = "priority"

        # Ensure at least one traffic light exists for scenario comparison
        if not any(n["type"] == "traffic_light" for n in nodes.values()) and nodes:
            list(nodes.values())[0]["type"] = "traffic_light"

        return nodes, edges

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
            ET.SubElement(
                root,
                "edge",
                id=str(edge["id"]),
                **{"from": str(edge["from"])},
                to=str(edge["to"]),
                speed=str(edge["speed"]),
                numLanes=str(edge["numLanes"]),
                priority="2",
            )
        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

    def _write_routes_xml(
        self,
        file_path: Path,
        edge_ids: list[str],
        duration_seconds: int,
        demand_rate_veh_hr: int,
        seed: int,
    ):
        """Generate calibrated trip demand."""
        import random
        rng = random.Random(seed)

        root = ET.Element("routes")
        # Define vehicle types
        ET.SubElement(root, "vType", id="passenger", accel="2.6", decel="4.5", sigma="0.5", length="4.5", maxSpeed="33.3")
        ET.SubElement(root, "vType", id="bus", accel="1.2", decel="3.5", sigma="0.5", length="12.0", maxSpeed="20.0", color="1,0.6,0")

        total_vehicles = max(20, int(demand_rate_veh_hr * (duration_seconds / 3600.0)))
        edge_count = len(edge_ids)

        if edge_count >= 2:
            depart_interval = duration_seconds / max(1, total_vehicles)
            for v_idx in range(total_vehicles):
                depart_time = round(v_idx * depart_interval + rng.uniform(0, 1.5), 1)
                from_edge = rng.choice(edge_ids)
                to_edge = rng.choice(edge_ids)
                while to_edge == from_edge and edge_count > 1:
                    to_edge = rng.choice(edge_ids)

                v_type = "bus" if rng.random() < 0.12 else "passenger"
                ET.SubElement(
                    root,
                    "trip",
                    id=f"veh_{v_idx}",
                    type=v_type,
                    depart=f"{depart_time:.1f}",
                    **{"from": from_edge, "to": to_edge},
                )

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

    def _write_sumocfg(self, file_path: Path, net_name: str, rou_name: str, duration_seconds: int):
        root = ET.Element("configuration")
        input_elem = ET.SubElement(root, "input")
        ET.SubElement(input_elem, "net-file", value=net_name)
        ET.SubElement(input_elem, "route-files", value=rou_name)

        time_elem = ET.SubElement(root, "time")
        ET.SubElement(time_elem, "begin", value="0")
        ET.SubElement(time_elem, "end", value=str(duration_seconds))
        ET.SubElement(time_elem, "step-length", value="0.2")

        report_elem = ET.SubElement(root, "report")
        ET.SubElement(report_elem, "no-warnings", value="true")
        ET.SubElement(report_elem, "no-step-log", value="true")

        tree = ET.ElementTree(root)
        tree.write(str(file_path), encoding="utf-8", xml_declaration=True)

    def _write_fallback_net_xml(self, file_path: Path, nodes: dict, edges: list):
        """Minimal compliant network XML in case netconvert is bypassed."""
        root = ET.Element("net", version="1.20", xmlns="http://sumo.dlr.de/xsd/net_file.xsd")
        for e in edges:
            edge_elem = ET.SubElement(root, "edge", id=e["id"], **{"from": e["from"]}, to=e["to"], priority="2")
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
