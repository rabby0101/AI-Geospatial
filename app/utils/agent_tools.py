"""
Agent tools — each function does one thing and returns a plain dict.
Success: dict with result data.
Failure: dict with "error" key.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Union

from shapely.geometry import Point, shape, mapping
from shapely.ops import transform
import pyproj

from app.utils.location_resolver import LocationResolver
from app.utils.database import db_manager

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


def query_features(description: str, within_geometry: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Query the PostGIS database for features matching a natural language description,
    optionally filtered to within a GeoJSON geometry.

    Uses the existing LLM→SQL pipeline to translate the description into SQL.

    Returns:
        {"type": "FeatureCollection", "features": [...], "count": int}
        or {"error": str}
    """
    try:
        from app.utils.deepseek import parse_geospatial_query
        from app.utils.spatial_engine import SpatialEngine

        full_question = description
        if within_geometry:
            geom_str = json.dumps(within_geometry)
            full_question = (
                f"{description}. Only return features within this geometry: {geom_str[:300]}"
            )

        plan = parse_geospatial_query(
            full_question,
            context=None,
            user_location=None,
            selected_feature=None,
            drawn_geometry=within_geometry,
        )

        engine = SpatialEngine()
        result = engine.execute_plan(plan)

        if result.get("success") is False:
            return {"error": result.get("error", "Query returned no results")}

        data = result.get("data", {})
        features = data.get("features", []) if isinstance(data, dict) else []
        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
        }
    except Exception as e:
        logger.error(f"query_features error: {e}")
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
    Score and rank GeoJSON features using MCDA.

    Args:
        features: GeoJSON FeatureCollection
        criteria: List of scoring criteria, e.g. ["near schools", "low noise"]

    Returns:
        GeoJSON FeatureCollection with added "score" property or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan
        import geopandas as gpd

        gdf = gpd.GeoDataFrame.from_features(features.get("features", []), crs="EPSG:4326")
        if gdf.empty:
            return {"error": "No features to score"}

        engine = SpatialEngine()
        query_str = ", ".join(criteria)
        plan = OperationPlan(operations=[], reasoning=query_str)
        scored_gdf = engine.apply_mcda_scoring(gdf, query_str, plan)

        return json.loads(scored_gdf.to_json())
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


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to callables for the orchestrator
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    "geocode_location": geocode_location,
    "create_buffer": create_buffer,
    "get_schema_info": get_schema_info,
    "get_table_columns": get_table_columns,
    "execute_sql": execute_sql,
    "spatial_filter": spatial_filter,
    "calculate_route": calculate_route,
    "walking_isochrone": walking_isochrone,
    "analyze_satellite": analyze_satellite,
    "score_locations": score_locations,
    # kept but not in system prompt — available as fallback
    "query_features": query_features,
}
