"""
Walking Distance API Routes

Provides REST endpoints for walking distance-based spatial queries.
Uses road network routing to find features accessible within a given walking time.
"""

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
import time
from app.utils.walking_distance import walking_distance_service

router = APIRouter(prefix="/api/walking-distance", tags=["walking-distance"])


@router.post("/reachable-roads")
async def get_reachable_roads(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get all road segments reachable within the specified walking time.
    
    This endpoint returns the actual road network that can be traversed
    within the given time limit, starting from the specified location.
    
    Request Body:
        {
            "lat": 52.52,
            "lon": 13.405,
            "time_minutes": 10
        }
        
    Returns:
        {
            "success": true,
            "data": GeoJSON FeatureCollection of road LineStrings,
            "metadata": {
                "time_minutes": 10,
                "distance_limit_m": 1000,
                "road_count": 156
            }
        }
    """
    start_time = time.time()
    
    # Validate required fields
    lat = request.get("lat")
    lon = request.get("lon")
    time_minutes = request.get("time_minutes", 10)
    
    if lat is None or lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: lat, lon"
        )
    
    try:
        lat = float(lat)
        lon = float(lon)
        time_minutes = float(time_minutes)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lat, lon, and time_minutes must be numeric"
        )
    
    if time_minutes <= 0 or time_minutes > 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="time_minutes must be between 0 and 60"
        )
    
    result = walking_distance_service.get_reachable_roads(lat, lon, time_minutes)
    
    result["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


@router.post("/find-buildings")
async def find_buildings_within_walking_time(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find buildings accessible within the specified walking time.
    
    Uses the road network to determine which buildings can be reached
    within the given walking time from the starting point.
    
    Request Body:
        {
            "lat": 52.52,
            "lon": 13.405,
            "time_minutes": 10,
            "building_table": "osm_residential_buildings",  // optional
            "buffer_m": 30  // optional, buffer around roads
        }
        
    Returns:
        {
            "success": true,
            "data": GeoJSON FeatureCollection of buildings,
            "metadata": {
                "building_count": 342,
                "time_minutes": 10,
                "walking_speed_kmh": 6.0
            }
        }
    """
    start_time = time.time()
    
    # Validate required fields
    lat = request.get("lat")
    lon = request.get("lon")
    time_minutes = request.get("time_minutes", 10)
    building_table = request.get("building_table", "osm_buildings")
    buffer_m = request.get("buffer_m", 30)
    limit = request.get("limit", 5000)
    
    if lat is None or lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: lat, lon"
        )
    
    try:
        lat = float(lat)
        lon = float(lon)
        time_minutes = float(time_minutes)
        buffer_m = float(buffer_m)
        limit = int(limit)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid numeric values"
        )
    
    if time_minutes <= 0 or time_minutes > 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="time_minutes must be between 0 and 60"
        )
    
    # Sanitize table name to prevent SQL injection
    allowed_tables = [
        "osm_buildings",
        "osm_supermarkets", 
        "osm_restaurants",
        "osm_hospitals",
        "osm_schools",
        "osm_parks",
        "osm_pharmacies"
    ]
    
    # Also allow any table that starts with osm_ as a fallback
    if building_table not in allowed_tables and not building_table.startswith("osm_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid building_table. Allowed: {allowed_tables}"
        )
    
    result = walking_distance_service.find_buildings_within_walking_time(
        lat=lat,
        lon=lon,
        time_minutes=time_minutes,
        building_table=building_table,
        buffer_m=buffer_m,
        limit=limit
    )
    
    result["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


@router.post("/coverage")
async def get_walking_coverage(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get the walking coverage area as a polygon.
    
    Returns a polygon representing the area accessible within
    the specified walking time from the starting point.
    
    Request Body:
        {
            "lat": 52.52,
            "lon": 13.405,
            "time_minutes": 10,
            "buffer_m": 30  // optional
        }
        
    Returns:
        {
            "success": true,
            "data": GeoJSON FeatureCollection with coverage polygon,
            "metadata": {...}
        }
    """
    start_time = time.time()
    
    lat = request.get("lat")
    lon = request.get("lon")
    time_minutes = request.get("time_minutes", 10)
    buffer_m = request.get("buffer_m", 30)
    
    if lat is None or lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: lat, lon"
        )
    
    try:
        lat = float(lat)
        lon = float(lon)
        time_minutes = float(time_minutes)
        buffer_m = float(buffer_m)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid numeric values"
        )
    
    result = walking_distance_service.get_walking_coverage(
        lat=lat,
        lon=lon,
        time_minutes=time_minutes,
        buffer_m=buffer_m
    )
    
    result["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


@router.get("/health")
async def walking_distance_health() -> Dict[str, Any]:
    """
    Check if walking distance service is ready.
    
    Verifies that the Valhalla routing service is available.
    """
    try:
        from app.utils.valhalla_routing import valhalla_service
        
        health = valhalla_service.check_health()
        
        if health.get("status") != "healthy":
            return {
                "status": "error",
                "message": f"Valhalla routing service unavailable: {health.get('error', 'unknown')}"
            }
        
        return {
            "status": "ready",
            "routing_engine": "valhalla",
            "walking_speed_kmh": 5.1,
            "message": "Walking distance service is ready (Valhalla)"
        }
        
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e)
        }
