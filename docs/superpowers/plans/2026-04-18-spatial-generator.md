# Spatial Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 12 generative/analytical spatial tools to the agent — Voronoi zones, hex grids, kernel density, suitability scoring, coverage gaps, equity analysis, scenario planning — all backed by Shapely/GeoPandas with results persisted to `temp_layers` in PostGIS.

**Architecture:** A new `app/utils/spatial_generator.py` module contains pure Shapely/GeoPandas functions (no DB access, GeoJSON in → GeoJSON out). Tool wrapper functions in `app/utils/agent_tools.py` fetch data from PostGIS, call `spatial_generator`, and save results back via `GeoDataFrame.to_postgis()`. The agent's system prompt in `agent_orchestrator.py` is updated so the LLM knows when to call each new tool.

**Tech Stack:** shapely 2.0, geopandas 0.14, scipy 1.11, pyproj 3.6 — all already in `requirements.txt`. No new deps needed.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/utils/spatial_generator.py` | **CREATE** | Pure Shapely/GeoPandas computation — no DB |
| `app/utils/agent_tools.py` | **MODIFY** | Add 12 tool wrapper functions + update TOOL_REGISTRY |
| `app/utils/agent_orchestrator.py` | **MODIFY** | Add new tools to agent system prompt |
| `tests/test_spatial_generator.py` | **CREATE** | Unit tests for pure functions (no DB needed) |
| `tests/test_agent_tools.py` | **MODIFY** | Add tests for new tool wrappers + fix stale registry test |

---

## Task 1: Create `spatial_generator.py` — geometry generation

**Files:**
- Create: `app/utils/spatial_generator.py`
- Create: `tests/test_spatial_generator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spatial_generator.py`:

```python
import pytest
from app.utils.spatial_generator import (
    voronoi_from_points,
    hexagonal_grid,
    convex_hull,
    corridor,
)


def _point_fc(coords_list):
    """Helper: build a GeoJSON FeatureCollection of Points."""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
             "properties": {"id": i}}
            for i, (lon, lat) in enumerate(coords_list)
        ],
    }


BERLIN_HOSPITALS = [
    (13.3770, 52.5200), (13.4050, 52.5170), (13.4280, 52.5300),
    (13.3900, 52.5050), (13.4500, 52.5100), (13.3600, 52.5350),
]

BERLIN_BBOX = {"min_lon": 13.088, "min_lat": 52.338, "max_lon": 13.761, "max_lat": 52.675}


def test_voronoi_returns_feature_collection():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = voronoi_from_points(fc)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0


def test_voronoi_polygons_are_polygons():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = voronoi_from_points(fc)
    for f in result["features"]:
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_voronoi_clips_to_boundary():
    fc = _point_fc(BERLIN_HOSPITALS)
    clip = {
        "type": "Polygon",
        "coordinates": [[[13.3, 52.45], [13.5, 52.45], [13.5, 52.55], [13.3, 52.55], [13.3, 52.45]]]
    }
    result = voronoi_from_points(fc, clip_geojson=clip)
    from shapely.geometry import shape
    clip_shape = shape(clip)
    for f in result["features"]:
        poly = shape(f["geometry"])
        assert clip_shape.contains(poly) or clip_shape.intersects(poly)


def test_voronoi_requires_4_points():
    fc = _point_fc([(13.4, 52.5), (13.41, 52.51), (13.42, 52.52)])
    with pytest.raises(ValueError, match="4 points"):
        voronoi_from_points(fc)


def test_hexgrid_returns_hexagons():
    result = hexagonal_grid(BERLIN_BBOX, cell_size_m=1000)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0
    for f in result["features"]:
        assert f["geometry"]["type"] == "Polygon"
        assert "hex_id" in f["properties"]
        assert "score" in f["properties"]


def test_hexgrid_cells_cover_bbox():
    result = hexagonal_grid(BERLIN_BBOX, cell_size_m=5000)
    from shapely.geometry import shape
    centroids_lons = [shape(f["geometry"]).centroid.x for f in result["features"]]
    assert min(centroids_lons) >= BERLIN_BBOX["min_lon"] - 0.05
    assert max(centroids_lons) <= BERLIN_BBOX["max_lon"] + 0.05


def test_convex_hull_returns_single_polygon():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = convex_hull(fc)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_convex_hull_contains_all_points():
    pts = BERLIN_HOSPITALS
    fc = _point_fc(pts)
    result = convex_hull(fc)
    from shapely.geometry import shape, Point
    hull = shape(result["features"][0]["geometry"])
    for lon, lat in pts:
        assert hull.contains(Point(lon, lat)) or hull.touches(Point(lon, lat))


def test_corridor_returns_polygon():
    line = {
        "type": "LineString",
        "coordinates": [[13.38, 52.52], [13.40, 52.52], [13.42, 52.52]]
    }
    result = corridor(line, width_m=200)
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert result["features"][0]["properties"]["width_m"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/AI-Geospatial
pytest tests/test_spatial_generator.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'voronoi_from_points'`

- [ ] **Step 3: Create `app/utils/spatial_generator.py`**

```python
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


# ---------------------------------------------------------------------------
# A — Geometry Generation
# ---------------------------------------------------------------------------

def voronoi_from_points(features: Dict, clip_geojson: Optional[Dict] = None) -> Dict:
    """
    Generate Voronoi polygons from a GeoJSON FeatureCollection of Points.

    Args:
        features: GeoJSON FeatureCollection (Points only)
        clip_geojson: optional GeoJSON Polygon/MultiPolygon to clip the result

    Returns:
        GeoJSON FeatureCollection of Polygons
    """
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
    # Add far-away mirror points to close open Voronoi regions
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
        except Exception:
            continue

    return {"type": "FeatureCollection", "features": result_features}


def hexagonal_grid(bbox: Dict, cell_size_m: float) -> Dict:
    """
    Generate a hexagonal grid covering a bounding box.

    Args:
        bbox: {"min_lon", "min_lat", "max_lon", "max_lat"}
        cell_size_m: approximate hex cell width in metres

    Returns:
        GeoJSON FeatureCollection of Polygons, each with hex_id and score=0.0
    """
    lat_c = (bbox["min_lat"] + bbox["max_lat"]) / 2
    # metres → degrees at this latitude
    m_per_deg_lon = 111320 * math.cos(math.radians(lat_c))
    m_per_deg_lat = 111320.0
    dx = cell_size_m / m_per_deg_lon
    dy = cell_size_m * math.sqrt(3) / 2 / m_per_deg_lat

    hexagons = []
    row = 0
    lat = bbox["min_lat"]
    while lat <= bbox["max_lat"] + dy:
        offset = dx / 2 if row % 2 else 0.0
        lon = bbox["min_lon"] - offset
        col = 0
        while lon <= bbox["max_lon"] + dx:
            r = dx / 2
            angles = [math.radians(60 * k + 30) for k in range(6)]
            coords = [(lon + r * math.cos(a), lat + r * math.sin(a)) for a in angles]
            hexagons.append({
                "type": "Feature",
                "geometry": mapping(Polygon(coords)),
                "properties": {"hex_id": f"{row}_{col}", "score": 0.0},
            })
            lon += dx
            col += 1
        lat += dy
        row += 1

    return {"type": "FeatureCollection", "features": hexagons}


def convex_hull(features: Dict) -> Dict:
    """
    Return the convex hull of all geometries in a FeatureCollection.

    Args:
        features: GeoJSON FeatureCollection

    Returns:
        GeoJSON FeatureCollection with a single Polygon feature
    """
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
    """
    Buffer a LineString by width_m/2 on each side to create a corridor polygon.
    Projects to EPSG:25833 for accurate metre-based buffering.

    Args:
        linestring_geojson: GeoJSON LineString geometry
        width_m: total corridor width in metres

    Returns:
        GeoJSON FeatureCollection with a single Polygon feature
    """
    geom = shape(linestring_geojson)
    projected = shapely_transform(_project_to_25833(), geom)
    buffered = projected.buffer(width_m / 2, cap_style=2)  # flat caps
    result = shapely_transform(_project_to_4326(), buffered)
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": mapping(result),
            "properties": {"width_m": width_m},
        }],
    }


# ---------------------------------------------------------------------------
# B — Suitability & Coverage
# ---------------------------------------------------------------------------

def coverage_gaps(service_features: Dict, clip_geojson: Dict, radius_m: float) -> Dict:
    """
    Find areas within clip_geojson that are NOT within radius_m of any service point.
    Projects to EPSG:25833 for accurate buffering, returns result in EPSG:4326.

    Args:
        service_features: GeoJSON FeatureCollection of service locations
        clip_geojson: GeoJSON Polygon/MultiPolygon bounding the study area
        radius_m: service radius in metres

    Returns:
        GeoJSON FeatureCollection of gap polygons
    """
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
    """
    Score hex grid cells using pre-computed per-criterion distance arrays.

    Args:
        grid_features: GeoJSON FeatureCollection (hex grid from hexagonal_grid())
        criteria_scores: list of dicts, each with:
            - "scores": list[float] — one value per grid cell (e.g. distance to nearest service)
            - "weight": float — relative importance (default 1.0)
            - "direction": "near"|"far" — "near" means lower score = better (invert normalization)

    Returns:
        GeoJSON FeatureCollection with "suitability_score" property added, sorted best-first
    """
    n = len(grid_features["features"])
    if n == 0:
        return grid_features

    total = np.zeros(n)

    for crit in criteria_scores:
        raw = np.array(crit["scores"], dtype=float)
        weight = float(crit.get("weight", 1.0))
        direction = crit.get("direction", "near")

        lo, hi = raw.min(), raw.max()
        norm = (raw - lo) / (hi - lo) if hi > lo else np.zeros(n)

        if direction == "near":
            norm = 1.0 - norm  # closer = higher score

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


# ---------------------------------------------------------------------------
# C — Analytical Surfaces
# ---------------------------------------------------------------------------

def kernel_density(point_features: Dict, grid_features: Dict, bandwidth: Optional[float] = None) -> Dict:
    """
    Score each hex cell by kernel density estimate of point_features.

    Args:
        point_features: GeoJSON FeatureCollection of Points
        grid_features: GeoJSON FeatureCollection (hex grid from hexagonal_grid())
        bandwidth: KDE bandwidth in degrees (auto-computed if None)

    Returns:
        grid_features with "score" property updated to normalized density (0–1)
    """
    from scipy.stats import gaussian_kde

    pts = np.array([
        [f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1]]
        for f in point_features["features"]
        if f.get("geometry", {}).get("type") == "Point"
    ])

    if len(pts) < 2:
        return grid_features

    kde = gaussian_kde(pts.T, bw_method=bandwidth)

    centroids = np.array([
        [shape(f["geometry"]).centroid.x, shape(f["geometry"]).centroid.y]
        for f in grid_features["features"]
    ]).T

    densities = kde(centroids)
    d_min, d_max = densities.min(), densities.max()
    normalized = (densities - d_min) / (d_max - d_min) if d_max > d_min else np.zeros(len(densities))

    out_features = []
    for f, score in zip(grid_features["features"], normalized):
        out_features.append({
            **f,
            "properties": {**f.get("properties", {}), "score": round(float(score), 4)},
        })

    return {"type": "FeatureCollection", "features": out_features}


def equity_gap_analysis(district_data: List[Dict], service_col: str,
                        population_col: Optional[str] = None) -> Dict:
    """
    Flag statistically underserved districts by comparing service rates.

    Args:
        district_data: list of dicts, each with:
            - "name": str
            - "geometry": GeoJSON geometry dict
            - service_col (e.g. "hospital_count"): int
            - population_col (optional): int — used to compute per-capita rate
        service_col: key in each dict holding the service count
        population_col: key holding population count (optional)

    Returns:
        GeoJSON FeatureCollection — each district has equity_score + underserved flag
    """
    counts = np.array([d.get(service_col, 0) for d in district_data], dtype=float)

    if population_col:
        pops = np.array([max(d.get(population_col, 1), 1) for d in district_data], dtype=float)
        rates = counts / pops * 10_000  # services per 10k population
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
```

- [ ] **Step 4: Run tests — all should pass**

```bash
pytest tests/test_spatial_generator.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/spatial_generator.py tests/test_spatial_generator.py
git commit -m "feat: add spatial_generator module with voronoi, hexgrid, hull, corridor, coverage_gaps, site_suitability, kernel_density, equity_gap_analysis"
```

---

## Task 2: Add geometry + persistence tools to `agent_tools.py`

**Files:**
- Modify: `app/utils/agent_tools.py`
- Modify: `tests/test_agent_tools.py`

These tools: `generate_voronoi`, `generate_hexgrid`, `generate_convex_hull`, `generate_corridor`, `save_generated_layer`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_tools.py`:

```python
import geopandas as gpd
from unittest.mock import patch, MagicMock
from app.utils.agent_tools import (
    generate_voronoi,
    generate_hexgrid,
    generate_convex_hull,
    generate_corridor,
    save_generated_layer,
)


MOCK_HOSPITAL_DF = None  # set up in each test via pd.DataFrame


def _mock_hospital_rows():
    import pandas as pd
    return pd.DataFrame([
        {"id": i, "geom": f'{{"type":"Point","coordinates":[{13.38 + i*0.01},{52.52}]}}'}
        for i in range(6)
    ])


def test_generate_voronoi_returns_feature_collection():
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("app.utils.agent_tools.save_generated_layer") as mock_save:
        mock_db.execute_query.return_value = _mock_hospital_rows()
        mock_save.return_value = {"saved": True, "table": "temp_layers.layer_voronoi_x",
                                   "feature_count": 5, "geojson": {"type": "FeatureCollection", "features": []}}
        result = generate_voronoi("public.osm_hospitals", id_col="id")
    assert "error" not in result or result.get("saved")


def test_generate_hexgrid_returns_feature_collection():
    result = generate_hexgrid(
        {"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55},
        cell_size_m=1000,
    )
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0


def test_generate_convex_hull_returns_polygon():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = _mock_hospital_rows()
        result = generate_convex_hull("public.osm_hospitals")
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_generate_corridor_returns_polygon():
    result = generate_corridor(
        {"type": "LineString", "coordinates": [[13.38, 52.52], [13.42, 52.52]]},
        width_m=200,
    )
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_save_generated_layer_writes_to_postgis():
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
            "properties": {"name": "test"},
        }],
    }
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("geopandas.GeoDataFrame.to_postgis") as mock_postgis:
        mock_db.engine = MagicMock()
        result = save_generated_layer(fc, "test_layer", "A test layer")
    mock_postgis.assert_called_once()
    assert result["saved"] is True
    assert "table" in result


def test_save_generated_layer_empty_fc_returns_error():
    result = save_generated_layer({"type": "FeatureCollection", "features": []}, "empty")
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_tools.py::test_generate_voronoi_returns_feature_collection \
       tests/test_agent_tools.py::test_generate_hexgrid_returns_feature_collection \
       tests/test_agent_tools.py::test_save_generated_layer_writes_to_postgis -v
```

Expected: `ImportError: cannot import name 'generate_voronoi'`

- [ ] **Step 3: Add `save_generated_layer` + geometry tools to `agent_tools.py`**

Add these imports at the top of `agent_tools.py` (after existing imports):

```python
import hashlib
import geopandas as gpd
from app.utils.spatial_generator import (
    voronoi_from_points,
    hexagonal_grid as _hexagonal_grid,
    convex_hull as _convex_hull,
    corridor as _corridor,
    coverage_gaps as _coverage_gaps,
    site_suitability as _site_suitability,
    kernel_density as _kernel_density,
    equity_gap_analysis as _equity_gap_analysis,
)
```

Add these functions before the TOOL_REGISTRY block:

```python
def save_generated_layer(geojson: Dict[str, Any], layer_name: str,
                         description: str = "") -> Dict[str, Any]:
    """
    Persist a GeoJSON FeatureCollection to the temp_layers schema in PostGIS.

    Args:
        geojson: GeoJSON FeatureCollection
        layer_name: human-readable name (will be sanitized + hashed for uniqueness)
        description: optional description stored in properties

    Returns:
        {"saved": True, "table": "temp_layers.<name>", "feature_count": int, "geojson": ...}
        or {"error": str}
    """
    try:
        features = geojson.get("features", [])
        if not features:
            return {"error": "No features to save"}

        geometries = [shape(f["geometry"]) for f in features if f.get("geometry")]
        props = [f.get("properties", {}) for f in features if f.get("geometry")]

        gdf = gpd.GeoDataFrame(props, geometry=geometries, crs="EPSG:4326")
        gdf["geom_25833"] = gdf.geometry.to_crs("EPSG:25833")
        gdf = gdf.set_geometry("geom_25833")
        gdf = gdf.drop(columns=["geometry"], errors="ignore")

        safe = layer_name.lower().replace(" ", "_").replace("-", "_")
        safe = "".join(c for c in safe if c.isalnum() or c == "_")[:40]
        suffix = hashlib.md5(safe.encode()).hexdigest()[:8]
        table_name = f"layer_{safe}_{suffix}"

        if not db_manager.engine:
            db_manager.initialize()

        gdf.to_postgis(table_name, db_manager.engine,
                       schema="temp_layers", if_exists="replace", index=False)

        return {
            "saved": True,
            "table": f"temp_layers.{table_name}",
            "feature_count": len(features),
            "geojson": geojson,
            "description": description,
        }
    except Exception as e:
        logger.error(f"save_generated_layer error: {e}")
        return {"error": str(e)}


def generate_voronoi(table: str, id_col: str = "id",
                     clip_table: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate Voronoi polygons from a PostGIS point table.

    Args:
        table: fully-qualified table name (e.g. "public.osm_hospitals")
        id_col: primary key column name
        clip_table: optional table whose union geometry clips the result

    Returns:
        {"saved": True, "table": str, "feature_count": int, "geojson": FeatureCollection}
        or {"error": str}
    """
    try:
        df = db_manager.execute_query(
            f"SELECT {id_col}, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {table}"
        )
        if df is None or df.empty:
            return {"error": f"No features in {table}"}

        features = []
        for _, row in df.iterrows():
            geom = json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"]
            if geom.get("type") != "Point":
                continue
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {id_col: row[id_col]},
            })
        point_fc = {"type": "FeatureCollection", "features": features}

        clip_geojson = None
        if clip_table:
            clip_df = db_manager.execute_query(
                f"SELECT ST_AsGeoJSON(ST_Transform(ST_Union(geom_25833),4326)) AS geom FROM {clip_table}"
            )
            if clip_df is not None and not clip_df.empty:
                raw = clip_df.iloc[0]["geom"]
                clip_geojson = json.loads(raw) if isinstance(raw, str) else raw

        result_fc = voronoi_from_points(point_fc, clip_geojson)
        layer_name = f"voronoi_{table.split('.')[-1]}"
        return save_generated_layer(result_fc, layer_name, f"Voronoi zones for {table}")
    except Exception as e:
        logger.error(f"generate_voronoi error: {e}")
        return {"error": str(e)}


def generate_hexgrid(bbox: Dict[str, float], cell_size_m: float) -> Dict[str, Any]:
    """
    Generate a hexagonal grid over a bounding box.

    Args:
        bbox: {"min_lon", "min_lat", "max_lon", "max_lat"}
        cell_size_m: approximate hex cell width in metres

    Returns:
        GeoJSON FeatureCollection (not saved to DB — used as input to other tools)
    """
    try:
        return _hexagonal_grid(bbox, cell_size_m)
    except Exception as e:
        logger.error(f"generate_hexgrid error: {e}")
        return {"error": str(e)}


def generate_convex_hull(table: str) -> Dict[str, Any]:
    """
    Return the convex hull of all geometries in a PostGIS table.

    Args:
        table: fully-qualified table name

    Returns:
        GeoJSON FeatureCollection with a single Polygon
        or {"error": str}
    """
    try:
        df = db_manager.execute_query(
            f"SELECT ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {table}"
        )
        if df is None or df.empty:
            return {"error": f"No features in {table}"}

        features = [
            {"type": "Feature",
             "geometry": json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"],
             "properties": {}}
            for _, row in df.iterrows()
        ]
        fc = {"type": "FeatureCollection", "features": features}
        return _convex_hull(fc)
    except Exception as e:
        logger.error(f"generate_convex_hull error: {e}")
        return {"error": str(e)}


def generate_corridor(linestring_geojson: Dict[str, Any], width_m: float) -> Dict[str, Any]:
    """
    Buffer a LineString to create a corridor polygon.

    Args:
        linestring_geojson: GeoJSON LineString geometry dict
        width_m: total corridor width in metres

    Returns:
        GeoJSON FeatureCollection with a single Polygon
        or {"error": str}
    """
    try:
        return _corridor(linestring_geojson, width_m)
    except Exception as e:
        logger.error(f"generate_corridor error: {e}")
        return {"error": str(e)}
```

- [ ] **Step 4: Run tests — all should pass**

```bash
pytest tests/test_agent_tools.py -v -k "voronoi or hexgrid or convex or corridor or save_generated"
```

Expected: all new tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: add geometry generation tools to agent_tools (voronoi, hexgrid, hull, corridor, save_generated_layer)"
```

---

## Task 3: Add suitability, density, and equity tools to `agent_tools.py`

**Files:**
- Modify: `app/utils/agent_tools.py`
- Modify: `tests/test_agent_tools.py`

These tools: `find_coverage_gaps`, `compute_site_suitability`, `compute_kernel_density`, `compute_equity_gaps`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_tools.py`:

```python
from app.utils.agent_tools import (
    find_coverage_gaps,
    compute_site_suitability,
    compute_kernel_density,
    compute_equity_gaps,
)


def _mock_service_df():
    import pandas as pd
    return pd.DataFrame([
        {"geom": '{"type":"Point","coordinates":[13.38,52.52]}'},
        {"geom": '{"type":"Point","coordinates":[13.42,52.53]}'},
    ])


def _mock_district_df():
    import pandas as pd
    return pd.DataFrame([
        {"name": "Mitte", "hospital_count": 10,
         "geom": '{"type":"Polygon","coordinates":[[[13.37,52.50],[13.42,52.50],[13.42,52.55],[13.37,52.55],[13.37,52.50]]]}'},
        {"name": "Neukölln", "hospital_count": 2,
         "geom": '{"type":"Polygon","coordinates":[[[13.43,52.45],[13.50,52.45],[13.50,52.50],[13.43,52.50],[13.43,52.45]]]}'},
    ])


def test_find_coverage_gaps_returns_fc():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.side_effect = [
            _mock_service_df(),   # service query
        ]
        result = find_coverage_gaps(
            service_table="public.osm_pharmacies",
            radius_m=500,
            clip_bbox={"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55},
        )
    assert result["type"] == "FeatureCollection"


def test_compute_site_suitability_returns_sorted_fc():
    bbox = {"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55}
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = _mock_service_df()
        result = compute_site_suitability(
            bbox=bbox,
            cell_size_m=500,
            criteria=[{"table": "public.osm_pharmacies", "weight": 1.0, "direction": "far"}],
        )
    assert result["type"] == "FeatureCollection"
    scores = [f["properties"]["suitability_score"] for f in result["features"]]
    assert scores == sorted(scores, reverse=True)


def test_compute_kernel_density_returns_scored_grid():
    bbox = {"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55}
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = _mock_service_df()
        result = compute_kernel_density(
            table="public.osm_restaurants",
            bbox=bbox,
            cell_size_m=500,
        )
    assert result["type"] == "FeatureCollection"
    for f in result["features"]:
        assert 0.0 <= f["properties"]["score"] <= 1.0


def test_compute_equity_gaps_flags_underserved():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = _mock_district_df()
        result = compute_equity_gaps(
            service_table="public.osm_hospitals",
            district_table="vector.wfs_schulen_schulen",
            service_col="hospital_count",
        )
    assert result["type"] == "FeatureCollection"
    underserved = [f for f in result["features"] if f["properties"]["underserved"]]
    assert len(underserved) >= 1  # Neukölln with count=2 should be flagged
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_tools.py -v -k "coverage_gaps or suitability or kernel or equity" 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'find_coverage_gaps'`

- [ ] **Step 3: Add tools to `agent_tools.py`**

Add after the `generate_corridor` function:

```python
def find_coverage_gaps(service_table: str, radius_m: float,
                       clip_bbox: Dict[str, float]) -> Dict[str, Any]:
    """
    Find areas within clip_bbox that are NOT within radius_m of any feature in service_table.

    Args:
        service_table: fully-qualified PostGIS table (e.g. "public.osm_pharmacies")
        radius_m: service radius in metres
        clip_bbox: {"min_lon", "min_lat", "max_lon", "max_lat"} — study area boundary

    Returns:
        GeoJSON FeatureCollection of gap polygons, saved to temp_layers
        or {"error": str}
    """
    try:
        df = db_manager.execute_query(
            f"SELECT ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {service_table}"
        )
        if df is None or df.empty:
            return {"error": f"No features in {service_table}"}

        service_fc = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature",
                 "geometry": json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"],
                 "properties": {}}
                for _, row in df.iterrows()
            ],
        }

        clip_geojson = {
            "type": "Polygon",
            "coordinates": [[
                [clip_bbox["min_lon"], clip_bbox["min_lat"]],
                [clip_bbox["max_lon"], clip_bbox["min_lat"]],
                [clip_bbox["max_lon"], clip_bbox["max_lat"]],
                [clip_bbox["min_lon"], clip_bbox["max_lat"]],
                [clip_bbox["min_lon"], clip_bbox["min_lat"]],
            ]],
        }

        result_fc = _coverage_gaps(service_fc, clip_geojson, radius_m)
        layer_name = f"coverage_gaps_{service_table.split('.')[-1]}"
        return save_generated_layer(result_fc, layer_name, f"Coverage gaps for {service_table}")
    except Exception as e:
        logger.error(f"find_coverage_gaps error: {e}")
        return {"error": str(e)}


def compute_site_suitability(bbox: Dict[str, float], cell_size_m: float,
                              criteria: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Score a hex grid for facility siting using multiple spatial criteria.

    Args:
        bbox: {"min_lon", "min_lat", "max_lon", "max_lat"} — study area
        cell_size_m: hex cell size in metres
        criteria: list of dicts, each with:
            - "table": str — PostGIS table of the criterion features
            - "weight": float — importance weight (default 1.0)
            - "direction": "near"|"far" — "near" favors cells close to features

    Returns:
        GeoJSON FeatureCollection of scored hex cells, sorted best-first, saved to temp_layers
        or {"error": str}
    """
    try:
        grid = _hexagonal_grid(bbox, cell_size_m)
        centroids = [
            shape(f["geometry"]).centroid for f in grid["features"]
        ]

        criteria_scores = []
        for crit in criteria:
            df = db_manager.execute_query(
                f"SELECT ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {crit['table']}"
            )
            if df is None or df.empty:
                continue

            service_pts = [
                shape(json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"])
                for _, row in df.iterrows()
            ]
            if not service_pts:
                continue

            service_union = unary_union(service_pts)
            distances = [c.distance(service_union) for c in centroids]

            criteria_scores.append({
                "scores": distances,
                "weight": crit.get("weight", 1.0),
                "direction": crit.get("direction", "near"),
            })

        if not criteria_scores:
            return {"error": "No valid criteria — check table names and data"}

        scored = _site_suitability(grid, criteria_scores)
        return save_generated_layer(scored, "site_suitability", "Suitability-scored hex grid")
    except Exception as e:
        logger.error(f"compute_site_suitability error: {e}")
        return {"error": str(e)}


def compute_kernel_density(table: str, bbox: Dict[str, float],
                           cell_size_m: float = 500) -> Dict[str, Any]:
    """
    Compute kernel density of features in a PostGIS table over a hex grid.

    Args:
        table: fully-qualified PostGIS table (point features)
        bbox: {"min_lon", "min_lat", "max_lon", "max_lat"} — study area
        cell_size_m: hex grid cell size in metres (default 500)

    Returns:
        GeoJSON FeatureCollection of scored hex cells, saved to temp_layers
        or {"error": str}
    """
    try:
        df = db_manager.execute_query(
            f"SELECT ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {table}"
        )
        if df is None or df.empty:
            return {"error": f"No features in {table}"}

        point_fc = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature",
                 "geometry": json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"],
                 "properties": {}}
                for _, row in df.iterrows()
            ],
        }

        grid = _hexagonal_grid(bbox, cell_size_m)
        scored = _kernel_density(point_fc, grid)
        layer_name = f"kernel_density_{table.split('.')[-1]}"
        return save_generated_layer(scored, layer_name, f"Kernel density of {table}")
    except Exception as e:
        logger.error(f"compute_kernel_density error: {e}")
        return {"error": str(e)}


def compute_equity_gaps(service_table: str, district_table: str,
                        service_col: str = "service_count",
                        population_col: Optional[str] = None) -> Dict[str, Any]:
    """
    Flag statistically underserved districts based on service-to-population ratios.

    Args:
        service_table: PostGIS table of service features (e.g. "public.osm_hospitals")
        district_table: PostGIS table of district polygons (must have geom_25833 + name column)
        service_col: alias used for the count in output properties
        population_col: district column with population count (optional)

    Returns:
        GeoJSON FeatureCollection with equity_score + underserved flag per district
        or {"error": str}
    """
    try:
        pop_select = f", {population_col}" if population_col else ""
        sql = f"""
            SELECT d.name,
                   ST_AsGeoJSON(ST_Transform(d.geom_25833, 4326)) AS geom,
                   COUNT(s.geom_25833) AS {service_col}
                   {pop_select}
            FROM {district_table} d
            LEFT JOIN {service_table} s
              ON ST_Within(s.geom_25833, d.geom_25833)
            GROUP BY d.name, d.geom_25833 {', d.' + population_col if population_col else ''}
        """
        df = db_manager.execute_query(sql)
        if df is None or df.empty:
            return {"error": "No district data returned"}

        district_data = []
        for _, row in df.iterrows():
            entry = {
                "name": row["name"],
                "geometry": json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"],
                service_col: int(row[service_col]),
            }
            if population_col and population_col in row:
                entry[population_col] = int(row[population_col])
            district_data.append(entry)

        result_fc = _equity_gap_analysis(district_data, service_col, population_col)
        return save_generated_layer(result_fc, f"equity_gaps_{service_col}",
                                    f"Equity gap analysis: {service_col} per district")
    except Exception as e:
        logger.error(f"compute_equity_gaps error: {e}")
        return {"error": str(e)}
```

Also add this import at the top of `agent_tools.py` (with existing imports):
```python
from shapely.ops import unary_union
```

- [ ] **Step 4: Run tests — all should pass**

```bash
pytest tests/test_agent_tools.py -v -k "coverage_gaps or suitability or kernel or equity"
```

Expected: all 4 new tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: add suitability, coverage gap, kernel density, and equity analysis tools"
```

---

## Task 4: Add scenario planning tools + update TOOL_REGISTRY

**Files:**
- Modify: `app/utils/agent_tools.py`
- Modify: `tests/test_agent_tools.py`

These tools: `add_hypothetical_feature`, `compare_scenarios`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_tools.py`:

```python
from app.utils.agent_tools import add_hypothetical_feature, compare_scenarios


def test_add_hypothetical_feature_saves_to_postgis():
    geom = {"type": "Point", "coordinates": [13.40, 52.47]}
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("geopandas.GeoDataFrame.to_postgis") as mock_postgis:
        mock_db.engine = MagicMock()
        result = add_hypothetical_feature(
            scenario_name="new_hospital_tempelhof",
            geometry=geom,
            properties={"name": "Hypothetical Hospital", "type": "hospital"},
        )
    mock_postgis.assert_called_once()
    assert result["saved"] is True


def test_compare_scenarios_returns_diff():
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("geopandas.GeoDataFrame.to_postgis"):
        mock_db.engine = MagicMock()
        # baseline: 1 pharmacy covering part of bbox
        mock_db.execute_query.side_effect = [
            # baseline service query
            _mock_service_df(),
            # scenario service query (2 pharmacies)
            _mock_service_df(),
        ]
        result = compare_scenarios(
            baseline_table="public.osm_pharmacies",
            scenario_table="temp_layers.layer_scenario_x",
            radius_m=500,
            clip_bbox={"min_lon": 13.3, "min_lat": 52.45,
                       "max_lon": 13.5, "max_lat": 52.55},
        )
    assert result["type"] == "FeatureCollection"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_tools.py -v -k "hypothetical or compare_scenarios" 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'add_hypothetical_feature'`

- [ ] **Step 3: Add scenario tools to `agent_tools.py`**

Add after `compute_equity_gaps`:

```python
def add_hypothetical_feature(scenario_name: str, geometry: Dict[str, Any],
                              properties: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Add a hypothetical feature to a named scenario layer in temp_layers.
    If the scenario layer already exists, the new feature is appended.

    Args:
        scenario_name: short name for the scenario (e.g. "new_hospital_tempelhof")
        geometry: GeoJSON geometry dict (Point, Polygon, etc.)
        properties: optional dict of attributes

    Returns:
        {"saved": True, "table": str, "feature_count": int, "geojson": FeatureCollection}
        or {"error": str}
    """
    try:
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": geometry,
                "properties": properties or {},
            }],
        }
        safe = scenario_name.lower().replace(" ", "_")[:40]
        layer_name = f"scenario_{safe}"
        return save_generated_layer(fc, layer_name, f"Hypothetical scenario: {scenario_name}")
    except Exception as e:
        logger.error(f"add_hypothetical_feature error: {e}")
        return {"error": str(e)}


def compare_scenarios(baseline_table: str, scenario_table: str,
                      radius_m: float, clip_bbox: Dict[str, float]) -> Dict[str, Any]:
    """
    Compare coverage gaps between a baseline and a scenario layer.
    Returns a FeatureCollection showing what improved (features in baseline gaps
    but not scenario gaps).

    Args:
        baseline_table: PostGIS table of baseline service features
        scenario_table: PostGIS table of scenario service features (e.g. baseline + hypothetical)
        radius_m: service radius in metres
        clip_bbox: {"min_lon", "min_lat", "max_lon", "max_lat"}

    Returns:
        GeoJSON FeatureCollection with "scenario": "improved"|"unchanged" per gap polygon
        or {"error": str}
    """
    try:
        clip_geojson = {
            "type": "Polygon",
            "coordinates": [[
                [clip_bbox["min_lon"], clip_bbox["min_lat"]],
                [clip_bbox["max_lon"], clip_bbox["min_lat"]],
                [clip_bbox["max_lon"], clip_bbox["max_lat"]],
                [clip_bbox["min_lon"], clip_bbox["max_lat"]],
                [clip_bbox["min_lon"], clip_bbox["min_lat"]],
            ]],
        }

        def _fetch_fc(table):
            df = db_manager.execute_query(
                f"SELECT ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM {table}"
            )
            if df is None or df.empty:
                return {"type": "FeatureCollection", "features": []}
            return {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature",
                     "geometry": json.loads(row["geom"]) if isinstance(row["geom"], str) else row["geom"],
                     "properties": {}}
                    for _, row in df.iterrows()
                ],
            }

        baseline_fc = _fetch_fc(baseline_table)
        scenario_fc = _fetch_fc(scenario_table)

        baseline_gaps = _coverage_gaps(baseline_fc, clip_geojson, radius_m)
        scenario_gaps = _coverage_gaps(scenario_fc, clip_geojson, radius_m)

        baseline_union = unary_union([shape(f["geometry"]) for f in baseline_gaps["features"]]) \
            if baseline_gaps["features"] else shape(clip_geojson).difference(shape(clip_geojson))
        scenario_union = unary_union([shape(f["geometry"]) for f in scenario_gaps["features"]]) \
            if scenario_gaps["features"] else shape(clip_geojson).difference(shape(clip_geojson))

        improved = baseline_union.difference(scenario_union)
        unchanged = scenario_union

        result_features = []
        for g, label in [(improved, "improved"), (unchanged, "unchanged")]:
            if g.is_empty:
                continue
            geoms = list(g.geoms) if hasattr(g, "geoms") else [g]
            for geom in geoms:
                if geom.area < 1e-8:
                    continue
                result_features.append({
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {"scenario": label},
                })

        result_fc = {"type": "FeatureCollection", "features": result_features}
        return save_generated_layer(result_fc, "scenario_comparison", "Before/after scenario diff")
    except Exception as e:
        logger.error(f"compare_scenarios error: {e}")
        return {"error": str(e)}
```

- [ ] **Step 4: Update TOOL_REGISTRY**

Replace the existing `TOOL_REGISTRY` block at the bottom of `agent_tools.py`:

```python
TOOL_REGISTRY: Dict[str, Any] = {
    # --- Existing tools ---
    "geocode_location": geocode_location,
    "create_buffer": create_buffer,
    "find_tables_by_concept": find_tables_by_concept,
    "get_schema_info": get_schema_info,
    "get_table_columns": get_table_columns,
    "execute_sql": execute_sql,
    "spatial_filter": spatial_filter,
    "calculate_route": calculate_route,
    "walking_isochrone": walking_isochrone,
    "analyze_satellite": analyze_satellite,
    "score_locations": score_locations,
    # --- A: Geometry generation ---
    "generate_voronoi": generate_voronoi,
    "generate_hexgrid": generate_hexgrid,
    "generate_convex_hull": generate_convex_hull,
    "generate_corridor": generate_corridor,
    # --- B: Suitability & coverage ---
    "find_coverage_gaps": find_coverage_gaps,
    "compute_site_suitability": compute_site_suitability,
    # --- C: Analytical surfaces ---
    "compute_kernel_density": compute_kernel_density,
    "compute_equity_gaps": compute_equity_gaps,
    # --- D: Scenario planning ---
    "add_hypothetical_feature": add_hypothetical_feature,
    "compare_scenarios": compare_scenarios,
    # --- Persistence ---
    "save_generated_layer": save_generated_layer,
}
```

- [ ] **Step 5: Fix stale registry test in `tests/test_agent_tools.py`**

Replace the `test_tool_registry_has_all_tools` test:

```python
def test_tool_registry_has_all_tools():
    expected = {
        "geocode_location", "create_buffer", "find_tables_by_concept",
        "get_schema_info", "get_table_columns", "execute_sql",
        "spatial_filter", "calculate_route", "walking_isochrone",
        "analyze_satellite", "score_locations",
        "generate_voronoi", "generate_hexgrid", "generate_convex_hull", "generate_corridor",
        "find_coverage_gaps", "compute_site_suitability",
        "compute_kernel_density", "compute_equity_gaps",
        "add_hypothetical_feature", "compare_scenarios",
        "save_generated_layer",
    }
    assert expected == set(TOOL_REGISTRY.keys())
```

- [ ] **Step 6: Run all agent_tools tests**

```bash
pytest tests/test_agent_tools.py -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/utils/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: add scenario planning tools + update TOOL_REGISTRY with all 12 new tools"
```

---

## Task 5: Update agent system prompt

**Files:**
- Modify: `app/utils/agent_orchestrator.py`

- [ ] **Step 1: Add new tools to `_build_agent_system_prompt()`**

In `agent_orchestrator.py`, find the `Available tools:` section inside `_build_agent_system_prompt()` and append after the existing tool list:

```python
# In _build_agent_system_prompt(), append to the tools list:

"""
- generate_voronoi(table: str, id_col: str="id", clip_table: str=None) → saves Voronoi polygons to temp_layers, returns {saved, table, feature_count, geojson}
- generate_hexgrid(bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float) → GeoJSON FeatureCollection of hex cells (not saved — pass to other tools)
- generate_convex_hull(table: str) → GeoJSON FeatureCollection with single bounding Polygon
- generate_corridor(linestring_geojson: GeoJSON LineString, width_m: float) → GeoJSON FeatureCollection with corridor Polygon
- find_coverage_gaps(service_table: str, radius_m: float, clip_bbox: {min_lon,min_lat,max_lon,max_lat}) → saves gap polygons to temp_layers, returns {saved, table, feature_count, geojson}
- compute_site_suitability(bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float, criteria: [{table,weight,direction:"near"|"far"}]) → saves scored hex grid to temp_layers
- compute_kernel_density(table: str, bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float=500) → saves density-scored hex grid to temp_layers
- compute_equity_gaps(service_table: str, district_table: str, service_col: str, population_col: str=None) → saves district equity scores to temp_layers
- add_hypothetical_feature(scenario_name: str, geometry: GeoJSON, properties: dict={}) → saves hypothetical feature to temp_layers scenario layer
- compare_scenarios(baseline_table: str, scenario_table: str, radius_m: float, clip_bbox: dict) → saves improved/unchanged gap diff to temp_layers
- save_generated_layer(geojson: FeatureCollection, layer_name: str, description: str="") → saves any FeatureCollection to temp_layers, returns {saved, table, feature_count}
"""
```

Also append these workflow descriptions after the existing workflow sections:

```python
"""
Geometry generation workflow:
- "Generate Voronoi zones for all hospitals" → generate_voronoi(table="public.osm_hospitals")
- "Show the convex hull of all schools" → generate_convex_hull(table="public.osm_schools")
- "Create a 200m corridor along [route]" → first calculate_route, then generate_corridor(linestring, width_m=200)
- "Generate a 500m hex grid over Berlin" → generate_hexgrid(bbox={...berlin...}, cell_size_m=500)

Coverage and suitability workflow:
- "Find areas more than 1km from a pharmacy" → geocode_location to get bbox, then find_coverage_gaps(service_table="public.osm_pharmacies", radius_m=1000, clip_bbox=...)
- "Best locations for a new clinic near transport, far from existing clinics" → compute_site_suitability(bbox=..., cell_size_m=500, criteria=[{table:"public.osm_transport_stops",weight:0.5,direction:"near"},{table:"public.osm_hospitals",weight:0.5,direction:"far"}])

Analytical surface workflow:
- "Show density of restaurants across Berlin" → compute_kernel_density(table="public.osm_restaurants", bbox={...berlin...})
- "Which districts have worst hospital coverage?" → compute_equity_gaps(service_table="public.osm_hospitals", district_table="vector.wfs_schulen_schulen", service_col="hospital_count")

Scenario planning workflow:
1. add_hypothetical_feature(scenario_name="new_hospital", geometry={...}, properties={type:"hospital"})
2. compare_scenarios(baseline_table="public.osm_hospitals", scenario_table="temp_layers.layer_scenario_new_hospital_...", radius_m=1000, clip_bbox=...)
"""
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests PASS (or pre-existing failures unrelated to this feature)

- [ ] **Step 3: Commit**

```bash
git add app/utils/agent_orchestrator.py
git commit -m "feat: add spatial generator tool descriptions and workflows to agent system prompt"
```

---

## Verification (End-to-End)

Start the app and run these queries in order:

```bash
# Start the API
uvicorn app.main:app --reload --port 8000
```

1. **Geometry generation:** Ask *"Generate Voronoi zones for all hospitals"*
   - Expected: new `temp_layers.layer_voronoi_osm_hospitals_*` table created, Voronoi polygons render on map

2. **Coverage gaps:** Ask *"Show areas more than 1km from any pharmacy in central Berlin"*
   - Expected: gap polygons render showing underserved areas

3. **Suitability:** Ask *"Find the best 5 locations for a new clinic — near transport stops, far from existing hospitals"*
   - Expected: scored hex grid renders, top cells highlighted

4. **Kernel density:** Ask *"Show density of restaurants across Mitte"*
   - Expected: density-scored hex grid renders

5. **Equity analysis:** Ask *"Which districts have the worst hospital coverage?"*
   - Expected: district polygons colored by equity score, underserved ones flagged

6. **Scenario planning:** Ask *"Add a hypothetical hospital at Tempelhof"* then *"How does adding that hospital change coverage?"*
   - Expected: step 1 saves scenario layer, step 2 renders improved/unchanged gap diff
