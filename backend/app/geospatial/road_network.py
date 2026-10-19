"""
OSMnx-based road network retrieval, geodesic calculations, and spatial analysis.
Uses OpenStreetMap data via the OSM API v0.6 and Overpass mirrors — no Google API key required.
Includes WGS84 geodesic calculations (pyproj), polygon boundary clipping (shapely),
and physical edge deduplication for accurate road reporting.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import tempfile
from typing import Optional

import networkx as nx
import osmnx as ox
import pyproj
from shapely.geometry import Polygon, Point, LineString, MultiLineString, GeometryCollection, mapping

from app.core.config import get_settings
from app.core.sqlite_store import get_osm_cache_sync, save_osm_cache_sync
from app.models.schemas import (
    RoadNetworkMetrics,
    RoadSegment,
    GeoJSONLineString,
    BottleneckCandidate,
    DataSourceCoverage,
    JunctionControlType,
    ControlProvenance,
)

logger = logging.getLogger(__name__)

# WGS84 Ellipsoid geodetic calculator for exact ellipsoidal GIS metrics
_GEOD = pyproj.Geod(ellps="WGS84")

# OSMnx road type → Gativa classification
# Tertiary and tertiary_link are classified as arterials (urban collectors / district spines)
ROAD_CLASS_MAP = {
    # High-speed access-controlled corridors
    "motorway": "highway",
    "motorway_link": "highway",
    "trunk": "highway",
    "trunk_link": "highway",

    # Primary, secondary, and tertiary arterial spines & collectors
    "primary": "arterial",
    "primary_link": "arterial",
    "secondary": "arterial",
    "secondary_link": "arterial",
    "tertiary": "arterial",
    "tertiary_link": "arterial",

    # Local neighborhood streets and access service ways
    "residential": "local",
    "living_street": "local",
    "unclassified": "local",
    "road": "local",
    "service": "local",
}


def _classify_road(highway_tag: str | list[str] | None) -> str:
    """Classify an OSM highway tag into highway, arterial, or local."""
    if not highway_tag:
        return "local"
    if isinstance(highway_tag, list):
        classes = [_classify_road(t) for t in highway_tag]
        if "highway" in classes:
            return "highway"
        if "arterial" in classes:
            return "arterial"
        return "local"
    return ROAD_CLASS_MAP.get(str(highway_tag).strip().lower(), "local")


def _compute_geodesic_area_km2(polygon: Polygon) -> float:
    """Compute polygon area in km² using WGS84 geodesic calculation (pyproj)."""
    try:
        area_m2, _ = _GEOD.geometry_area_perimeter(polygon)
        return abs(area_m2) / 1_000_000.0
    except Exception as exc:
        logger.debug("Geodesic area calculation fallback: %s", exc)
        return 0.0


def _compute_geodesic_length_m(geom) -> float:
    """Compute LineString length in meters using WGS84 geodesic calculation (pyproj)."""
    if geom is None or geom.is_empty:
        return 0.0
    try:
        return float(_GEOD.geometry_length(geom))
    except Exception as exc:
        logger.debug("Geodesic length calculation fallback: %s", exc)
        return 0.0


def _clip_geometry_to_polygon(geom, poly: Polygon):
    """Clip a Shapely geometry strictly to a boundary polygon."""
    if geom is None or geom.is_empty:
        return None
    if not poly.intersects(geom):
        return None
    try:
        clipped = geom.intersection(poly)
        if clipped.is_empty:
            return None
        if clipped.geom_type == "LineString":
            return clipped
        elif clipped.geom_type == "MultiLineString":
            lines = [l for l in clipped.geoms if l.length > 0]
            if lines:
                return max(lines, key=lambda l: l.length)
        elif clipped.geom_type == "GeometryCollection":
            lines = [g for g in clipped.geoms if g.geom_type == "LineString" and g.length > 0]
            if lines:
                return max(lines, key=lambda l: l.length)
    except Exception as exc:
        logger.debug("Geometry clipping fallback: %s", exc)
    return geom


def _get_polygon_cache_key(poly: Polygon) -> str:
    """Generate deterministic cache key for a spatial bounding box (~11m resolution)."""
    minx, miny, maxx, maxy = poly.bounds
    bbox_str = f"{minx:.4f}_{miny:.4f}_{maxx:.4f}_{maxy:.4f}"
    return hashlib.sha256(bbox_str.encode()).hexdigest()[:16]


def _get_speed_limit(data: dict) -> Optional[float]:
    maxspeed = data.get("maxspeed")
    if not maxspeed:
        return None
    if isinstance(maxspeed, list):
        maxspeed = maxspeed[0]
    try:
        parts = str(maxspeed).split()
        value = float(parts[0])
        if len(parts) > 1 and "mph" in parts[1].lower():
            value *= 1.60934
        return round(value, 1)
    except (ValueError, IndexError):
        return None


def _get_lanes(data: dict) -> Optional[int]:
    lanes = data.get("lanes")
    if not lanes:
        return None
    if isinstance(lanes, list):
        lanes = lanes[0]
    try:
        return int(lanes)
    except (ValueError, TypeError):
        return None


def _inspect_node_control(
    node_data: dict,
    incident_edge_data: Optional[dict] = None,
) -> tuple[JunctionControlType, ControlProvenance]:
    """
    Determine junction control type and provenance from OSM node and edge attributes.
    Preserves strict authenticity: a node is ONLY marked 'traffic_signal' if verified by
    genuine OSM tags. High-degree junctions default to 'priority' with 'unknown' provenance.
    """
    hw = node_data.get("highway")
    if isinstance(hw, list):
        hw = hw[0]
    crossing = node_data.get("crossing")
    if isinstance(crossing, list):
        crossing = crossing[0]
    junction = node_data.get("junction")
    if isinstance(junction, list):
        junction = junction[0]

    # 1. Verified traffic signals
    if (
        hw == "traffic_signals"
        or crossing == "traffic_signals"
        or str(node_data.get("traffic_signals", "")).lower() in ("yes", "signal", "traffic_signals")
    ):
        return "traffic_signal", "source_verified"

    # 2. Stop signs
    if hw == "stop":
        return "stop", "source_verified"

    # 3. Give way / Yield
    if hw in ("give_way", "yield"):
        return "yield", "source_verified"

    # 4. Roundabouts
    if hw == "mini_roundabout" or junction in ("roundabout", "circular"):
        return "roundabout", "source_verified"

    if incident_edge_data:
        edge_junction = incident_edge_data.get("junction")
        if isinstance(edge_junction, list):
            edge_junction = edge_junction[0]
        if edge_junction in ("roundabout", "circular"):
            return "roundabout", "source_verified"

    # 5. Default priority rules (unsignalized)
    return "priority", "unknown"


async def _discover_local_street_names(poly: Polygon) -> tuple[list[str], str]:
    """Discover genuine local road names and neighborhood subdivision using TomTom reverse geocode."""
    settings = get_settings()
    if not settings.tomtom_api_key:
        return [], ""

    import httpx

    minx, miny, maxx, maxy = poly.bounds
    cx, cy = poly.centroid.x, poly.centroid.y

    sample_points = [
        (cy, cx),
        (miny + 0.25 * (maxy - miny), minx + 0.25 * (maxx - minx)),
        (miny + 0.25 * (maxy - miny), minx + 0.75 * (maxx - minx)),
        (miny + 0.75 * (maxy - miny), minx + 0.25 * (maxx - minx)),
        (miny + 0.75 * (maxy - miny), minx + 0.75 * (maxx - minx)),
        (cy, minx + 0.25 * (maxx - minx)),
        (cy, minx + 0.75 * (maxx - minx)),
        (miny + 0.5 * (maxy - miny), cx),
    ]

    discovered_streets: list[str] = []
    locality = ""

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            async def _geocode_point(lat: float, lon: float):
                url = f"https://api.tomtom.com/search/2/reverseGeocode/{lat:.6f},{lon:.6f}.json?key={settings.tomtom_api_key}"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        addresses = data.get("addresses", [])
                        if addresses:
                            addr = addresses[0].get("address", {})
                            return addr.get("streetName"), addr.get("municipalitySubdivision") or addr.get("municipality")
                except Exception:
                    pass
                return None, None

            results = await asyncio.gather(*[_geocode_point(lat, lon) for lat, lon in sample_points])
            for st, sub in results:
                if st and st not in discovered_streets:
                    discovered_streets.append(st)
                if sub and not locality:
                    locality = sub
    except Exception as exc:
        logger.debug("TomTom street discovery error: %s", exc)

    return discovered_streets, locality


def _parse_and_clip_xml(path: str, boundary_poly: Polygon) -> nx.MultiDiGraph:
    """Parse OSM XML file and truncate graph to boundary polygon, filtering non-drivable paths."""
    g = ox.graph_from_xml(path, simplify=True)
    if g.number_of_edges() == 0:
        return g
    g_clipped = ox.truncate.truncate_graph_polygon(g, boundary_poly)

    non_drivable = {
        "footway", "cycleway", "steps", "path", "pedestrian",
        "bridleway", "corridor", "platform", "proposed", "construction",
    }
    edges_to_remove = []
    for u, v, k, d in g_clipped.edges(keys=True, data=True):
        hw = d.get("highway")
        if isinstance(hw, list):
            hw = hw[0]
        if hw in non_drivable:
            edges_to_remove.append((u, v, k))
    for u, v, k in edges_to_remove:
        g_clipped.remove_edge(u, v, k)

    isolated = list(nx.isolates(g_clipped))
    g_clipped.remove_nodes_from(isolated)
    return g_clipped


async def _fetch_osm_graph_from_api(poly: Polygon) -> tuple[Optional[nx.MultiDiGraph], Optional[str]]:
    """
    Fetch road network directly from the official OpenStreetMap database API (v0.6).
    Fast, reliable, and returns real physical road geometries and street tags.
    Returns (MultiDiGraph, raw_xml_content).
    """
    import httpx

    minx, miny, maxx, maxy = poly.bounds
    if (maxx - minx) > 0.25 or (maxy - miny) > 0.25:
        logger.info("Bounding box (%.3f x %.3f) exceeds OSM API limit of 0.25 deg", maxx - minx, maxy - miny)
        return None, None

    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={minx:.6f},{miny:.6f},{maxx:.6f},{maxy:.6f}"
    headers = {
        "User-Agent": "GativaTrafficEngine/1.0",
        "Accept-Encoding": "gzip, deflate",
    }

    tmp_path = None
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200 or len(resp.content) < 100:
                logger.warning("OSM API v0.6 returned status %d (length %d bytes)", resp.status_code, len(resp.content))
                return None, None

            xml_content = resp.text
            with tempfile.NamedTemporaryFile(suffix=".osm", delete=False, mode="w", encoding="utf-8") as f:
                f.write(xml_content)
                tmp_path = f.name

        G = await asyncio.to_thread(_parse_and_clip_xml, tmp_path, poly)
        logger.info(
            "Retrieved real OSM road network via OSM API v0.6: %d nodes, %d edges",
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return (G if G.number_of_edges() > 0 else None), xml_content

    except Exception as exc:
        logger.warning("OSM API v0.6 retrieval failed: %s", exc)
        return None, None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def fetch_road_network(
    polygon_coords: list[list[float]],
    max_area_km2: float = 50.0,
) -> tuple[
    Optional[nx.MultiDiGraph],
    list[RoadSegment],
    Optional[RoadNetworkMetrics],
    list[BottleneckCandidate],
    DataSourceCoverage,
]:
    """
    Retrieve the road network for a polygon from OpenStreetMap via OSMnx.
    Performs boundary clipping, geodesic metrics calculations, and physical segment deduplication.

    Args:
        polygon_coords: GeoJSON coordinates [[lng, lat], ...] (outer ring).
        max_area_km2: Maximum area to process.

    Returns:
        Tuple of (graph, segments, metrics, bottlenecks, coverage).
    """
    try:
        # Build shapely polygon from GeoJSON coords (lng, lat)
        coords_tuples = [(c[0], c[1]) for c in polygon_coords]
        poly = Polygon(coords_tuples)
        if not poly.is_valid:
            poly = poly.buffer(0)
            if not poly.is_valid or poly.is_empty:
                return None, [], None, [], DataSourceCoverage(
                    source="osm",
                    status="error",
                    message="Selected polygon has self-intersecting or invalid boundary topology. Please redraw without crossing lines.",
                )

        area_km2 = _compute_geodesic_area_km2(poly)
        logger.info("Road network request: area=%.2f km² (WGS84 geodesic)", area_km2)

        if area_km2 < 0.005:
            return None, [], None, [], DataSourceCoverage(
                source="osm",
                status="error",
                message=f"Selected area ({area_km2:.4f} km²) is too small to contain road infrastructure. Minimum boundary is 0.01 km².",
            )

        if area_km2 > max_area_km2:
            return None, [], None, [], DataSourceCoverage(
                source="osm",
                status="error",
                message=f"Area {area_km2:.1f} km² exceeds maximum {max_area_km2} km². Draw a smaller polygon.",
            )

        # Configure OSMnx
        ox.settings.log_console = False
        ox.settings.use_cache = True
        ox.settings.overpass_rate_limit = False
        ox.settings.timeout = 25
        ox.settings.requests_timeout = 25
        ox.settings.http_user_agent = "Gativa-Traffic-Analysis/1.0"

        # Concurrently discover genuine street names & locality via TomTom
        discovered_streets, locality = await _discover_local_street_names(poly)

        G: Optional[nx.MultiDiGraph] = None
        source_channel = "osm_api_v06"
        cache_key = _get_polygon_cache_key(poly)

        # 1. Check local persistent SQLite cache
        try:
            cached_entry = await asyncio.to_thread(get_osm_cache_sync, cache_key)
            if cached_entry:
                cached_xml, meta = cached_entry
                with tempfile.NamedTemporaryFile(suffix=".osm", delete=False, mode="w", encoding="utf-8") as f:
                    f.write(cached_xml)
                    tmp_cache_path = f.name
                try:
                    G = await asyncio.to_thread(_parse_and_clip_xml, tmp_cache_path, poly)
                    if G is not None and G.number_of_edges() > 0:
                        source_channel = "osm_spatial_cache"
                        logger.info("Loaded road network from local spatial cache (%d edges)", G.number_of_edges())
                finally:
                    if os.path.exists(tmp_cache_path):
                        os.remove(tmp_cache_path)
        except Exception as exc:
            logger.debug("Spatial cache lookup encountered: %s", exc)

        # 2. Attempt official OpenStreetMap API v0.6 if not loaded from cache
        if G is None or G.number_of_edges() == 0:
            try:
                G, raw_xml = await _fetch_osm_graph_from_api(poly)
                if G is not None and G.number_of_edges() > 0 and raw_xml:
                    source_channel = "osm_api_v06"
                    meta = {
                        "area_km2": round(area_km2, 4),
                        "edges": G.number_of_edges(),
                        "nodes": G.number_of_nodes(),
                        "retrieval_method": "osm_api_v06",
                    }
                    await asyncio.to_thread(save_osm_cache_sync, cache_key, raw_xml, meta)
            except Exception as exc:
                logger.warning("OSM API v0.6 retrieval encountered error: %s", exc)

        # 3. If OSM API v0.6 did not return edges, attempt Overpass API with mirrors
        if G is None or G.number_of_edges() == 0:
            for endpoint in [
                "https://overpass.kumi.systems/api/interpreter",
                "https://overpass-api.de/api/interpreter",
                "https://overpass.private.coffee/api/interpreter",
            ]:
                try:
                    ox.settings.overpass_endpoint = endpoint
                    logger.info("Attempting Overpass retrieval via %s", endpoint)
                    G = await asyncio.wait_for(
                        asyncio.to_thread(ox.graph_from_polygon, poly, network_type="drive", simplify=True),
                        timeout=20.0,
                    )
                    if G is not None and G.number_of_edges() > 0:
                        source_channel = "osm_overpass"
                        break
                except Exception as exc:
                    logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)

        # 4. Strictly reject synthetic fallback in production
        if G is None or G.number_of_edges() == 0:
            logger.warning("No road network could be retrieved from OpenStreetMap API or Overpass mirrors.")
            return None, [], None, [], DataSourceCoverage(
                source="osm",
                status="error",
                message="OpenStreetMap data could not be retrieved for this area. Please verify network connectivity or adjust the polygon boundary.",
            )

        # ─── Build physical road segments list with canonical deduplication ───
        # In a directed MultiDiGraph, bidirectional streets have pairs (u, v) and (v, u).
        # We deduplicate into unique physical centerline segments so metrics, lengths, and visualizations reflect real roadways.
        seen_canonical_edges: set[tuple] = set()
        segments: list[RoadSegment] = []
        class_counts: dict[str, int] = {"highway": 0, "arterial": 0, "local": 0}
        total_length_m = 0.0

        for u, v, key, data in G.edges(keys=True, data=True):
            canonical_key = (min(u, v), max(u, v), key)
            if canonical_key in seen_canonical_edges:
                continue
            seen_canonical_edges.add(canonical_key)

            # Determine physical one-way status:
            # If oneway tag is True AND there is no reciprocal edge (v, u), it is one-way.
            is_oneway = bool(data.get("oneway", False)) and not G.has_edge(v, u)

            # Geometry extraction
            geom = data.get("geometry")
            if geom is None:
                u_data = G.nodes[u]
                v_data = G.nodes[v]
                if "x" in u_data and "y" in u_data and "x" in v_data and "y" in v_data:
                    geom = LineString([[u_data["x"], u_data["y"]], [v_data["x"], v_data["y"]]])

            # Clip geometry strictly to polygon boundary
            clipped_geom = _clip_geometry_to_polygon(geom, poly)
            if clipped_geom is None or clipped_geom.is_empty:
                continue

            length_m = _compute_geodesic_length_m(clipped_geom)
            if length_m < 1.0:
                continue

            coords_list = [[round(c[0], 6), round(c[1], 6)] for c in clipped_geom.coords]
            geojson_line = GeoJSONLineString(coordinates=coords_list)

            highway = data.get("highway", "unclassified")
            road_class = _classify_road(highway)
            osm_highway_str = highway[0] if isinstance(highway, list) else str(highway)
            osm_id_val = data.get("osmid")
            osm_id_str = str(osm_id_val[0]) if isinstance(osm_id_val, list) else str(osm_id_val or "")

            # Street Name
            name = data.get("name")
            if isinstance(name, list):
                name = name[0]
            if not name:
                loc_prefix = locality or "Corridor"
                if road_class == "highway":
                    name = f"{loc_prefix} Expressway Corridor"
                elif road_class == "arterial":
                    name = f"{loc_prefix} Primary Arterial Corridor"
                else:
                    hw_tag = data.get("highway")
                    if isinstance(hw_tag, list):
                        hw_tag = hw_tag[0]
                    if hw_tag == "residential":
                        name = f"{loc_prefix} Residential Way"
                    elif hw_tag in ("tertiary", "tertiary_link"):
                        name = f"{loc_prefix} Collector Marg"
                    else:
                        name = f"{loc_prefix} Sector Street"

            u_ctrl, u_prov = _inspect_node_control(G.nodes[u] if u in G.nodes else {}, data)
            v_ctrl, v_prov = _inspect_node_control(G.nodes[v] if v in G.nodes else {}, data)

            segments.append(RoadSegment(
                segment_id=f"{u}_{v}_{key}",
                name=name,
                road_type=road_class,
                length_m=round(length_m, 1),
                geometry=geojson_line,
                speed_limit_kmh=_get_speed_limit(data),
                lanes=_get_lanes(data),
                is_oneway=is_oneway,
                osm_highway=osm_highway_str,
                osm_id=osm_id_str,
                u_control=u_ctrl,
                v_control=v_ctrl,
                u_provenance=u_prov,
                v_provenance=v_prov,
            ))

            class_counts[road_class] = class_counts.get(road_class, 0) + 1
            total_length_m += length_m

        total_length_km = round(total_length_m / 1000.0, 2)

        # ─── Network metrics (Authentic junction controls) ───────────────────
        signalized_nodes = set()
        unsignalized_nodes = set()
        for n in G.nodes:
            if G.degree(n) >= 2:
                n_ctrl, _ = _inspect_node_control(G.nodes[n])
                if n_ctrl == "traffic_signal":
                    signalized_nodes.add(n)
                else:
                    unsignalized_nodes.add(n)

        signalized_intersection_count = len(signalized_nodes)
        unsignalized_intersection_count = len(unsignalized_nodes)
        intersection_count = sum(1 for n in G.nodes if G.degree(n) >= 3)
        bottlenecks = _detect_structural_bottlenecks(G, locality=locality)

        metrics = RoadNetworkMetrics(
            total_segments=len(segments),
            highway_count=class_counts.get("highway", 0),
            arterial_count=class_counts.get("arterial", 0),
            local_count=class_counts.get("local", 0),
            total_length_km=total_length_km,
            road_density_km_per_km2=round(total_length_km / area_km2, 2) if area_km2 > 0 else 0.0,
            intersection_count=intersection_count,
            potential_bottleneck_count=len(bottlenecks),
            area_km2=round(area_km2, 3),
            road_class_distribution={
                "Highway": class_counts.get("highway", 0),
                "Arterial": class_counts.get("arterial", 0),
                "Local": class_counts.get("local", 0),
            },
            signalized_intersection_count=signalized_intersection_count,
            unsignalized_intersection_count=unsignalized_intersection_count,
        )

        coverage = DataSourceCoverage(
            source="osm",
            status="ok",
            message=f"Retrieved {len(segments)} genuine physical road segments from OpenStreetMap ({source_channel})",
        )

        logger.info(
            "OSM road network: %d physical segments (Highways: %d, Arterials: %d, Local: %d), %.2f km total, area: %.2f km², density: %.2f km/km²",
            len(segments),
            class_counts.get("highway", 0),
            class_counts.get("arterial", 0),
            class_counts.get("local", 0),
            total_length_km,
            area_km2,
            metrics.road_density_km_per_km2,
        )
        return G, segments, metrics, bottlenecks, coverage

    except Exception as exc:
        logger.exception("OSMnx road network fetch failed")
        return None, [], None, [], DataSourceCoverage(
            source="osm",
            status="error",
            message=f"Failed to retrieve road network from OpenStreetMap: {exc}",
        )


def _detect_structural_bottlenecks(
    G: nx.MultiDiGraph,
    locality: str = "",
) -> list[BottleneckCandidate]:
    """
    Detect potential structural bottleneck nodes using betweenness centrality.
    Calculates correct statistical percentile ranks (e.g. 'Top 1% of network nodes').
    Applies spatial deduplication to ensure distinct physical chokepoints across the corridor.
    """
    bottlenecks: list[BottleneckCandidate] = []

    if G.number_of_nodes() < 3:
        return bottlenecks

    try:
        UG = G.to_undirected()

        # Sample nodes for large networks to bound computation time
        k = min(500, G.number_of_nodes())
        centrality = nx.betweenness_centrality(UG, k=k, normalized=True, seed=42)
        degree = dict(G.degree())

        if not centrality:
            return bottlenecks

        max_centrality = max(centrality.values())
        if max_centrality == 0:
            return bottlenecks

        # Threshold: top of betweenness AND degree >= 3
        threshold = max_centrality * 0.35

        candidate_nodes = [
            (node, score)
            for node, score in centrality.items()
            if score >= threshold and degree.get(node, 0) >= 3
        ]
        candidate_nodes.sort(key=lambda x: x[1], reverse=True)

        # Spatial deduplication: ensure bottlenecks are at least ~100-120m apart (0.001 deg)
        deduped_candidates: list[tuple[int, float, float, float]] = []
        for node, score in candidate_nodes:
            node_data = G.nodes[node]
            lat = node_data.get("y", 0.0)
            lng = node_data.get("x", 0.0)
            too_close = False
            for _, _, flat, flng in deduped_candidates:
                if math.hypot(lat - flat, lng - flng) < 0.0010:  # ~110m
                    too_close = True
                    break
            if not too_close:
                deduped_candidates.append((node, score, lat, lng))
                if len(deduped_candidates) >= 10:
                    break

        total_nodes = len(centrality)
        for node, score, lat, lng in deduped_candidates:
            deg = degree.get(node, 0)

            # Discover street/road names meeting at this intersection
            incident_names = []
            for _, v, d in G.out_edges(node, data=True):
                nm = d.get("name")
                if nm:
                    if isinstance(nm, list):
                        incident_names.extend(nm)
                    else:
                        incident_names.append(nm)
            for u, _, d in G.in_edges(node, data=True):
                nm = d.get("name")
                if nm:
                    if isinstance(nm, list):
                        incident_names.extend(nm)
                    else:
                        incident_names.append(nm)

            # Check 1-hop neighbor edges if no direct names
            if not incident_names:
                for nbr in list(G.neighbors(node))[:4]:
                    for _, _, d in G.edges(nbr, data=True):
                        nm = d.get("name")
                        if nm:
                            if isinstance(nm, list):
                                incident_names.extend(nm)
                            else:
                                incident_names.append(nm)
                            break

            unique_names = []
            for nm in incident_names:
                clean_nm = str(nm).strip()
                if clean_nm and clean_nm not in unique_names:
                    unique_names.append(clean_nm)

            if len(unique_names) >= 2:
                loc_name = f"{unique_names[0]} & {unique_names[1]} Junction"
            elif len(unique_names) == 1:
                loc_name = f"{unique_names[0]} Chauraha (Node #{node})"
            else:
                loc_name = f"{locality or 'Sector'} Interchange Node #{node} ({deg} Approaches)"

            severity: str
            if score >= max_centrality * 0.75:
                severity = "high"
            elif score >= max_centrality * 0.5:
                severity = "medium"
            else:
                severity = "low"

            # Compute rank percentile (Top X% of network nodes)
            nodes_higher_or_equal = sum(1 for val in centrality.values() if val >= score)
            pct_rank = max(1, round((nodes_higher_or_equal / total_nodes) * 100))

            evidence_items = []
            if unique_names:
                evidence_items.append(f"Major crossroads: {', '.join(unique_names[:3])}")
            evidence_items.extend([
                f"Betweenness centrality score: {score:.3f} (Top {pct_rank}% of network nodes)",
                f"Intersection degree: {deg} connecting roads",
                "High network centrality indicates severe traffic convergence",
            ])

            bottlenecks.append(BottleneckCandidate(
                segment_id=f"node_{node}",
                location_name=loc_name,
                lat=lat,
                lng=lng,
                bottleneck_type="network_structural",
                severity=severity,
                evidence=evidence_items,
                centrality_score=round(score, 4),
                speed_reduction=None,
            ))

        return bottlenecks

    except Exception as exc:
        logger.warning("Bottleneck detection failed: %s", exc)
        return []
