"""
Spatial Generator — pure Shapely/GeoPandas computation.
No database access. GeoJSON dicts in, GeoJSON dicts out.
"""
import math
import logging
from typing import Any, Dict, List, Optional

import numpy as np
from shapely.geometry import shape, mapping, Point, Polygon, MultiPolygon
from shapely.ops import unary_union, transform as shapely_transform
import pyproj

logger = logging.getLogger(__name__)


def _project_to_25833():
    return pyproj.Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True).transform


def _project_to_4326():
    return pyproj.Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True).transform


def voronoi_from_points(features: Dict, clip_geojson: Optional[Dict] = None) -> Dict:
    from scipy.spatial import Voronoi

    pts_list = [
        (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1])
        for f in features["features"]
        if f.get("geometry", {}).get("type") == "Point"
    ]
    props_list = [f.get("properties", {}) for f in features["features"]
                  if f.get("geometry", {}).get("type") == "Point"]

    if len(pts_list) < 4:
        raise ValueError("Need at least 4 points for Voronoi diagram")

    pts = np.array(pts_list)
    center = pts.mean(axis=0)
    span = pts.max(axis=0) - pts.min(axis=0) + 1e-6
    mirrors = np.array([
        center + [span[0] * 10, 0],
        center + [-span[0] * 10, 0],
        center + [0, span[1] * 10],
        center + [0, -span[1] * 10],
    ])
    all_pts = np.vstack([pts, mirrors])

    vor = Voronoi(all_pts)
    clip_shape = shape(clip_geojson) if clip_geojson else None

    result_features = []
    for i, region_idx in enumerate(vor.point_region[: len(pts_list)]):
        region = vor.regions[region_idx]
        if -1 in region or not region:
            continue
        vertices = [vor.vertices[v] for v in region]
        try:
            poly = Polygon(vertices)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if clip_shape is not None:
                poly = poly.intersection(clip_shape)
            if poly.is_empty:
                continue
            result_features.append({
                "type": "Feature",
                "geometry": mapping(poly),
                "properties": {**props_list[i], "voronoi_id": i},
            })
        except Exception as e:
            logger.debug(f"Skipped Voronoi region {i}: {e}")
            continue

    return {"type": "FeatureCollection", "features": result_features}


def hexagonal_grid(bbox: Dict, cell_size_m: float) -> Dict:
    lat_c = (bbox["min_lat"] + bbox["max_lat"]) / 2
    m_per_deg_lon = 111320 * math.cos(math.radians(lat_c))
    m_per_deg_lat = 111320.0
    dx = cell_size_m * math.sqrt(3) / 2 / m_per_deg_lat
    dy = cell_size_m / m_per_deg_lon

    hexagons = []
    row = 0
    lat = bbox["min_lat"]
    while lat <= bbox["max_lat"] + dx:
        offset = dy / 2 if row % 2 else 0.0
        lon = bbox["min_lon"] - offset
        col = 0
        while lon <= bbox["max_lon"] + dy:
            if lon <= bbox["max_lon"] + dy / 2:
                r = dy / math.sqrt(3)
                angles = [math.radians(60 * k + 30) for k in range(6)]
                coords = [(lon + r * math.cos(a), lat + r * math.sin(a)) for a in angles]
                hexagons.append({
                    "type": "Feature",
                    "geometry": mapping(Polygon(coords)),
                    "properties": {"hex_id": f"{row}_{col}", "score": 0.0},
                })
            lon += dy
            col += 1
        lat += dx
        row += 1

    return {"type": "FeatureCollection", "features": hexagons}


def convex_hull(features: Dict) -> Dict:
    geoms = [
        shape(f["geometry"])
        for f in features["features"]
        if f.get("geometry")
    ]
    if not geoms:
        raise ValueError("No valid geometries in FeatureCollection")

    hull = unary_union(geoms).convex_hull
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": mapping(hull),
            "properties": {"feature_count": len(geoms)},
        }],
    }


def corridor(linestring_geojson: Dict, width_m: float) -> Dict:
    geom = shape(linestring_geojson)
    projected = shapely_transform(_project_to_25833(), geom)
    buffered = projected.buffer(width_m / 2, cap_style=2)
    result = shapely_transform(_project_to_4326(), buffered)
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": mapping(result),
            "properties": {"width_m": width_m},
        }],
    }


def coverage_gaps(service_features: Dict, clip_geojson: Dict, radius_m: float) -> Dict:
    project_to = _project_to_25833()
    project_back = _project_to_4326()

    clip = shapely_transform(project_to, shape(clip_geojson))

    buffers = []
    for f in service_features["features"]:
        if not f.get("geometry"):
            continue
        geom_proj = shapely_transform(project_to, shape(f["geometry"]))
        buffers.append(geom_proj.buffer(radius_m))

    if not buffers:
        gap = clip
    else:
        covered = unary_union(buffers)
        gap = clip.difference(covered)

    if gap.is_empty:
        return {"type": "FeatureCollection", "features": []}

    gap_wgs84 = shapely_transform(project_back, gap)
    geoms = list(gap_wgs84.geoms) if hasattr(gap_wgs84, "geoms") else [gap_wgs84]

    features = []
    for g in geoms:
        if g.area < 1e-8:
            continue
        features.append({
            "type": "Feature",
            "geometry": mapping(g),
            "properties": {"gap": True},
        })

    return {"type": "FeatureCollection", "features": features}


def site_suitability(grid_features: Dict, criteria_scores: List[Dict]) -> Dict:
    n = len(grid_features["features"])
    if n == 0:
        return grid_features

    total = np.zeros(n)

    for crit in criteria_scores:
        if len(crit["scores"]) != n:
            raise ValueError(
                f"Criterion scores length {len(crit['scores'])} does not match grid size {n}"
            )
        raw = np.array(crit["scores"], dtype=float)
        weight = float(crit.get("weight", 1.0))
        direction = crit.get("direction", "near")

        lo, hi = raw.min(), raw.max()
        norm = (raw - lo) / (hi - lo) if hi > lo else np.zeros(n)

        if direction == "near":
            norm = 1.0 - norm

        total += weight * norm

    max_total = total.max()
    if max_total > 0:
        total /= max_total

    out_features = []
    for f, score in zip(grid_features["features"], total):
        out_features.append({
            **f,
            "properties": {**f.get("properties", {}), "suitability_score": round(float(score), 4)},
        })

    out_features.sort(key=lambda x: x["properties"]["suitability_score"], reverse=True)
    return {"type": "FeatureCollection", "features": out_features}


def kernel_density(point_features: Dict, grid_features: Dict, bandwidth: Optional[float] = None) -> Dict:
    from scipy.stats import gaussian_kde

    pts = np.array([
        [f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1]]
        for f in point_features["features"]
        if f.get("geometry", {}).get("type") == "Point"
    ])

    if len(pts) < 2:
        return grid_features

    try:
        kde = gaussian_kde(pts.T, bw_method=bandwidth)
    except np.linalg.LinAlgError:
        # Singular covariance (e.g. collinear points) — return uniform scores
        logger.warning("kernel_density: singular covariance, returning uniform scores")
        return {
            "type": "FeatureCollection",
            "features": [
                {**f, "properties": {**f.get("properties", {}), "score": 0.5}}
                for f in grid_features["features"]
            ],
        }

    valid_features = []
    centroid_coords = []
    for f in grid_features["features"]:
        try:
            c = shape(f["geometry"]).centroid
            centroid_coords.append([c.x, c.y])
            valid_features.append(f)
        except Exception as e:
            logger.debug(f"Skipped invalid geometry in kernel_density: {e}")

    if not centroid_coords:
        return grid_features

    centroids = np.array(centroid_coords).T
    densities = kde(centroids)
    d_min, d_max = densities.min(), densities.max()
    normalized = (densities - d_min) / (d_max - d_min) if d_max > d_min else np.zeros(len(densities))

    out_features = []
    for f, score in zip(valid_features, normalized):
        out_features.append({
            **f,
            "properties": {**f.get("properties", {}), "score": round(float(score), 4)},
        })

    return {"type": "FeatureCollection", "features": out_features}


def equity_gap_analysis(district_data: List[Dict], service_col: str,
                        population_col: Optional[str] = None) -> Dict:
    counts = np.array([d.get(service_col, 0) for d in district_data], dtype=float)

    if population_col:
        pops = np.array([
            max(float(d.get(population_col, 1) or 1), 1)
            for d in district_data
        ], dtype=float)
        rates = counts / pops * 10_000
    else:
        rates = counts.copy()

    mean_rate = rates.mean()
    threshold = mean_rate - 0.5 * rates.std()

    features = []
    for d, rate in zip(district_data, rates):
        features.append({
            "type": "Feature",
            "geometry": d["geometry"],
            "properties": {
                "name": d.get("name", ""),
                service_col: d.get(service_col, 0),
                "rate_per_10k": round(float(rate), 3) if population_col else None,
                "equity_score": round(float(rate / mean_rate), 3) if mean_rate > 0 else 0.0,
                "underserved": bool(rate < threshold),
            },
        })

    return {"type": "FeatureCollection", "features": features}
