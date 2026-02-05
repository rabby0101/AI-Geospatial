"""
Walking Distance Service

Provides realistic walking distance calculations using the road network.
Given a starting point and time limit, finds all buildings accessible
within that walking time by following actual roads.

Uses pgr_drivingDistance to find reachable road segments, then identifies
buildings adjacent to those roads.
"""

from typing import Dict, Any, List, Optional
import json
import logging
from app.utils.database import db_manager

logger = logging.getLogger(__name__)

# Walking speed constants
WALKING_SPEED_KMH = 6.0  # Average walking speed in km/h
WALKING_SPEED_M_PER_MIN = 100.0  # 6 km/h = 100 meters per minute
WALKING_SPEED_M_PER_SEC = 1.667  # ~1.67 m/s

# Default buffer distance for buildings "along" a road
DEFAULT_BUILDING_BUFFER_M = 30.0


class WalkingDistanceService:
    """
    Service for computing walking distance accessibility.
    
    Uses pgRouting's pgr_drivingDistance to find all road segments
    reachable within a given walking time, then finds buildings
    adjacent to those roads.
    """

    def time_to_distance(self, time_minutes: float) -> float:
        """
        Convert walking time to distance in meters.
        
        Args:
            time_minutes: Walking time in minutes
            
        Returns:
            Distance in meters
        """
        return time_minutes * WALKING_SPEED_M_PER_MIN

    def _get_start_vertex(self, lat: float, lon: float) -> Optional[int]:
        """
        Find the nearest road network vertex to the given point.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            Vertex ID or None if not found
        """
        try:
            # Optimized & Robust: Find vertex from nearest footway edge using double JOIN
            # Avoids ST_StartPoint/ST_LineLocatePoint on MultiLineString
            query = """
            WITH nearest_edge AS (
                SELECT source, target
                FROM vector.custom_roads
                WHERE fclass IN ('footway', 'path', 'pedestrian', 'steps', 'living_street')
                ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                LIMIT 1
            ),
            params AS (
                SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography as pt
            )
            SELECT 
                CASE 
                    WHEN ST_Distance(v1.the_geom::geography, p.pt) < ST_Distance(v2.the_geom::geography, p.pt)
                    THEN v1.id 
                    ELSE v2.id 
                END as vertex_id,
                LEAST(
                    ST_Distance(v1.the_geom::geography, p.pt),
                    ST_Distance(v2.the_geom::geography, p.pt)
                ) as distance_m
            FROM nearest_edge ne
            CROSS JOIN params p
            JOIN vector.custom_roads_vertices_pgr v1 ON v1.id = ne.source
            JOIN vector.custom_roads_vertices_pgr v2 ON v2.id = ne.target
            """
            result = db_manager.execute_query(query.replace(':lon', str(lon)).replace(':lat', str(lat)))
            if not result.empty:
                vertex_id = int(result.iloc[0]['vertex_id'])
                distance = float(result.iloc[0]['distance_m'])
                logger.info(f"📍 Found start vertex {vertex_id} ({distance:.0f}m from point)")
                return vertex_id
            return None
        except Exception as e:
            logger.error(f"Error finding start vertex: {e}")
            return None

    def get_reachable_roads(
        self, 
        lat: float, 
        lon: float, 
        time_minutes: float
    ) -> Dict[str, Any]:
        """
        Get all road segments reachable within the specified walking time.
        
        Uses pgr_drivingDistance to find all vertices reachable within
        the distance limit, then gets the road geometries connecting them.
        
        Args:
            lat: Starting latitude
            lon: Starting longitude  
            time_minutes: Maximum walking time in minutes
            
        Returns:
            GeoJSON FeatureCollection of reachable road segments
        """
        try:
            # 1. Find starting vertex
            start_vertex = self._get_start_vertex(lat, lon)
            if not start_vertex:
                return {"success": False, "error": "Could not find road network near starting point"}

            # 2. Convert time to distance
            distance_limit = self.time_to_distance(time_minutes)
            logger.info(f"🚶 Walking {time_minutes} min = {distance_limit}m distance limit")

            # 3. Use pgr_drivingDistance to find reachable nodes and edges
            # The 'cost' column in custom_roads is in meters
            query = f"""
            WITH reachable AS (
                SELECT * FROM pgr_drivingDistance(
                    'SELECT id, source, target, cost, reverse_cost FROM vector.custom_roads WHERE source != target AND fclass IN (''footway'', ''path'', ''pedestrian'', ''steps'', ''living_street'')',
                    {start_vertex},
                    {distance_limit},
                    true  -- directed
                )
            ),
            reachable_edges AS (
                -- Get all edges that connect reachable nodes (ONLY footways/paths)
                SELECT DISTINCT r.id, r.geometry, r.fclass, r.name,
                       LEAST(d1.agg_cost, d2.agg_cost) as min_cost
                FROM vector.custom_roads r
                JOIN reachable d1 ON r.source = d1.node
                JOIN reachable d2 ON r.target = d2.node
                WHERE r.fclass IN ('footway', 'path', 'pedestrian', 'steps', 'living_street')
            )
            SELECT 
                json_build_object(
                    'type', 'FeatureCollection',
                    'features', COALESCE(json_agg(
                        json_build_object(
                            'type', 'Feature',
                            'geometry', ST_AsGeoJSON(geometry)::json,
                            'properties', json_build_object(
                                'id', id,
                                'fclass', fclass,
                                'name', name,
                                'walking_time_min', min_cost / {WALKING_SPEED_M_PER_MIN}
                            )
                        )
                    ), '[]'::json)
                ) as geojson
            FROM reachable_edges
            """

            result = db_manager.execute_query(query)
            
            if result.empty or result.iloc[0]['geojson'] is None:
                return {"success": False, "error": "No reachable roads found"}

            geojson = result.iloc[0]['geojson']
            if isinstance(geojson, str):
                geojson = json.loads(geojson)

            feature_count = len(geojson.get('features', []))
            logger.info(f"✅ Found {feature_count} reachable road segments")

            return {
                "success": True,
                "data": geojson,
                "metadata": {
                    "start_vertex": start_vertex,
                    "time_minutes": time_minutes,
                    "distance_limit_m": distance_limit,
                    "road_count": feature_count
                }
            }

        except Exception as e:
            logger.error(f"Error getting reachable roads: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def find_buildings_within_walking_time(
        self,
        lat: float,
        lon: float, 
        time_minutes: float,
        building_table: str = "osm_buildings",
        buffer_m: float = DEFAULT_BUILDING_BUFFER_M,
        limit: int = 5000
    ) -> Dict[str, Any]:
        """
        Find buildings accessible within the specified walking time.
        
        This method:
        1. Finds all road segments reachable within walking time
        2. Creates a buffer around those roads
        3. Returns buildings that intersect with the buffered road network
        
        Args:
            lat: Starting latitude (e.g., supermarket location)
            lon: Starting longitude
            time_minutes: Maximum walking time in minutes
            building_table: Table containing buildings (in vector schema)
            buffer_m: Buffer distance from roads in meters (default 30m)
            limit: Maximum number of buildings to return
            
        Returns:
            GeoJSON FeatureCollection of accessible buildings
        """
        try:
            # 1. Find starting vertex
            start_vertex = self._get_start_vertex(lat, lon)
            if not start_vertex:
                return {"success": False, "error": "Could not find road network near starting point"}

            # 2. Convert time to distance
            distance_limit = self.time_to_distance(time_minutes)
            logger.info(f"🚶 Finding buildings within {time_minutes} min walk ({distance_limit}m)")

            # 3. Improved query that verifies ACTUAL footway routability:
            # - Get reachable nodes from pgr_drivingDistance
            # - Find the nearest footway vertex for each building
            # - Only include buildings whose nearest vertex is in the reachable set
            # - Use the actual walking distance (agg_cost) from the routing
            query = f"""
            WITH reachable AS (
                -- Get all nodes reachable within walking distance via footway network
                SELECT node, agg_cost FROM pgr_drivingDistance(
                    'SELECT id, source, target, cost, reverse_cost FROM vector.custom_roads WHERE source != target AND fclass IN (''footway'', ''path'', ''pedestrian'', ''steps'', ''living_street'')',
                    {start_vertex},
                    {distance_limit},
                    true
                )
            ),
            reachable_vertices AS (
                -- Get the actual vertex coordinates for reachable nodes
                SELECT 
                    v.id as vertex_id, 
                    v.the_geom as vertex_geom,
                    r.agg_cost as walking_distance_m
                FROM vector.custom_roads_vertices_pgr v
                JOIN reachable r ON v.id = r.node
            ),
            building_vertices AS (
                -- For each building, find which reachable vertex is closest
                -- This ensures the building is actually connected to the reachable network
                SELECT DISTINCT ON (b.geometry)
                    b.geometry,
                    rv.vertex_id,
                    rv.walking_distance_m,
                    ST_Distance(
                        ST_Transform(b.geometry, 25833),
                        ST_Transform(rv.vertex_geom, 25833)
                    ) as distance_to_vertex_m
                FROM vector.{building_table} b
                CROSS JOIN LATERAL (
                    -- Find the closest reachable vertex to this building
                    SELECT rv.vertex_id, rv.walking_distance_m, rv.vertex_geom
                    FROM reachable_vertices rv
                    ORDER BY ST_Distance(b.geometry, rv.vertex_geom)
                    LIMIT 1
                ) rv
                -- Only include buildings within {buffer_m}m of a reachable footway vertex
                WHERE ST_DWithin(
                    ST_Transform(b.geometry, 25833),
                    ST_Transform(rv.vertex_geom, 25833),
                    {buffer_m}
                )
            ),
            accessible_buildings AS (
                -- Calculate total walking distance = distance to start vertex + distance along network
                SELECT 
                    geometry,
                    ROW_NUMBER() OVER (ORDER BY (walking_distance_m + distance_to_vertex_m)) as row_id,
                    walking_distance_m,
                    distance_to_vertex_m,
                    (walking_distance_m + distance_to_vertex_m) as total_walking_distance_m,
                    ((walking_distance_m + distance_to_vertex_m) / {WALKING_SPEED_M_PER_MIN}) as walking_time_min
                FROM building_vertices
                -- Filter to only buildings within the time limit (with some buffer for vertex distance)
                WHERE (walking_distance_m + distance_to_vertex_m) <= {distance_limit} + {buffer_m}
                ORDER BY total_walking_distance_m
                LIMIT {limit}
            )
            SELECT 
                json_build_object(
                    'type', 'FeatureCollection',
                    'features', COALESCE(json_agg(
                        json_build_object(
                            'type', 'Feature',
                            'geometry', ST_AsGeoJSON(geometry)::json,
                            'properties', json_build_object(
                                'id', row_id,
                                'walking_distance_m', ROUND(total_walking_distance_m::numeric, 1),
                                'walking_time_min', ROUND(walking_time_min::numeric, 1)
                            )
                        )
                    ), '[]'::json)
                ) as geojson,
                COUNT(*) as building_count
            FROM accessible_buildings
            """

            result = db_manager.execute_query(query)

            if result.empty:
                return {"success": False, "error": "Query returned no results"}

            geojson = result.iloc[0]['geojson']
            building_count = int(result.iloc[0]['building_count'])
            
            if isinstance(geojson, str):
                geojson = json.loads(geojson)

            logger.info(f"✅ Found {building_count} buildings within {time_minutes} min walk")

            return {
                "success": True,
                "data": geojson,
                "metadata": {
                    "start_point": {"lat": lat, "lon": lon},
                    "start_vertex": start_vertex,
                    "time_minutes": time_minutes,
                    "distance_limit_m": distance_limit,
                    "buffer_m": buffer_m,
                    "building_table": building_table,
                    "building_count": building_count,
                    "walking_speed_kmh": WALKING_SPEED_KMH
                }
            }

        except Exception as e:
            logger.error(f"Error finding buildings within walking time: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def find_buildings_within_walking_time_valhalla(
        self,
        lat: float,
        lon: float,
        time_minutes: float,
        building_table: str = "osm_buildings",
        limit: int = 5000
    ) -> Dict[str, Any]:
        """
        Find buildings accessible within the specified walking time using Valhalla isochrones.
        
        This method uses Valhalla's native isochrone API for more accurate results:
        - Proper pedestrian routing with realistic walking speeds
        - No fragmented network issues
        - Native polygon generation
        
        Falls back to pgRouting-based method if Valhalla is unavailable.
        
        Args:
            lat: Starting latitude
            lon: Starting longitude
            time_minutes: Maximum walking time in minutes
            building_table: Table containing buildings (in vector schema)
            limit: Maximum number of buildings to return
            
        Returns:
            GeoJSON FeatureCollection of accessible buildings
        """
        try:
            # Import Valhalla service
            from app.utils.valhalla_routing import valhalla_service
            
            # Check if Valhalla is available
            health = valhalla_service.check_health()
            if health.get("status") != "healthy":
                logger.warning(f"Valhalla unavailable: {health.get('error')}. Falling back to pgRouting.")
                return self.find_buildings_within_walking_time(
                    lat, lon, time_minutes, building_table, limit=limit
                )
            
            # Get isochrone from Valhalla
            logger.info(f"🚶 Using Valhalla isochrone for {time_minutes} min walk from ({lat}, {lon})")
            isochrone_result = valhalla_service.get_walking_isochrone(
                lat=lat,
                lon=lon,
                time_minutes=time_minutes,
                denoise=0.5,
                generalize=20  # Less generalization for accuracy
            )
            
            if not isochrone_result.success:
                logger.error(f"Valhalla isochrone failed: {isochrone_result.error}")
                return self.find_buildings_within_walking_time(
                    lat, lon, time_minutes, building_table, limit=limit
                )
            
            isochrone_geojson = json.dumps(isochrone_result.geometry)
            
            # Find buildings within the isochrone polygon
            query = f"""
            WITH isochrone AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON('{isochrone_geojson}'), 4326) as geom
            ),
            accessible_buildings AS (
                SELECT 
                    b.geometry,
                    ROW_NUMBER() OVER (ORDER BY ST_Distance(
                        b.geometry,
                        ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)
                    )) as row_id,
                    ST_Distance(
                        ST_Transform(b.geometry, 25833),
                        ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 25833)
                    ) as straight_line_m
                FROM vector.{building_table} b
                JOIN isochrone i ON ST_Intersects(b.geometry, i.geom)
                LIMIT {limit}
            )
            SELECT 
                json_build_object(
                    'type', 'FeatureCollection',
                    'features', COALESCE(json_agg(
                        json_build_object(
                            'type', 'Feature',
                            'geometry', ST_AsGeoJSON(geometry)::json,
                            'properties', json_build_object(
                                'id', row_id,
                                'straight_line_m', ROUND(straight_line_m::numeric, 1),
                                'walking_time_min', {time_minutes}
                            )
                        )
                    ), '[]'::json)
                ) as geojson,
                COUNT(*) as building_count
            FROM accessible_buildings
            """
            
            result = db_manager.execute_query(query)
            
            if result.empty:
                return {"success": False, "error": "Query returned no results"}
            
            geojson = result.iloc[0]['geojson']
            building_count = int(result.iloc[0]['building_count'])
            
            if isinstance(geojson, str):
                geojson = json.loads(geojson)
            
            logger.info(f"✅ Found {building_count} buildings within {time_minutes} min walk (Valhalla)")
            
            return {
                "success": True,
                "data": geojson,
                "metadata": {
                    "start_point": {"lat": lat, "lon": lon},
                    "time_minutes": time_minutes,
                    "building_table": building_table,
                    "building_count": building_count,
                    "routing_engine": "valhalla",
                    "walking_speed_kmh": 5.1  # Valhalla default
                },
                "isochrone": isochrone_result.geometry
            }
            
        except ImportError:
            logger.warning("Valhalla module not available. Falling back to pgRouting.")
            return self.find_buildings_within_walking_time(
                lat, lon, time_minutes, building_table, limit=limit
            )
        except Exception as e:
            logger.error(f"Error with Valhalla walking time query: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to pgRouting
            return self.find_buildings_within_walking_time(
                lat, lon, time_minutes, building_table, limit=limit
            )

    def get_walking_coverage(
        self,
        lat: float,
        lon: float,
        time_minutes: float,
        buffer_m: float = DEFAULT_BUILDING_BUFFER_M
    ) -> Dict[str, Any]:
        """
        Get the walking coverage area as a polygon.
        
        Creates a buffered union of all reachable road segments,
        representing the area accessible within walking time.
        
        Args:
            lat: Starting latitude
            lon: Starting longitude
            time_minutes: Maximum walking time in minutes
            buffer_m: Buffer distance from roads in meters
            
        Returns:
            GeoJSON Feature with coverage polygon
        """
        try:
            start_vertex = self._get_start_vertex(lat, lon)
            if not start_vertex:
                return {"success": False, "error": "Could not find road network near starting point"}

            distance_limit = self.time_to_distance(time_minutes)

            query = f"""
            WITH reachable AS (
                SELECT node, agg_cost FROM pgr_drivingDistance(
                    'SELECT id, source, target, cost, reverse_cost FROM vector.custom_roads WHERE source != target AND fclass IN (''footway'', ''path'', ''pedestrian'', ''steps'', ''living_street'')',
                    {start_vertex},
                    {distance_limit},
                    true
                )
            ),
            reachable_roads AS (
                SELECT DISTINCT r.geometry
                FROM vector.custom_roads r
                WHERE (r.source IN (SELECT node FROM reachable)
                   OR r.target IN (SELECT node FROM reachable))
                  AND r.fclass IN ('footway', 'path', 'pedestrian', 'steps', 'living_street')
            ),
            coverage AS (
                SELECT ST_Transform(
                    ST_Buffer(
                        ST_Transform(ST_Union(geometry), 25833),
                        {buffer_m}
                    ),
                    4326
                ) as coverage_geom
                FROM reachable_roads
            )
            SELECT ST_AsGeoJSON(coverage_geom) as geojson
            FROM coverage
            """

            result = db_manager.execute_query(query)

            if result.empty or result.iloc[0]['geojson'] is None:
                return {"success": False, "error": "Could not generate coverage area"}

            geojson = result.iloc[0]['geojson']
            if isinstance(geojson, str):
                geojson = json.loads(geojson)

            feature = {
                "type": "Feature",
                "geometry": geojson,
                "properties": {
                    "type": "walking_coverage",
                    "time_minutes": time_minutes,
                    "buffer_m": buffer_m,
                    "walking_speed_kmh": WALKING_SPEED_KMH
                }
            }

            return {
                "success": True,
                "data": {
                    "type": "FeatureCollection",
                    "features": [feature]
                },
                "metadata": {
                    "start_point": {"lat": lat, "lon": lon},
                    "time_minutes": time_minutes,
                    "distance_limit_m": distance_limit
                }
            }

        except Exception as e:
            logger.error(f"Error getting walking coverage: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


# Singleton instance
walking_distance_service = WalkingDistanceService()
