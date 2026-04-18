"""
Agent tools — each function does one thing and returns a plain dict.
Success: dict with result data.
Failure: dict with "error" key.
"""
import hashlib
import json
import logging
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


def analyze_satellite(
    bbox: Dict[str, Any],
    indices: List[str],
    date_range: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run satellite spectral analysis over a bounding box.

    Args:
        bbox: GeoJSON Polygon or {"min_lon", "min_lat", "max_lon", "max_lat"}
        indices: List of spectral indices, e.g. ["NDVI", "NDWI"]
        date_range: Optional {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

    Returns:
        GeoJSON FeatureCollection with stats or {"error": str}
    """
    try:
        from app.utils.satellite_processor import SatelliteProcessor

        if isinstance(bbox, dict) and "type" in bbox:
            geom = shape(bbox)
            bounds = geom.bounds  # (min_lon, min_lat, max_lon, max_lat)
        elif all(k in bbox for k in ("min_lon", "min_lat", "max_lon", "max_lat")):
            bounds = (bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"])
        else:
            return {
                "error": "bbox must be a GeoJSON Polygon or dict with min_lon/min_lat/max_lon/max_lat"
            }

        processor = SatelliteProcessor()
        result = processor.analyze_area(bounds=bounds, indices=indices, date_range=date_range)
        if result is None:
            return {"error": "No satellite data found for this area and time range"}
        return result
    except Exception as e:
        logger.error(f"analyze_satellite error: {e}")
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
    "analyze_satellite": analyze_satellite,
    "score_locations": score_locations,
}
