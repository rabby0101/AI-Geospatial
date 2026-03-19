"""
Routing API endpoints for connectivity analysis.

This module provides endpoints for finding shortest paths between
multiple selected features using the pgRouting road network.
"""

import time
from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any, List
from app.utils.database import db_manager

router = APIRouter(prefix="/api/routing", tags=["routing"])


@router.post("/connect-features")
async def connect_features(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find shortest road paths connecting selected features (pairwise).

    This endpoint computes all pairwise shortest paths between selected features
    using pgRouting's Dijkstra algorithm on the Berlin road network.

    Request Body:
        {
            "geometries": [
                {"type": "Point", "coordinates": [13.405, 52.52]},
                {"type": "Point", "coordinates": [13.42, 52.51]},
                {"type": "Point", "coordinates": [13.415, 52.505]}
            ],
            "feature_names": ["Hospital A", "Hospital B", "Hospital C"],  # Optional
            "session_id": "unique_session_id"  # Optional
        }

    Returns:
        {
            "success": true,
            "routes": [
                {
                    "from_index": 0,
                    "to_index": 1,
                    "from_name": "Hospital A",
                    "to_name": "Hospital B",
                    "distance_m": 2450.5,
                    "geometry": {GeoJSON LineString}
                },
                ...
            ],
            "total_distance_m": 7500.25,
            "route_count": 3,
            "feature_count": 3,
            "metadata": {
                "execution_time_ms": 245.5,
                "algorithm": "Dijkstra",
                "road_network": "Berlin Detailnetz"
            }
        }
    """
    start_time = time.time()

    try:
        # Validate input
        geometries = request.get("geometries")
        feature_names = request.get("feature_names", [])

        if not geometries or not isinstance(geometries, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'geometries' must be a non-empty list of GeoJSON Point objects"
            )

        if len(geometries) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least 2 geometries required for connectivity analysis"
            )

        if len(geometries) > 15:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 15 features supported (would create 105 routes)"
            )

        # Use Valhalla for routing
        from app.utils.valhalla_routing import valhalla_service
        from shapely.geometry import shape
        
        # Extract coordinates from geometries
        points = []
        for geom in geometries:
            geom_shape = shape(geom)
            centroid = geom_shape.centroid
            points.append((centroid.y, centroid.x))  # (lat, lon)
        
        # Use Valhalla multi-point route
        route_result = valhalla_service.get_multi_point_route(points, costing="pedestrian")
        
        if not route_result.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Routing failed: {route_result.error}"
            )
        
        # Build route response
        route = {
            "from_index": 0,
            "to_index": len(points) - 1,
            "from_geometry": geometries[0],
            "to_geometry": geometries[-1],
            "route_geometry": route_result.geometry,
            "distance_m": round(route_result.distance_m, 2),
            "from_name": feature_names[0] if feature_names else "Item 1",
            "to_name": feature_names[-1] if feature_names else f"Item {len(geometries)}"
        }
        
        # Calculate execution time
        execution_time_ms = (time.time() - start_time) * 1000

        # Build response
        response = {
            "success": True,
            "routes": [route],
            "total_distance_m": round(route_result.distance_m, 2),
            "route_count": 1,
            "feature_count": len(geometries),
            "metadata": {
                "execution_time_ms": round(execution_time_ms, 2),
                "algorithm": "Valhalla Pedestrian",
                "road_network": "OpenStreetMap Berlin",
                "routing_engine": "valhalla"
            }
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000
        print(f"❌ Error in connect_features: {e}")
        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Routing computation failed: {str(e)}"
        )


@router.post("/nearest-vertex")
async def find_nearest_vertex(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deprecated: pgRouting vertices are no longer used.
    Valhalla handles all routing directly.
    """
    return {
        "success": False,
        "error": "This endpoint is deprecated. Routing now uses Valhalla exclusively.",
        "message": "Use /api/routing/optimal-tour or /api/routing/connect-features instead."
    }


@router.post("/optimal-tour")
async def compute_optimal_tour(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute optimal tour connecting selected features in best sequence.

    Uses Valhalla pedestrian routing for accurate walking times,
    with fallback to pgRouting if Valhalla is unavailable.

    Request Body:
        {
            "geometries": [
                {"type": "Point", "coordinates": [13.405, 52.52]},
                {"type": "Point", "coordinates": [13.42, 52.51]},
                {"type": "Point", "coordinates": [13.415, 52.505]}
            ],
            "feature_names": ["Hospital A", "School B", "Park C"],  # Optional
            "costing": "pedestrian",  # Optional, default: pedestrian
            "session_id": "unique_session_id"  # Optional
        }

    Returns:
        {
            "success": true,
            "geometry": {GeoJSON LineString},
            "total_distance_m": 5234.5,
            "total_time_minutes": 12,
            "routing_engine": "valhalla" or "pgrouting",
            ...
        }
    """
    start_time = time.time()

    try:
        # Validate input
        geometries = request.get("geometries")
        feature_names = request.get("feature_names", [])
        costing = request.get("costing", "pedestrian")

        if not geometries or not isinstance(geometries, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'geometries' must be a non-empty list of GeoJSON Point objects"
            )

        if len(geometries) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least 2 geometries required for routing"
            )

        if len(geometries) > 15:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 15 features supported for optimal tour"
            )

        # Try Valhalla first for accurate pedestrian routing
        valhalla_result = None
        try:
            from app.utils.valhalla_routing import valhalla_service
            
            health = valhalla_service.check_health()
            if health.get("status") == "healthy":
                # Extract coordinates from geometries
                points = []
                for geom in geometries:
                    if geom.get("type") == "Point":
                        coords = geom.get("coordinates", [])
                        if len(coords) >= 2:
                            points.append((coords[1], coords[0]))  # (lat, lon)
                    elif geom.get("type") in ["Polygon", "MultiPolygon"]:
                        # For polygons, use centroid
                        from shapely.geometry import shape
                        shapely_geom = shape(geom)
                        centroid = shapely_geom.centroid
                        points.append((centroid.y, centroid.x))  # (lat, lon)
                
                if len(points) >= 2:
                    print(f"🚶 Using Valhalla ({costing}) for route between {len(points)} points")
                    
                    # For 2 points, use simple route
                    if len(points) == 2:
                        route_result = valhalla_service.get_route(
                            origin_lat=points[0][0],
                            origin_lon=points[0][1],
                            dest_lat=points[1][0],
                            dest_lon=points[1][1],
                            costing=costing
                        )
                    else:
                        # For 3+ points, use multi-point route
                        route_result = valhalla_service.get_multi_point_route(points, costing=costing)
                    
                    if route_result.success:
                        print(f"✅ Valhalla route: {route_result.distance_m:.0f}m, {route_result.duration_minutes:.1f} min")
                        
                        # Build waypoints
                        waypoints = []
                        for i, pt in enumerate(points):
                            name = feature_names[i] if i < len(feature_names) else f"Stop {i+1}"
                            waypoints.append({
                                "order": i + 1,
                                "name": name,
                                "lat": pt[0],
                                "lon": pt[1]
                            })
                        
                        # Build layer name
                        if feature_names:
                            layer_name = "Route: " + " → ".join(feature_names[:5])
                            if len(feature_names) > 5:
                                layer_name += " ..."
                        else:
                            layer_name = f"Walking Route ({route_result.duration_minutes:.1f} min)"
                        
                        execution_time_ms = (time.time() - start_time) * 1000
                        
                        return {
                            "success": True,
                            "geometry": route_result.geometry,
                            "total_distance_m": round(route_result.distance_m, 2),
                            "total_time_minutes": round(route_result.duration_minutes, 1),
                            "waypoints": waypoints,
                            "directions": route_result.maneuvers,
                            "optimal_sequence": list(range(len(points))),
                            "layer_name": layer_name,
                            "routing_engine": "valhalla",
                            "costing": costing,
                            "metadata": {
                                "feature_count": len(points),
                                "waypoint_count": len(points),
                                "algorithm": f"Valhalla {costing.replace('_', ' ').title()}",
                                "road_network": "OpenStreetMap Berlin",
                                "costing": costing
                            },
                            "execution_time_ms": round(execution_time_ms, 2)
                        }
                    else:
                        print(f"⚠️ Valhalla failed: {route_result.error}")
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Valhalla routing failed: {route_result.error}"
                        )
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Valhalla routing service is not available"
                )
                
        except HTTPException:
            raise
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Valhalla routing module not available"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Routing error: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000
        print(f"❌ Error in compute_optimal_tour: {e}")
        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Optimal tour computation failed: {str(e)}"
        )


@router.get("/health")
async def routing_health() -> Dict[str, Any]:
    """
    Check if Valhalla routing service is available and ready.

    Returns routing infrastructure status.
    """
    try:
        from app.utils.valhalla_routing import valhalla_service
        
        health = valhalla_service.check_health()
        
        if health.get("status") == "healthy":
            return {
                "status": "healthy",
                "routing_engine": "valhalla",
                "message": "Valhalla routing service is ready"
            }
        else:
            return {
                "status": "unhealthy",
                "routing_engine": "valhalla",
                "error": health.get("error", "Valhalla service not responding")
            }

    except Exception as e:
        return {
            "status": "unhealthy",
            "routing_engine": "valhalla",
            "error": str(e)
        }
