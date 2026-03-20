"""
Walking Distance Service

Provides realistic walking distance calculations using Valhalla routing engine.
Given a starting point and time limit, finds all buildings accessible
within that walking time using Valhalla's isochrone API.
"""

from typing import Dict, Any, List, Optional
import json
import logging
from app.utils.database import db_manager

logger = logging.getLogger(__name__)

# Walking speed constants
WALKING_SPEED_KMH = 5.1  # Valhalla default pedestrian speed
WALKING_SPEED_M_PER_MIN = 85.0  # ~5.1 km/h
WALKING_SPEED_M_PER_SEC = 1.417

# Default buffer distance for buildings "along" a road
DEFAULT_BUILDING_BUFFER_M = 30.0


class WalkingDistanceService:
    """
    Service for computing walking distance accessibility.
    
    Uses Valhalla's isochrone API to determine reachable areas,
    then finds buildings within those areas using PostGIS.
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

    def get_reachable_roads(
        self, 
        lat: float, 
        lon: float, 
        time_minutes: float
    ) -> Dict[str, Any]:
        """
        Get the walking coverage area as a polygon using Valhalla isochrone.
        
        Args:
            lat: Starting latitude
            lon: Starting longitude  
            time_minutes: Maximum walking time in minutes
            
        Returns:
            GeoJSON FeatureCollection with coverage polygon
        """
        try:
            from app.utils.valhalla_routing import valhalla_service
            
            logger.info(f"🚶 Getting reachable area for {time_minutes} min walk from ({lat}, {lon})")
            
            isochrone_result = valhalla_service.get_walking_isochrone(
                lat=lat,
                lon=lon,
                time_minutes=time_minutes,
                denoise=0.5,
                generalize=20
            )
            
            if not isochrone_result.success:
                return {"success": False, "error": f"Valhalla isochrone failed: {isochrone_result.error}"}
            
            feature = {
                "type": "Feature",
                "geometry": isochrone_result.geometry,
                "properties": {
                    "type": "walking_coverage",
                    "time_minutes": time_minutes,
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
                    "time_minutes": time_minutes,
                    "distance_limit_m": self.time_to_distance(time_minutes),
                    "road_count": 1,  # Single isochrone polygon
                    "routing_engine": "valhalla"
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
        building_table: str = "alkis_buildings",
        building_filter: str = None,
        buffer_m: float = DEFAULT_BUILDING_BUFFER_M,
        limit: int = 5000
    ) -> Dict[str, Any]:
        """
        Find buildings accessible within the specified walking time using Valhalla isochrones.
        
        This method uses Valhalla's native isochrone API:
        - Proper pedestrian routing with realistic walking speeds
        - No fragmented network issues
        - Native polygon generation
        
        Args:
            lat: Starting latitude
            lon: Starting longitude
            time_minutes: Maximum walking time in minutes
            building_table: Table containing buildings (in vector schema)
            building_filter: Optional SQL WHERE clause filter
            buffer_m: Buffer distance from roads in meters (default 30m)
            limit: Maximum number of buildings to return
            
        Returns:
            GeoJSON FeatureCollection of accessible buildings
        """
        try:
            from app.utils.valhalla_routing import valhalla_service
            
            # Check if Valhalla is available
            health = valhalla_service.check_health()
            if health.get("status") != "healthy":
                return {"success": False, "error": f"Valhalla routing service unavailable: {health.get('error')}"}
            
            # Get isochrone from Valhalla
            logger.info(f"🚶 Using Valhalla isochrone for {time_minutes} min walk from ({lat}, {lon})")
            isochrone_result = valhalla_service.get_walking_isochrone(
                lat=lat,
                lon=lon,
                time_minutes=time_minutes,
                denoise=0.5,
                generalize=20
            )
            
            if not isochrone_result.success:
                return {"success": False, "error": f"Valhalla isochrone failed: {isochrone_result.error}"}
            
            isochrone_geojson = json.dumps(isochrone_result.geometry)
            
            # Build WHERE clause for optional building filter
            where_clause = ""
            if building_filter:
                safe_filter = building_filter.strip()
                if safe_filter:
                    where_clause = f"WHERE {safe_filter}"
                    logger.info(f"📋 Applying building filter: {safe_filter}")
            
            # Find buildings within the isochrone polygon
            query = f"""
            WITH isochrone AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON('{isochrone_geojson}'), 4326) as geom
            ),
            filtered_features AS (
                SELECT * FROM vector.{building_table}
                {where_clause}
            ),
            accessible_features AS (
                SELECT 
                    b.*,
                    ROW_NUMBER() OVER (ORDER BY ST_Distance(
                        b.geometry,
                        ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)
                    )) as row_id,
                    ST_Distance(
                        ST_Transform(b.geometry, 25833),
                        ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 25833)
                    ) as straight_line_m
                FROM filtered_features b
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
            FROM accessible_features
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
                    "walking_speed_kmh": WALKING_SPEED_KMH
                },
                "isochrone": isochrone_result.geometry
            }
            
        except ImportError:
            return {"success": False, "error": "Valhalla routing module not available"}
        except Exception as e:
            logger.error(f"Error with Valhalla walking time query: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def get_walking_coverage(
        self,
        lat: float,
        lon: float,
        time_minutes: float,
        buffer_m: float = DEFAULT_BUILDING_BUFFER_M
    ) -> Dict[str, Any]:
        """
        Get the walking coverage area as a polygon using Valhalla isochrone.
        
        Args:
            lat: Starting latitude
            lon: Starting longitude
            time_minutes: Maximum walking time in minutes
            buffer_m: Buffer distance (unused, kept for API compatibility)
            
        Returns:
            GeoJSON Feature with coverage polygon
        """
        try:
            from app.utils.valhalla_routing import valhalla_service
            
            isochrone_result = valhalla_service.get_walking_isochrone(
                lat=lat,
                lon=lon,
                time_minutes=time_minutes,
                denoise=0.5,
                generalize=50
            )
            
            if not isochrone_result.success:
                return {"success": False, "error": f"Valhalla isochrone failed: {isochrone_result.error}"}

            feature = {
                "type": "Feature",
                "geometry": isochrone_result.geometry,
                "properties": {
                    "type": "walking_coverage",
                    "time_minutes": time_minutes,
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
                    "distance_limit_m": self.time_to_distance(time_minutes),
                    "routing_engine": "valhalla"
                }
            }

        except Exception as e:
            logger.error(f"Error getting walking coverage: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


# Singleton instance
walking_distance_service = WalkingDistanceService()
