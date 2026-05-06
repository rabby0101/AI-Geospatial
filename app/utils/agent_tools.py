"""
Agent tools — each function does one thing and returns a plain dict.
Success: dict with result data.
Failure: dict with "error" key.
"""
import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import geopandas as gpd
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform, unary_union
import pyproj

from app.utils.location_resolver import LocationResolver
from app.utils.database import db_manager
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

logger = logging.getLogger(__name__)
location_resolver = LocationResolver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wkt_point_to_coords(wkt: str) -> Optional[Dict[str, float]]:
    """Extract lon/lat from WKT POINT string."""
    try:
        from shapely import wkt as swkt
        geom = swkt.loads(wkt)
        return {"lon": geom.x, "lat": geom.y}
    except Exception:
        return None


def _buffer_geometry(geom_wgs84, radius_m: int) -> Dict[str, Any]:
    """Buffer a shapely geometry (in WGS84) by radius_m metres. Returns GeoJSON dict."""
    project_to = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True).transform
    project_back = pyproj.Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True).transform
    projected = transform(project_to, geom_wgs84)
    buffered = projected.buffer(radius_m)
    back = transform(project_back, buffered)
    return mapping(back)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def geocode_location(name: str) -> Dict[str, Any]:
    """
    Geocode a place name to coordinates.

    Returns:
        {"lat": float, "lon": float, "display_name": str, "geometry": GeoJSON Point}
        or {"error": str}
    """
    try:
        result = location_resolver.resolve_location(name)
        if not result:
            return {"error": f"Location not found: {name}"}

        geometry_wkt = result.get("geometry", "")
        coords = _wkt_point_to_coords(geometry_wkt) if geometry_wkt else None

        # Fall back to bbox centre if point extraction fails
        if not coords:
            bbox = result.get("bbox")
            if bbox:
                coords = {"lon": (bbox[0] + bbox[2]) / 2, "lat": (bbox[1] + bbox[3]) / 2}
            else:
                return {"error": f"Could not extract coordinates from location: {name}"}

        return {
            "lat": coords["lat"],
            "lon": coords["lon"],
            "display_name": result.get("name", name),
            "geometry": {
                "type": "Point",
                "coordinates": [coords["lon"], coords["lat"]],
            },
        }
    except Exception as e:
        logger.error(f"geocode_location error: {e}")
        return {"error": str(e)}


def create_buffer(geometry_or_coords: Union[Dict, Any], radius_m: int) -> Dict[str, Any]:
    """
    Create a buffer polygon around a point or geometry.

    Args:
        geometry_or_coords: GeoJSON geometry dict OR {"lat": float, "lon": float}
        radius_m: Buffer radius in metres

    Returns:
        GeoJSON Polygon dict or {"error": str}
    """
    try:
        if isinstance(geometry_or_coords, dict):
            if "lat" in geometry_or_coords and "lon" in geometry_or_coords:
                lat, lon = geometry_or_coords["lat"], geometry_or_coords["lon"]
                geom = Point(lon, lat)
            elif "type" in geometry_or_coords:
                geom = shape(geometry_or_coords)
            else:
                return {"error": "geometry_or_coords must have lat/lon keys or be a GeoJSON geometry"}
        else:
            return {"error": "geometry_or_coords must be a dict"}

        return _buffer_geometry(geom, radius_m)
    except Exception as e:
        logger.error(f"create_buffer error: {e}")
        return {"error": str(e)}


def get_schema_info(keywords: Optional[List[str]] = None, **_ignored) -> Union[List[Dict], Dict]:
    """
    Return a compact catalog of ALL available tables so the LLM can choose
    which ones are relevant. Each entry has table_name, a short description,
    geometry_type, and row_count.

    Args:
        keywords: Ignored (kept for backward compatibility). All tables are returned.

    Returns:
        List of {"table_name": str, "description": str, "geometry_type": str, "row_count": int}
        or {"error": str}
    """
    try:
        sql = """
            SELECT table_name, description, geometry_type, row_count
            FROM metadata.table_descriptions
            ORDER BY table_name
        """
        df = db_manager.execute_query(sql)

        if df is None or df.empty:
            return {"error": "No tables found in metadata"}
        rows = df.to_dict("records")
        # Return compact one-line-per-table catalog for minimal token usage
        lines = []
        for r in rows:
            name = r["table_name"]
            raw_rc = r.get("row_count")
            try:
                import math
                rc = int(raw_rc) if raw_rc is not None and not math.isnan(raw_rc) else "?"
            except (TypeError, ValueError):
                rc = "?"
            gt = r.get("geometry_type") or "NONE"
            desc = (r.get("description") or "")[:1000]
            lines.append(f"{name} ({rc} rows, {gt}) — {desc}")
        return {"catalog": "\n".join(lines), "total_tables": len(lines)}
    except Exception as e:
        logger.error(f"get_schema_info error: {e}")
        return {"error": str(e)}




def spatial_filter(
    features: Dict[str, Any],
    filter_geometry: Dict[str, Any],
    relation: str = "within",
) -> Dict[str, Any]:
    """
    Filter a GeoJSON FeatureCollection to features that are within or intersect a geometry.

    Args:
        features: GeoJSON FeatureCollection
        filter_geometry: GeoJSON geometry (e.g. a buffer polygon)
        relation: "within" or "intersects"

    Returns:
        {"type": "FeatureCollection", "features": [...], "count": int}
        or {"error": str}
    """
    try:
        filter_shape = shape(filter_geometry)
        result_features = []
        for feat in features.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            feat_shape = shape(geom)
            if relation == "within" and feat_shape.within(filter_shape):
                result_features.append(feat)
            elif relation == "intersects" and feat_shape.intersects(filter_shape):
                result_features.append(feat)
        return {
            "type": "FeatureCollection",
            "features": result_features,
            "count": len(result_features),
        }
    except Exception as e:
        logger.error(f"spatial_filter error: {e}")
        return {"error": str(e)}


def calculate_route(waypoints: List[Dict[str, float]], mode: str = "walking") -> Dict[str, Any]:
    """
    Calculate the optimal route between waypoints using Valhalla.

    Args:
        waypoints: List of {"lat": float, "lon": float, "name": str} dicts
        mode: "walking", "cycling", or "driving"

    Returns:
        GeoJSON FeatureCollection with route LineString + distance_m/duration_s properties
        or {"error": str}
    """
    try:
        from app.utils.valhalla_routing import valhalla_service

        MODE_MAP = {"walking": "pedestrian", "cycling": "bicycle", "driving": "auto"}
        costing = MODE_MAP.get(mode, "pedestrian")

        points = [(wp["lat"], wp["lon"]) for wp in waypoints]
        names = [wp.get("name", f"Point {i+1}") for i, wp in enumerate(waypoints)]

        if len(points) < 2:
            return {"error": "At least 2 waypoints required"}

        if len(points) == 2:
            result = valhalla_service.get_route(
                points[0][0], points[0][1],
                points[1][0], points[1][1],
                costing=costing
            )
        else:
            result = valhalla_service.get_multi_point_route(points, costing=costing)

        if not result.success:
            return {"error": result.error or "Routing failed"}

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": result.geometry,
                    "properties": {
                        "from": names[0],
                        "to": names[-1],
                        "mode": mode,
                        "distance_m": round(result.distance_m),
                        "distance_km": round(result.distance_m / 1000, 2),
                        "duration_s": round(result.duration_seconds),
                        "duration_min": round(result.duration_minutes, 1),
                    },
                }
            ],
        }
    except Exception as e:
        logger.error(f"calculate_route error: {e}")
        return {"error": str(e)}


def walking_isochrone(location: Dict[str, float], minutes: int, mode: str = "walking") -> Dict[str, Any]:
    """
    Calculate the area reachable from a location within N minutes by the given mode.

    Args:
        location: {"lat": float, "lon": float}
        minutes: Travel time in minutes
        mode: "walking", "cycling", or "driving"

    Returns:
        GeoJSON FeatureCollection with isochrone Polygon
        or {"error": str}
    """
    try:
        from app.utils.valhalla_routing import valhalla_service

        MODE_MAP = {"walking": "pedestrian", "cycling": "bicycle", "driving": "auto"}
        costing = MODE_MAP.get(mode, "pedestrian")

        lat = location.get("lat")
        lon = location.get("lon")
        if lat is None or lon is None:
            return {"error": "location must have 'lat' and 'lon' keys"}

        result = valhalla_service.get_isochrone(lat, lon, minutes, costing=costing)

        if not result.success:
            return {"error": result.error or "Isochrone failed"}

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": result.geometry,
                    "properties": {
                        "mode": mode,
                        "minutes": minutes,
                        "center_lat": lat,
                        "center_lon": lon,
                    },
                }
            ],
        }
    except Exception as e:
        logger.error(f"walking_isochrone error: {e}")
        return {"error": str(e)}


def compute_spectral_index(
    index: str = "NDVI",
    date: Optional[str] = None,
    geometry: Optional[Dict[str, Any]] = None,
    boundary_sql: Optional[str] = None,
    bbox: Optional[Dict[str, float]] = None,
    polygons_sql: Optional[str] = None,
    area_label: str = "area",
) -> Dict[str, Any]:
    """
    Compute a spectral index (NDVI/EVI/SAVI/NDWI/NDBI) over any area using
    satellite files attached to the current session.

    Exactly one geometry source must be supplied:
      geometry:     GeoJSON Polygon/MultiPolygon (e.g. drawn on the map)
      boundary_sql: SQL returning a single geometry column (derive with schema tools)
      bbox:         {min_lon, min_lat, max_lon, max_lat}

    polygons_sql: Optional SQL returning (id/name, geometry) rows for sub-area
                  zonal statistics at any granularity (Flurstück, districts, grid…).
                  Defaults to the same geometry as boundary_sql.
    area_label:   Label used in the saved layer name and metadata.

    Returns GeoJSON FeatureCollection with {index}_mean per polygon + choropleth
    metadata, or {"error": ...}.
    """
    try:
        from app.utils.attachment_store import current_session_id
        from app.routes.satellite import _load_session, _session_dir
        from app.utils.satellite_processor import (
            REQUIRED_BANDS,
            calculate_index,
            compute_single_date_zonal_stats,
            crop_to_area,
            identify_covering_tiles,
            mosaic_tiles,
        )
    except Exception as e:
        return {"error": f"Satellite pipeline unavailable: {e}"}

    # ── Resolve geometry source → boundary_sql ──────────────────────────────
    sources = [s for s in (geometry, boundary_sql, bbox) if s is not None]
    if len(sources) == 0:
        return {"error": "Provide exactly one of: geometry, boundary_sql, or bbox."}
    if len(sources) > 1:
        return {"error": "Provide only one geometry source (geometry, boundary_sql, or bbox)."}

    if geometry is not None:
        geojson_str = json.dumps(geometry).replace("'", "''")
        resolved_boundary = f"SELECT ST_GeomFromGeoJSON('{geojson_str}') AS geometry"
    elif boundary_sql is not None:
        resolved_boundary = boundary_sql
    else:  # bbox
        if not all(k in bbox for k in ("min_lon", "min_lat", "max_lon", "max_lat")):
            return {"error": "bbox must have keys: min_lon, min_lat, max_lon, max_lat"}
        resolved_boundary = (
            f"SELECT ST_MakeEnvelope("
            f"{bbox['min_lon']},{bbox['min_lat']},"
            f"{bbox['max_lon']},{bbox['max_lat']},4326) AS geometry"
        )

    if polygons_sql is None:
        polygons_sql = resolved_boundary

    # ── Session & index validation ───────────────────────────────────────────
    sid = current_session_id.get()
    if not sid:
        return {"error": "No active session — attach satellite files via the chat attach button first."}

    session_files = _load_session(sid)
    if not session_files:
        return {
            "error": "No satellite files in this session. "
                     "Attach a Sentinel-2 SAFE .zip or band .tif files first."
        }

    idx_lower = index.lower()
    if idx_lower not in REQUIRED_BANDS:
        return {
            "error": f"Unknown index '{index}'. "
                     f"Supported: {list(REQUIRED_BANDS.keys())}"
        }

    # ── Pick date ────────────────────────────────────────────────────────────
    if not date:
        available = sorted({e["date"] for e in session_files if e.get("date")})
        if not available:
            return {"error": "Uploaded tiles have no date metadata — please specify date='YYYY-MM-DD'."}
        date = available[0]

    work_dir = _session_dir(sid) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    safe_date = date.replace("-", "")
    safe_label = area_label.lower().replace(" ", "_")

    try:
        covering, _cov_pct = identify_covering_tiles(session_files, resolved_boundary, date)
    except ValueError as e:
        return {"error": str(e)}

    band_files: Dict[str, list] = {}
    for entry in covering:
        b = entry.get("band")
        if b:
            band_files.setdefault(b, []).append(entry)

    missing = [b for b in REQUIRED_BANDS[idx_lower] if b not in band_files]
    if missing:
        return {
            "error": f"{index.upper()} requires bands {REQUIRED_BANDS[idx_lower]}. "
                     f"Missing from your uploads: {missing}. Available: {sorted(band_files.keys())}"
        }

    try:
        cropped_bands: Dict[str, str] = {}
        for band in REQUIRED_BANDS[idx_lower]:
            tile_paths = [e["path"] for e in band_files[band] if e.get("path")]
            mosaic_path = str(work_dir / f"mosaic_{band}_{safe_date}.tif")
            mosaic_tiles(tile_paths, mosaic_path)
            crop_path = str(work_dir / f"crop_{band}_{safe_date}_{safe_label}.tif")
            crop_to_area(mosaic_path, resolved_boundary, crop_path)
            cropped_bands[band] = crop_path

        index_path = str(work_dir / f"{idx_lower}_{safe_date}_{safe_label}.tif")
        calculate_index(cropped_bands, idx_lower, index_path)

        result_gdf = compute_single_date_zonal_stats(
            raster_path=index_path,
            polygons_sql=polygons_sql,
            index_type=idx_lower,
        )

        if result_gdf.crs and result_gdf.crs.to_epsg() != 4326:
            result_gdf = result_gdf.to_crs(4326)

        geojson_dict = json.loads(result_gdf.to_json())
        choropleth_property = f"{idx_lower}_mean"

        values = [
            f["properties"].get(choropleth_property)
            for f in geojson_dict.get("features", [])
            if f["properties"].get(choropleth_property) is not None
        ]
        val_min = float(min(values)) if values else -1.0
        val_max = float(max(values)) if values else 1.0

        layer_name = f"{idx_lower}_{safe_label}_{date[:4]}"
        saved = save_generated_layer(
            geojson_dict,
            layer_name,
            f"{index.upper()} for {area_label} on {date}",
        )

        enriched = dict(geojson_dict)
        enriched["metadata"] = {
            "index": idx_lower,
            "area_label": area_label,
            "date": date,
            "choropleth_property": choropleth_property,
            "choropleth_min": val_min,
            "choropleth_max": val_max,
            "feature_count": len(geojson_dict.get("features", [])),
            "is_satellite_result": True,
        }
        if isinstance(saved, dict) and saved.get("saved"):
            enriched["saved_table"] = saved.get("table")
        return enriched
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"compute_spectral_index error: {e}", exc_info=True)
        return {"error": str(e)}


def score_locations(features: Dict[str, Any], criteria: List[str]) -> Dict[str, Any]:
    """
    Score and rank GeoJSON features using simple MCDA.

    Normalises all numeric properties to [0, 1] and computes an average score.

    Args:
        features: GeoJSON FeatureCollection
        criteria: List of scoring criteria (used as a label in properties)

    Returns:
        GeoJSON FeatureCollection with added "score" property or {"error": str}
    """
    try:
        import geopandas as gpd
        import numpy as np

        gdf = gpd.GeoDataFrame.from_features(features.get("features", []), crs="EPSG:4326")
        if gdf.empty:
            return {"error": "No features to score"}

        numeric_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            normed = gdf[numeric_cols].copy()
            for col in numeric_cols:
                col_min, col_max = normed[col].min(), normed[col].max()
                if col_max > col_min:
                    normed[col] = (normed[col] - col_min) / (col_max - col_min)
                else:
                    normed[col] = 0.0
            gdf["score"] = normed.mean(axis=1).round(4)
        else:
            gdf["score"] = 0.0

        gdf["scoring_criteria"] = ", ".join(criteria)
        gdf = gdf.sort_values("score", ascending=False)
        return json.loads(gdf.to_json())
    except Exception as e:
        logger.error(f"score_locations error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# New atomic tools for explicit agentic SQL workflow
# ---------------------------------------------------------------------------

def get_table_columns(table_name: str) -> Union[List[Dict], Dict]:
    """
    Return column names, types, and sample values for a specific table.
    Use this after get_schema_info to understand what columns are available
    before writing SQL.

    Args:
        table_name: Exact table name from get_schema_info (e.g. "osm_playgrounds")

    Returns:
        List of {"column": str, "type": str, "sample_values": list} dicts
        or {"error": str}
    """
    try:
        sql = f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'vector'
              AND table_name = '{table_name}'
            ORDER BY ordinal_position
            LIMIT 40
        """
        df = db_manager.execute_query(sql)
        if df is None or df.empty:
            return {"error": f"No columns found for 'vector.{table_name}'. Check the table name."}

        rows = df.to_dict("records")
        columns = [{"column": r["column_name"], "type": r["data_type"]} for r in rows]

        # Geometry columns bubble to the top so the LLM always sees them,
        # even in wide tables (50+ columns) where they'd otherwise be truncated
        GEO_COLS = {"geom_25833", "geometry", "geom"}
        geo = [c for c in columns if c["column"] in GEO_COLS]
        non_geo = [c for c in columns if c["column"] not in GEO_COLS]
        columns = geo + non_geo

        # Fetch sample values for first 10 non-geometry columns
        sample_cols = [c for c in columns if c["type"] not in ("USER-DEFINED",)][:10]
        for col in sample_cols:
            try:
                sample_sql = f"""
                    SELECT DISTINCT "{col['column']}"::text AS val
                    FROM vector.{table_name}
                    WHERE "{col['column']}" IS NOT NULL
                    LIMIT 5
                """
                sample_df = db_manager.execute_query(sample_sql)
                if sample_df is not None and not sample_df.empty:
                    col["sample_values"] = sample_df["val"].tolist()
                else:
                    col["sample_values"] = []
            except Exception:
                col["sample_values"] = []

        return columns
    except Exception as e:
        logger.error(f"get_table_columns error: {e}")
        return {"error": str(e)}


def _recursive_convert_decimals(obj):
    if isinstance(obj, dict):
        return {k: _recursive_convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_recursive_convert_decimals(item) for item in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj


def execute_sql(sql: str) -> Dict[str, Any]:
    """
    Execute a PostGIS SQL query and return results as a GeoJSON FeatureCollection.

    Rules for writing the SQL:
    - ALWAYS write: SELECT *, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom
      Use alias 'geom' — never 'geometry', as some tables (e.g. alkis_buildings) already
      have a raw 'geometry' column and aliasing to it causes a conflict.
      geom_25833 is THE geometry column in ALL tables; SELECT * preserves all attributes.
    - Tables live in the 'vector' schema: FROM vector.<table_name>
      Temp tables (selected features) live in the 'temp' schema: FROM temp.<table_name>
    - For spatial filters use ST_Within or ST_Intersects with ST_SetSRID(..., 4326)
    - Use ST_MakeValid() on geometries that may be invalid

    Args:
        sql: Valid PostGIS SQL SELECT statement

    Returns:
        {"type": "FeatureCollection", "features": [...], "count": int}
        or {"error": str}
    """
    try:
        import json as _json
        df = db_manager.execute_query(sql)
        if df is None or df.empty:
            return {"error": "Query failed or returned no results"}

        import math as _math

        features = []
        for row_dict in df.to_dict("records"):
            # Extract GeoJSON geometry — look for the 'geom' alias first (canonical),
            # then geom_25833 as fallback. Never use the raw 'geometry' column (WKB).
            geom = None
            for key in ("geom", "geom_25833"):
                if key in row_dict and row_dict[key]:
                    try:
                        geom = _json.loads(row_dict.pop(key))
                        geom = _recursive_convert_decimals(geom)
                        break
                    except Exception:
                        row_dict.pop(key, None)

            # Remove all remaining raw geometry columns to keep properties clean
            for key in list(row_dict.keys()):
                if "geom" in key.lower() or key == "geometry":
                    row_dict.pop(key)

            # Replace NaN/Infinity with None — json.dumps outputs literal NaN which is
            # not valid JSON, causing JSON.parse to fail silently in the browser.
            for key, val in row_dict.items():
                if isinstance(val, float) and not _math.isfinite(val):
                    row_dict[key] = None

            row_dict = _recursive_convert_decimals(row_dict)

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": row_dict,
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
        }
    except Exception as e:
        logger.error(f"execute_sql error: {e}")
        return {"error": str(e)}


def find_tables_by_concept(concepts: List[str]) -> Dict[str, Any]:
    """
    Find database tables relevant to the given concepts using the knowledge graph.

    Two-stage lookup:
    1. Query RDF graph: match concept strings against ontology synonyms → resolve to analysis_pattern tags
    2. Query DB: find tables whose analysis_patterns include those tags

    Args:
        concepts: List of concept strings in any language, e.g.
                  ["zoning plan", "B-Plan"] or ["elderly population", "Altersgruppen"]

    Returns:
        {"tables": [{"table_name", "description", "analysis_patterns", "related_tables"}],
         "count": int, "matched_tags": [...]}
    """
    try:
        from app.utils.semantic_layer import get_semantic_layer
        sl = get_semantic_layer()

        # Stage 1: resolve concepts → tags via ontology synonyms
        matched_tags: set = set()
        for concept in concepts:
            concept_lower = concept.lower().strip()
            sparql = f"""
                PREFIX : <http://geoassist.ai/ontology#>
                SELECT ?tag WHERE {{
                    ?class :synonym ?syn ;
                           :mapsFromTag ?tag .
                    FILTER(CONTAINS(LCASE(STR(?syn)), "{concept_lower}"))
                }}
            """
            try:
                results = sl.query_sparql(sparql)
                matched_tags.update(r["tag"] for r in results if r.get("tag"))
            except Exception:
                pass

        # Fallback: use concept words directly as tag candidates
        if not matched_tags:
            for concept in concepts:
                for word in concept.lower().replace("-", "_").split():
                    matched_tags.add(word)

        if not matched_tags:
            return {"tables": [], "count": 0, "matched_tags": [], "note": "No matching concepts found"}

        # Stage 2: query DB for tables with those tags in analysis_patterns
        # PostgreSQL text[] casts as {tag1,tag2,...} — no quotes around values
        tag_conditions = " OR ".join(
            f"analysis_patterns::text ILIKE '%{tag}%'" for tag in matched_tags
        )
        sql = f"""
            SELECT table_name, description, analysis_patterns, related_tables
            FROM metadata.table_descriptions
            WHERE {tag_conditions}
            ORDER BY table_name
        """
        df = db_manager.execute_query(sql)
        if df is None or df.empty:
            return {"tables": [], "count": 0, "matched_tags": list(matched_tags),
                    "note": "No tables found for these concepts"}

        tables = df.to_dict("records")
        return {
            "tables": tables,
            "count": len(tables),
            "matched_tags": list(matched_tags),
        }

    except Exception as e:
        logger.error(f"find_tables_by_concept error: {e}")
        return {"error": str(e)}


def save_generated_layer(geojson: Dict[str, Any], layer_name: str,
                         description: str = "") -> Dict[str, Any]:
    try:
        features = geojson.get("features", [])
        if not features:
            return {"error": "No features to save"}

        geometries = [shape(f["geometry"]) for f in features if f.get("geometry")]
        props = [f.get("properties", {}) for f in features if f.get("geometry")]

        if not geometries:
            return {"error": "No features with valid geometries to save"}

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
            "feature_count": len(geometries),
            "geojson": geojson,
            "description": description,
        }
    except Exception as e:
        logger.error(f"save_generated_layer error: {e}")
        return {"error": str(e)}


def generate_voronoi(table: str, id_col: str = "id",
                     clip_table: Optional[str] = None) -> Dict[str, Any]:
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
    try:
        return _hexagonal_grid(bbox, cell_size_m)
    except Exception as e:
        logger.error(f"generate_hexgrid error: {e}")
        return {"error": str(e)}


def generate_convex_hull(table: str) -> Dict[str, Any]:
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
    try:
        return _corridor(linestring_geojson, width_m)
    except Exception as e:
        logger.error(f"generate_corridor error: {e}")
        return {"error": str(e)}


def find_coverage_gaps(service_table: str, radius_m: float,
                       clip_bbox: Dict[str, float]) -> Dict[str, Any]:
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
    try:
        grid = _hexagonal_grid(bbox, cell_size_m)
        centroids = [shape(f["geometry"]).centroid for f in grid["features"]]

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
    try:
        pop_select = f", d.{population_col}" if population_col else ""
        pop_group = f", d.{population_col}" if population_col else ""
        sql = f"""
            SELECT d.name,
                   ST_AsGeoJSON(ST_Transform(d.geom_25833, 4326)) AS geom,
                   COUNT(s.geom_25833) AS {service_col}
                   {pop_select}
            FROM {district_table} d
            LEFT JOIN {service_table} s
              ON ST_Within(s.geom_25833, d.geom_25833)
            GROUP BY d.name, d.geom_25833{pop_group}
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
            if population_col and population_col in row.index:
                entry[population_col] = int(row[population_col])
            district_data.append(entry)

        result_fc = _equity_gap_analysis(district_data, service_col, population_col)
        return save_generated_layer(result_fc, f"equity_gaps_{service_col}",
                                    f"Equity gap analysis: {service_col} per district")
    except Exception as e:
        logger.error(f"compute_equity_gaps error: {e}")
        return {"error": str(e)}


def add_hypothetical_feature(scenario_name: str, geometry: Dict[str, Any],
                              properties: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Add a hypothetical feature to a named scenario layer in temp_layers.
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
    Returns a FeatureCollection showing improved vs unchanged gap polygons.
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

        clip_shape = shape(clip_geojson)
        empty = clip_shape.difference(clip_shape)

        baseline_union = unary_union([shape(f["geometry"]) for f in baseline_gaps["features"]]) \
            if baseline_gaps["features"] else empty
        scenario_union = unary_union([shape(f["geometry"]) for f in scenario_gaps["features"]]) \
            if scenario_gaps["features"] else empty

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
        saved = save_generated_layer(result_fc, "scenario_comparison", "Before/after scenario diff")
        if "error" in saved:
            return saved
        return {**result_fc, **{k: v for k, v in saved.items() if k != "geojson"}}
    except Exception as e:
        logger.error(f"compare_scenarios error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Attachment-reading tools
# ---------------------------------------------------------------------------

def _resolve_attachment(ref_id: str, required_kind: Optional[str] = None) -> Dict[str, Any]:
    """Look up an attachment by ref_id using the active session contextvar.
    Returns the full manifest entry or {"error": ...}."""
    try:
        from app.utils.attachment_store import AttachmentStore, current_session_id
    except Exception as e:
        return {"error": f"Attachment store unavailable: {e}"}

    sid = current_session_id.get()
    if not sid:
        return {"error": "No active session_id — attachments cannot be resolved."}

    store = AttachmentStore(sid)
    entry = store.get(ref_id)
    if entry is None:
        return {
            "error": f"Attachment '{ref_id}' not found in session {sid}. "
                     f"Known ref_ids: {[e.get('ref_id') for e in store.list_manifest()]}"
        }
    if required_kind and entry.get("kind") != required_kind:
        return {
            "error": f"Attachment '{ref_id}' is kind='{entry.get('kind')}', "
                     f"but this tool requires kind='{required_kind}'."
        }
    return entry


def read_pdf_attachment(
    ref_id: str,
    pages: Optional[List[int]] = None,
    max_chars: int = 8000,
) -> Dict[str, Any]:
    """
    Extract text from an attached PDF.

    Args:
        ref_id:    Attachment ref id from the attachments context block.
        pages:     Optional 1-indexed page numbers to read (None = all).
        max_chars: Truncate extracted text to this many characters.

    Returns:
        {ref_id, filename, n_pages, pages_read, text, truncated} or {"error": ...}
    """
    entry = _resolve_attachment(ref_id, required_kind="pdf")
    if "error" in entry:
        return entry
    try:
        from pypdf import PdfReader
        reader = PdfReader(entry["path"])
        total = len(reader.pages)

        if pages:
            page_indices = [p - 1 for p in pages if 1 <= p <= total]
        else:
            page_indices = list(range(total))

        collected: List[str] = []
        chars_left = max_chars
        pages_read: List[int] = []
        for i in page_indices:
            try:
                t = reader.pages[i].extract_text() or ""
            except Exception:
                t = ""
            if not t:
                continue
            snippet = t[:chars_left]
            collected.append(f"--- Page {i + 1} ---\n{snippet}")
            chars_left -= len(snippet)
            pages_read.append(i + 1)
            if chars_left <= 0:
                break

        text = "\n\n".join(collected)
        return {
            "ref_id": ref_id,
            "filename": entry.get("filename"),
            "n_pages": total,
            "pages_read": pages_read,
            "text": text,
            "truncated": chars_left <= 0,
        }
    except Exception as e:
        logger.error(f"read_pdf_attachment error: {e}")
        return {"error": str(e)}


def read_tabular_attachment(
    ref_id: str,
    sheet: Optional[str] = None,
    head_rows: int = 50,
    as_records: bool = True,
) -> Dict[str, Any]:
    """
    Read rows from an attached Excel/CSV file.

    Args:
        ref_id:     Attachment ref id.
        sheet:      Sheet name (Excel only). If None, uses the first sheet.
        head_rows:  Max rows to return (default 50).
        as_records: True → list of row dicts; False → column-oriented dict.

    Returns:
        {ref_id, filename, sheet, columns, n_rows, rows, truncated} or {"error": ...}
    """
    entry = _resolve_attachment(ref_id, required_kind="tabular")
    if "error" in entry:
        return entry
    try:
        import pandas as pd
        path = entry["path"]
        ext = path.lower().rsplit(".", 1)[-1]

        if ext == "csv":
            df = pd.read_csv(path)
            sheet_name = "data"
        else:
            xls = pd.ExcelFile(path)
            sheet_name = sheet or xls.sheet_names[0]
            if sheet_name not in xls.sheet_names:
                return {
                    "error": f"Sheet '{sheet}' not found. "
                             f"Available: {xls.sheet_names}"
                }
            df = xls.parse(sheet_name)

        n_total = int(len(df))
        head = df.head(head_rows)
        rows = (
            json.loads(head.to_json(orient="records", default_handler=str))
            if as_records
            else json.loads(head.to_json(orient="split", default_handler=str))
        )

        return {
            "ref_id": ref_id,
            "filename": entry.get("filename"),
            "sheet": sheet_name,
            "columns": [str(c) for c in df.columns],
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "n_rows_total": n_total,
            "n_rows_returned": min(head_rows, n_total),
            "rows": rows,
            "truncated": n_total > head_rows,
        }
    except Exception as e:
        logger.error(f"read_tabular_attachment error: {e}")
        return {"error": str(e)}


def compute_temporal_analysis(
    index: str = "NDVI",
    dates: Optional[List[str]] = None,
    geometry: Optional[Dict[str, Any]] = None,
    boundary_sql: Optional[str] = None,
    bbox: Optional[Dict[str, float]] = None,
    polygons_sql: Optional[str] = None,
    area_label: str = "area",
) -> Dict[str, Any]:
    """
    Compute a spectral index across all available (or specified) satellite dates and
    merge results into a single FeatureCollection with per-date columns plus a
    change/trend column. Works with any index (NDVI, EVI, NDWI, …) and any number
    of dates (2 or more). When dates is None, all dates found in the session are used.

    Exactly one geometry source must be supplied (geometry, boundary_sql, or bbox).
    Returns a FeatureCollection with {index}_mean_{date} columns per polygon plus
    {index}_change (= last_date_value − first_date_value).
    """
    try:
        from app.utils.attachment_store import current_session_id
        from app.routes.satellite import _load_session
    except Exception as e:
        return {"error": f"Satellite pipeline unavailable: {e}"}

    sid = current_session_id.get()
    if not sid:
        return {"error": "No active session — attach satellite files via the chat attach button first."}

    session_files = _load_session(sid)
    if not session_files:
        return {"error": "No satellite files in this session. Attach Sentinel-2 files first."}

    date_list = sorted(set(dates)) if dates else sorted({e["date"] for e in session_files if e.get("date")})
    if not date_list:
        return {"error": "No satellite dates found. Attach satellite files or specify dates explicitly."}
    if len(date_list) < 2:
        return {
            "error": (
                f"Temporal analysis requires at least 2 dates. Only found: {date_list}. "
                "Use compute_spectral_index for a single-date query."
            )
        }

    shared_kwargs = {
        "index": index,
        "geometry": geometry,
        "boundary_sql": boundary_sql,
        "bbox": bbox,
        "polygons_sql": polygons_sql,
        "area_label": area_label,
    }

    idx_lower = index.lower()
    mean_col = f"{idx_lower}_mean"
    date_results: Dict[str, Dict] = {}

    for d in date_list:
        result = compute_spectral_index(date=d, **shared_kwargs)
        if isinstance(result, dict) and result.get("error"):
            return {"error": f"Failed for date {d}: {result['error']}"}
        if not isinstance(result, dict) or result.get("type") != "FeatureCollection":
            return {"error": f"Unexpected result for date {d}"}
        date_results[d] = result

    first_date, last_date = date_list[0], date_list[-1]
    first_fc = date_results[first_date]

    def _fid(feature: Dict, fallback: int) -> str:
        props = feature.get("properties") or {}
        return str(props.get("id") or props.get("uuid") or fallback)

    date_lookup: Dict[str, Dict[str, Optional[float]]] = {}
    for d, fc in date_results.items():
        date_lookup[d] = {
            _fid(f, i): (f.get("properties") or {}).get(mean_col)
            for i, f in enumerate(fc.get("features", []))
        }

    merged_features = []
    for i, base_feat in enumerate(first_fc.get("features", [])):
        fid = _fid(base_feat, i)
        props = dict(base_feat.get("properties") or {})
        props.pop(mean_col, None)

        first_val = last_val = None
        for d in date_list:
            val = date_lookup[d].get(fid)
            props[f"{idx_lower}_mean_{d.replace('-', '_')}"] = val
            if d == first_date:
                first_val = val
            if d == last_date:
                last_val = val

        props[f"{idx_lower}_change"] = (
            round(last_val - first_val, 4)
            if first_val is not None and last_val is not None
            else None
        )
        merged_features.append({"type": "Feature", "geometry": base_feat.get("geometry"), "properties": props})

    merged_fc: Dict[str, Any] = {"type": "FeatureCollection", "features": merged_features}

    layer_name = f"{idx_lower}_change_{area_label.lower().replace(' ', '_')}"
    saved = save_generated_layer(
        merged_fc, layer_name,
        f"{index.upper()} temporal analysis ({first_date} → {last_date})",
    )

    change_values = [
        f["properties"][f"{idx_lower}_change"]
        for f in merged_features
        if f["properties"].get(f"{idx_lower}_change") is not None
    ]
    enriched = dict(merged_fc)
    enriched["metadata"] = {
        "index": idx_lower,
        "dates": date_list,
        "area_label": area_label,
        "choropleth_property": f"{idx_lower}_change",
        "choropleth_min": float(min(change_values)) if change_values else -1.0,
        "choropleth_max": float(max(change_values)) if change_values else 1.0,
        "feature_count": len(merged_features),
        "is_satellite_result": True,
    }
    if isinstance(saved, dict) and saved.get("saved"):
        enriched["saved_table"] = saved.get("table")
    return enriched


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to callables for the orchestrator
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    "geocode_location": geocode_location,
    "create_buffer": create_buffer,
    "find_tables_by_concept": find_tables_by_concept,
    "get_schema_info": get_schema_info,
    "get_table_columns": get_table_columns,
    "execute_sql": execute_sql,
    "spatial_filter": spatial_filter,
    "calculate_route": calculate_route,
    "walking_isochrone": walking_isochrone,
    "compute_spectral_index": compute_spectral_index,
    "compute_temporal_analysis": compute_temporal_analysis,
    "score_locations": score_locations,
    # --- Persistence ---
    "save_generated_layer": save_generated_layer,
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
    # --- E: Chat attachments ---
    "read_pdf_attachment": read_pdf_attachment,
    "read_tabular_attachment": read_tabular_attachment,
}
