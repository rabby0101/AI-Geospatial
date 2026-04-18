"""
Valhalla Routing Service for multi-mode routing.

This module provides integration with the Valhalla routing engine,
supporting multiple transport modes: pedestrian, bicycle, car (auto),
truck, bus, motor_scooter, and motorcycle.

Features:
- Proper speed calculation per mode
- Network-based isochrones
- Elevation-aware routing (optional)
- Turn-by-turn directions
"""

import os
import json
import logging
import httpx
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Valhalla configuration
VALHALLA_HOST = os.getenv("VALHALLA_HOST", "localhost")
VALHALLA_PORT = os.getenv("VALHALLA_PORT", "8002")
VALHALLA_BASE_URL = f"http://{VALHALLA_HOST}:{VALHALLA_PORT}"

# Walking speed constants (Valhalla uses ~5.1 km/h for pedestrian by default)
WALKING_SPEED_KMH = 5.1
WALKING_SPEED_M_PER_MIN = WALKING_SPEED_KMH * 1000 / 60  # ~85 m/min

# Supported transport modes and their default costing options
SUPPORTED_COSTINGS = {
    "pedestrian", "bicycle", "auto", "truck", "bus",
    "motor_scooter", "motorcycle"
}

DEFAULT_COSTING_OPTIONS = {
    "pedestrian": {
        "walking_speed": WALKING_SPEED_KMH,
        "walkway_factor": 0.9,
        "sidewalk_factor": 0.95,
        "alley_factor": 1.2,
        "driveway_factor": 1.3,
        "step_penalty": 30,
        "use_ferry": 0,
        "use_living_streets": 0.8,
        "use_tracks": 0.5
    },
    "bicycle": {
        "bicycle_type": "Hybrid",
        "cycling_speed": 20.0,
        "use_roads": 0.5,
        "use_hills": 0.5,
        "use_ferry": 0,
        "use_living_streets": 0.8
    },
    "auto": {},
    "truck": {
        "height": 4.11,
        "width": 2.6,
        "length": 21.64,
        "weight": 21.77
    },
    "bus": {
        "height": 4.11,
        "width": 2.6,
        "length": 12.0,
        "weight": 15.0
    },
    "motor_scooter": {
        "top_speed": 45
    },
    "motorcycle": {}
}


@dataclass
class RouteResult:
    """Result of a routing request."""
    success: bool
    geometry: Optional[Dict]  # GeoJSON geometry
    distance_m: float
    duration_seconds: float
    duration_minutes: float
    maneuvers: List[Dict]
    error: Optional[str] = None


@dataclass
class IsochroneResult:
    """Result of an isochrone request."""
    success: bool
    geometry: Optional[Dict]  # GeoJSON polygon
    time_minutes: float
    error: Optional[str] = None


class ValhallaRoutingService:
    """
    Service for routing operations using Valhalla.
    
    Supports multiple transport modes:
    - pedestrian, bicycle, auto, truck, bus, motor_scooter, motorcycle
    - Realistic travel times per mode
    - Native isochrone support
    """
    
    def __init__(self, base_url: str = VALHALLA_BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)
        
    async def __aenter__(self):
        self.async_client = httpx.AsyncClient(timeout=30.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.async_client.aclose()

    def _build_locations(self, points: List[Tuple[float, float]]) -> List[Dict]:
        """Convert (lat, lon) tuples to Valhalla location format."""
        return [{"lat": lat, "lon": lon} for lat, lon in points]

    def get_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        costing: str = "pedestrian",
        include_maneuvers: bool = True
    ) -> RouteResult:
        """
        Get route between two points using the specified transport mode.
        
        Args:
            origin_lat, origin_lon: Origin coordinates
            dest_lat, dest_lon: Destination coordinates
            costing: Valhalla costing model – one of: pedestrian, bicycle,
                     auto, truck, bus, motor_scooter, motorcycle
            include_maneuvers: Include turn-by-turn directions
            
        Returns:
            RouteResult with geometry, distance, duration, and directions
        """
        if costing not in SUPPORTED_COSTINGS:
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error=f"Unsupported costing: {costing}. Supported: {SUPPORTED_COSTINGS}"
            )

        try:
            costing_opts = DEFAULT_COSTING_OPTIONS.get(costing, {})
            request_body = {
                "locations": [
                    {"lat": origin_lat, "lon": origin_lon},
                    {"lat": dest_lat, "lon": dest_lon}
                ],
                "costing": costing,
                "costing_options": {costing: costing_opts} if costing_opts else {},
                "units": "meters",
                "directions_options": {"units": "meters"}
            }
            
            response = self.client.post(
                f"{self.base_url}/route",
                json=request_body
            )
            
            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"Valhalla {costing} route error: {error_msg}")
                return RouteResult(
                    success=False, geometry=None, distance_m=0,
                    duration_seconds=0, duration_minutes=0, maneuvers=[],
                    error=f"Valhalla error: {error_msg}"
                )
            
            data = response.json()
            trip = data.get("trip", {})
            legs = trip.get("legs", [{}])
            leg = legs[0] if legs else {}
            summary = leg.get("summary", {})
            
            shape = trip.get("legs", [{}])[0].get("shape", "")
            geometry = self._decode_polyline_to_geojson(shape) if shape else None
            
            distance_m = summary.get("length", 0) * 1000
            duration_seconds = summary.get("time", 0)
            duration_minutes = duration_seconds / 60
            
            maneuvers = []
            if include_maneuvers:
                for maneuver in leg.get("maneuvers", []):
                    maneuvers.append({
                        "instruction": maneuver.get("instruction", ""),
                        "street_name": ", ".join(maneuver.get("street_names", [])),
                        "distance_m": maneuver.get("length", 0) * 1000,
                        "time_seconds": maneuver.get("time", 0),
                        "type": maneuver.get("type", 0),
                        "begin_shape_index": maneuver.get("begin_shape_index", 0),
                        "end_shape_index": maneuver.get("end_shape_index", 0)
                    })
            
            logger.info(f"✅ Valhalla {costing} route: {distance_m:.0f}m, {duration_minutes:.1f} min")
            
            return RouteResult(
                success=True,
                geometry=geometry,
                distance_m=distance_m,
                duration_seconds=duration_seconds,
                duration_minutes=duration_minutes,
                maneuvers=maneuvers
            )
            
        except httpx.ConnectError:
            error_msg = f"Cannot connect to Valhalla at {self.base_url}. Is Valhalla running?"
            logger.error(error_msg)
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error=error_msg
            )
        except Exception as e:
            logger.error(f"Valhalla {costing} routing error: {e}")
            import traceback
            traceback.print_exc()
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error=str(e)
            )

    def get_pedestrian_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        include_maneuvers: bool = True
    ) -> RouteResult:
        """Convenience wrapper: pedestrian route between two points."""
        return self.get_route(
            origin_lat, origin_lon, dest_lat, dest_lon,
            costing="pedestrian", include_maneuvers=include_maneuvers
        )

    def get_isochrone(
        self,
        lat: float,
        lon: float,
        time_minutes: float,
        costing: str = "pedestrian",
        denoise: float = 0.5,
        generalize: float = 50
    ) -> IsochroneResult:
        """
        Get isochrone polygon for a given time limit and transport mode.

        Args:
            lat, lon: Center point coordinates
            time_minutes: Maximum travel time in minutes
            costing: Valhalla costing model (pedestrian, bicycle, auto, etc.)
            denoise: Smoothing factor (0-1, higher = more smooth)
            generalize: Simplification threshold in meters

        Returns:
            IsochroneResult with polygon geometry
        """
        if costing not in SUPPORTED_COSTINGS:
            return IsochroneResult(
                success=False,
                geometry=None,
                time_minutes=time_minutes,
                error=f"Unsupported costing: {costing}. Supported: {SUPPORTED_COSTINGS}"
            )
        try:
            costing_opts = DEFAULT_COSTING_OPTIONS.get(costing, {})
            request_body = {
                "locations": [{"lat": lat, "lon": lon}],
                "costing": costing,
                "costing_options": {costing: costing_opts} if costing_opts else {},
                "contours": [{"time": time_minutes}],
                "denoise": denoise,
                "generalize": generalize,
                "polygons": True,
                "show_locations": False
            }

            response = self.client.post(
                f"{self.base_url}/isochrone",
                json=request_body
            )

            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"Valhalla isochrone error: {error_msg}")
                return IsochroneResult(
                    success=False,
                    geometry=None,
                    time_minutes=time_minutes,
                    error=f"Valhalla error: {error_msg}"
                )

            data = response.json()
            features = data.get("features", [])
            if features:
                geometry = features[0].get("geometry")
                logger.info(f"✅ Valhalla isochrone: {time_minutes} min {costing} area generated")
                return IsochroneResult(
                    success=True,
                    geometry=geometry,
                    time_minutes=time_minutes
                )
            else:
                return IsochroneResult(
                    success=False,
                    geometry=None,
                    time_minutes=time_minutes,
                    error="No isochrone generated"
                )

        except httpx.ConnectError:
            error_msg = f"Cannot connect to Valhalla at {self.base_url}. Is Valhalla running?"
            logger.error(error_msg)
            return IsochroneResult(
                success=False,
                geometry=None,
                time_minutes=time_minutes,
                error=error_msg
            )
        except Exception as e:
            logger.error(f"Valhalla isochrone error: {e}")
            import traceback
            traceback.print_exc()
            return IsochroneResult(
                success=False,
                geometry=None,
                time_minutes=time_minutes,
                error=str(e)
            )

    def get_walking_isochrone(
        self,
        lat: float,
        lon: float,
        time_minutes: float,
        denoise: float = 0.5,
        generalize: float = 50
    ) -> IsochroneResult:
        """Convenience wrapper: pedestrian isochrone. Use get_isochrone for other modes."""
        return self.get_isochrone(lat, lon, time_minutes, costing="pedestrian",
                                  denoise=denoise, generalize=generalize)

    def get_multi_point_route(
        self,
        points: List[Tuple[float, float]],
        costing: str = "pedestrian"
    ) -> RouteResult:
        """
        Get route through multiple waypoints using the specified mode.
        
        Args:
            points: List of (lat, lon) tuples representing waypoints
            costing: Valhalla costing model
            
        Returns:
            RouteResult with combined geometry
        """
        if len(points) < 2:
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error="At least 2 points required"
            )

        if costing not in SUPPORTED_COSTINGS:
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error=f"Unsupported costing: {costing}"
            )

        try:
            costing_opts = DEFAULT_COSTING_OPTIONS.get(costing, {})
            request_body = {
                "locations": self._build_locations(points),
                "costing": costing,
                "costing_options": {costing: costing_opts} if costing_opts else {},
                "units": "meters"
            }
            
            response = self.client.post(
                f"{self.base_url}/route",
                json=request_body
            )
            
            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"Valhalla {costing} multi-route error: {error_msg}")
                return RouteResult(
                    success=False, geometry=None, distance_m=0,
                    duration_seconds=0, duration_minutes=0, maneuvers=[],
                    error=f"Valhalla error: {error_msg}"
                )
            
            data = response.json()
            trip = data.get("trip", {})
            
            total_distance = 0
            total_time = 0
            all_maneuvers = []
            all_coordinates = []
            
            for leg in trip.get("legs", []):
                summary = leg.get("summary", {})
                total_distance += summary.get("length", 0) * 1000
                total_time += summary.get("time", 0)
                
                shape = leg.get("shape", "")
                if shape:
                    coords = self._decode_polyline(shape)
                    all_coordinates.extend(coords)
                    
                for m in leg.get("maneuvers", []):
                    all_maneuvers.append({
                        "instruction": m.get("instruction", ""),
                        "street_name": ", ".join(m.get("street_names", [])),
                        "distance_m": m.get("length", 0) * 1000,
                        "time_seconds": m.get("time", 0)
                    })
            
            geometry = {
                "type": "LineString",
                "coordinates": all_coordinates
            } if all_coordinates else None
            
            return RouteResult(
                success=True,
                geometry=geometry,
                distance_m=total_distance,
                duration_seconds=total_time,
                duration_minutes=total_time / 60,
                maneuvers=all_maneuvers
            )
            
        except Exception as e:
            logger.error(f"Valhalla {costing} multi-route error: {e}")
            return RouteResult(
                success=False, geometry=None, distance_m=0,
                duration_seconds=0, duration_minutes=0, maneuvers=[],
                error=str(e)
            )

    def _decode_polyline(self, encoded: str, precision: int = 6) -> List[List[float]]:
        """
        Decode Valhalla's encoded polyline to coordinate list.
        
        Valhalla uses precision 6 (Google uses 5).
        """
        inv = 1.0 / (10 ** precision)
        decoded = []
        previous = [0, 0]
        i = 0
        
        while i < len(encoded):
            ll = [0, 0]
            for j in range(2):
                shift = 0
                byte = 0x20
                
                while byte >= 0x20:
                    byte = ord(encoded[i]) - 63
                    i += 1
                    ll[j] |= (byte & 0x1f) << shift
                    shift += 5
                    
                ll[j] = previous[j] + (~(ll[j] >> 1) if ll[j] & 1 else (ll[j] >> 1))
                previous[j] = ll[j]
                
            decoded.append([ll[1] * inv, ll[0] * inv])  # [lon, lat] for GeoJSON
            
        return decoded

    def _decode_polyline_to_geojson(self, encoded: str) -> Dict:
        """Decode polyline and return as GeoJSON LineString."""
        coordinates = self._decode_polyline(encoded)
        return {
            "type": "LineString",
            "coordinates": coordinates
        }

    def check_health(self) -> Dict[str, Any]:
        """Check if Valhalla service is healthy and ready."""
        try:
            response = self.client.get(f"{self.base_url}/status")
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "valhalla": "available",
                    "url": self.base_url
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": f"Status code: {response.status_code}",
                    "url": self.base_url
                }
        except httpx.ConnectError:
            return {
                "status": "unavailable",
                "error": f"Cannot connect to Valhalla at {self.base_url}",
                "url": self.base_url
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "url": self.base_url
            }


# Singleton instance for the application
valhalla_service = ValhallaRoutingService()
