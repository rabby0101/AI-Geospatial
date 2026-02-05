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

        # Compute pairwise shortest paths
        result = db_manager.compute_pairwise_shortest_paths(geometries)

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to compute shortest paths")
            )

        # Enhance routes with feature names if provided
        routes = result.get("routes", [])
        if feature_names:
            for route in routes:
                from_idx = route.get("from_index", 0)
                to_idx = route.get("to_index", 1)

                if from_idx < len(feature_names):
                    route["from_name"] = feature_names[from_idx]
                if to_idx < len(feature_names):
                    route["to_name"] = feature_names[to_idx]

        # Calculate execution time
        execution_time_ms = (time.time() - start_time) * 1000

        # Build response
        response = {
            "success": True,
            "routes": routes,
            "total_distance_m": result.get("total_distance_m", 0),
            "route_count": result.get("route_count", 0),
            "feature_count": result.get("feature_count", 0),
            "metadata": {
                "execution_time_ms": round(execution_time_ms, 2),
                "algorithm": "Dijkstra (pgRouting)",
                "road_network": "Berlin Custom Roads",
                "vertices_snapped": len(result.get("vertices_used", []))
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
    Find the nearest pgRouting vertex to a given point.

    Useful for debugging and understanding vertex snapping.

    Request Body:
        {
            "lon": 13.405,
            "lat": 52.52
        }

    Returns:
        {
            "success": true,
            "vertex_id": 15234,
            "x": 13.4051,
            "y": 52.5201,
            "distance_m": 12.5,
            "message": "Vertex snapped 12.5m from input point"
        }
    """
    try:
        lon = request.get("lon")
        lat = request.get("lat")

        if lon is None or lat is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'lon' and 'lat' are required"
            )

        # Find nearest vertex
        vertex_info = db_manager.find_nearest_vertex_to_point(lon, lat)

        if vertex_info:
            return {
                "success": True,
                **vertex_info,
                "message": f"Vertex snapped {vertex_info['distance_m']:.1f}m from input point"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not find vertex for the given coordinates"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vertex lookup failed: {str(e)}"
        )


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
                    print(f"🚶 Using Valhalla for pedestrian route between {len(points)} points")
                    
                    # For 2 points, use simple route
                    if len(points) == 2:
                        route_result = valhalla_service.get_pedestrian_route(
                            origin_lat=points[0][0],
                            origin_lon=points[0][1],
                            dest_lat=points[1][0],
                            dest_lon=points[1][1]
                        )
                    else:
                        # For 3+ points, use multi-point route
                        route_result = valhalla_service.get_multi_point_route(points)
                    
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
                            "metadata": {
                                "feature_count": len(points),
                                "waypoint_count": len(points),
                                "algorithm": "Valhalla Pedestrian",
                                "road_network": "OpenStreetMap Berlin",
                                "walking_speed_kmh": 5.1
                            },
                            "execution_time_ms": round(execution_time_ms, 2)
                        }
                    else:
                        print(f"⚠️ Valhalla failed: {route_result.error}. Falling back to pgRouting.")
            else:
                print("ℹ️ Valhalla not available, using pgRouting")
                
        except ImportError:
            print("ℹ️ Valhalla module not available, using pgRouting")
        except Exception as e:
            print(f"⚠️ Valhalla error: {e}. Falling back to pgRouting.")
        
        # Fallback: Compute optimal tour using pgRouting
        result = db_manager.compute_optimal_tour(geometries, feature_names)

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to compute optimal tour")
            )

        # Calculate execution time
        execution_time_ms = (time.time() - start_time) * 1000

        # Build response
        response = {
            "success": True,
            "geometry": result.get("geometry"),
            "total_distance_m": result.get("total_distance_m", 0),
            "total_time_minutes": result.get("total_time_minutes"),
            "waypoints": result.get("waypoints", []),
            "directions": result.get("directions", []),
            "optimal_sequence": result.get("optimal_sequence", []),
            "layer_name": result.get("layer_name"),
            "routing_engine": "pgrouting",
            "metadata": result.get("metadata", {}),
            "execution_time_ms": round(execution_time_ms, 2)
        }

        return response

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
    Check if pgRouting topology is available and ready.

    Returns routing infrastructure status.
    """
    try:
        # Test by finding a vertex
        test_vertex = db_manager.find_nearest_vertex_to_point(13.405, 52.52)

        if test_vertex:
            return {
                "status": "healthy",
                "pgRouting": "available",
                "topology": "routing.ways and routing.ways_vertices_pgr",
                "test_vertex": test_vertex["vertex_id"],
                "message": "pgRouting infrastructure is ready"
            }
        else:
            return {
                "status": "unhealthy",
                "pgRouting": "unavailable",
                "error": "Could not find vertices in routing topology"
            }

    except Exception as e:
        return {
            "status": "unhealthy",
            "pgRouting": "error",
            "error": str(e)
        }
