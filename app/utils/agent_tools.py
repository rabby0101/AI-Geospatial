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


def get_schema_info(keywords: List[str]) -> Union[List[Dict], Dict]:
    """
    Return relevant table names and descriptions matching the given keywords.

    Returns:
        List of {"table_name": str, "description": str, "geometry_type": str}
        or {"error": str}
    """
    try:
        keyword_conditions = " OR ".join(
            f"(LOWER(table_name) LIKE '%{kw.lower()}%' OR LOWER(description) LIKE '%{kw.lower()}%')"
            for kw in keywords
        )
        sql = f"""
            SELECT table_name, description, geometry_type
            FROM vector.table_metadata
            WHERE {keyword_conditions}
            LIMIT 10
        """
        rows = db_manager.execute_query(sql)
        if rows is None:
            return {"error": "Database query failed"}
        return [dict(r) for r in rows]
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


def calculate_route(waypoints: List[Dict[str, float]], mode: str = "driving") -> Dict[str, Any]:
    """
    Calculate the optimal route between waypoints using pgRouting.

    Args:
        waypoints: List of {"lat": float, "lon": float, "name": str} dicts
        mode: "driving" or "walking"

    Returns:
        GeoJSON FeatureCollection with route LineString + distance/duration properties
        or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan, GeospatialOperation

        engine = SpatialEngine()
        op = GeospatialOperation(
            operation="routing",
            parameters={"waypoints": waypoints, "mode": mode},
            description=f"Route between {len(waypoints)} waypoints",
        )
        plan = OperationPlan(operations=[op], reasoning="Agent-requested routing")
        result = engine._execute_routing_operation(op, plan)

        if not result.get("success"):
            return {"error": result.get("error", "Routing failed")}

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": result.get("geometry", {}),
                    "properties": {
                        "distance_m": result.get("total_distance_m", 0),
                        "duration_s": (result.get("total_time_minutes", 0) or 0) * 60,
                    },
                }
            ],
            "distance_m": result.get("total_distance_m", 0),
            "duration_s": (result.get("total_time_minutes", 0) or 0) * 60,
        }
    except Exception as e:
        logger.error(f"calculate_route error: {e}")
        return {"error": str(e)}


def walking_isochrone(location: Dict[str, float], minutes: int) -> Dict[str, Any]:
    """
    Calculate the area reachable by walking from a location within N minutes.

    Args:
        location: {"lat": float, "lon": float}
        minutes: Walking time in minutes

    Returns:
        GeoJSON FeatureCollection with isochrone Polygon
        or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan, GeospatialOperation

        engine = SpatialEngine()
        op = GeospatialOperation(
            operation="walking_time",
            parameters={"origin": location, "time_minutes": minutes},
            description=f"{minutes}-minute walking isochrone",
        )
        plan = OperationPlan(operations=[op], reasoning="Agent-requested isochrone")
        result = engine._execute_walking_time_operation(op, plan)

        if not result.get("success"):
            return {"error": result.get("error", "Isochrone failed")}

        return result.get("data", {"type": "FeatureCollection", "features": []})
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
# Tool registry — maps tool names to callables for the orchestrator
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    "geocode_location": geocode_location,
    "create_buffer": create_buffer,
    "query_features": query_features,
    "spatial_filter": spatial_filter,
    "get_schema_info": get_schema_info,
    "calculate_route": calculate_route,
    "walking_isochrone": walking_isochrone,
    "analyze_satellite": analyze_satellite,
    "score_locations": score_locations,
}
