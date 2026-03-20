"""
Nominatim Geocoder Service for address resolution and location lookup.

Self-hosted OSM geocoder with no external API dependencies.
Supports forward geocoding, reverse geocoding, and autocomplete.
"""

import os
import logging
import httpx
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Nominatim configuration
NOMINATIM_HOST = os.getenv("NOMINATIM_HOST", "localhost")
NOMINATIM_PORT = os.getenv("NOMINATIM_PORT", "7070")
NOMINATIM_BASE_URL = f"http://{NOMINATIM_HOST}:{NOMINATIM_PORT}"

# Berlin viewbox: min_lon, max_lat, max_lon, min_lat (Nominatim format: left,top,right,bottom)
BERLIN_VIEWBOX = "12.9,52.8,13.9,52.3"


@dataclass
class GeocodeResult:
    """Result of a forward geocoding request."""
    place_id: int
    display_name: str
    name: str  # First token of display_name
    lat: float
    lon: float
    bbox: List[float]  # [min_lon, min_lat, max_lon, max_lat]
    type: str
    osm_type: str
    importance: float
    address: Dict[str, str] = field(default_factory=dict)


@dataclass
class ReverseGeocodeResult:
    """Result of a reverse geocoding request."""
    place_id: int
    display_name: str
    lat: float
    lon: float
    address: Dict[str, str] = field(default_factory=dict)
    osm_type: str = ""
    type: str = ""


class GeocoderService:
    """
    Service for geocoding operations using self-hosted Nominatim.

    Supports:
    - Forward geocoding (address/place name → coordinates)
    - Autocomplete (partial query → suggestions)
    - Reverse geocoding (coordinates → address)
    - Health check
    """

    def __init__(self, base_url: str = NOMINATIM_BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=10.0)

    def search(self, query: str, limit: int = 5) -> List[GeocodeResult]:
        """
        Forward geocoding: resolve a query string to coordinates.

        Uses Berlin viewbox bias; bounded=1 restricts results to Berlin area.

        Args:
            query: Address or place name to geocode
            limit: Maximum number of results to return

        Returns:
            List of GeocodeResult, empty list if unavailable or no results
        """
        try:
            params = {
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": limit,
                "bounded": 1,
                "viewbox": BERLIN_VIEWBOX,
            }
            response = self.client.get(f"{self.base_url}/search", params=params)
            if response.status_code != 200:
                logger.warning(f"Nominatim search error: {response.status_code}")
                return []

            return self._parse_search_results(response.json())

        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"Nominatim unavailable at {self.base_url}")
            return []
        except Exception as e:
            logger.error(f"Nominatim search error: {e}")
            return []

    def autocomplete(self, partial: str, limit: int = 7) -> List[GeocodeResult]:
        """
        Typeahead autocomplete: returns suggestions for a partial query.

        Tries bounded Berlin search first; retries globally if empty.

        Args:
            partial: Partial query string
            limit: Maximum number of suggestions

        Returns:
            List of GeocodeResult suggestions
        """
        try:
            params = {
                "q": partial,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": limit,
                "bounded": 1,
                "viewbox": BERLIN_VIEWBOX,
            }
            response = self.client.get(f"{self.base_url}/search", params=params)
            if response.status_code != 200:
                return []

            results = self._parse_search_results(response.json())

            # Retry without bounding box if bounded search returned nothing
            if not results:
                params["bounded"] = 0
                response = self.client.get(f"{self.base_url}/search", params=params)
                if response.status_code == 200:
                    results = self._parse_search_results(response.json())

            return results

        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"Nominatim unavailable at {self.base_url}")
            return []
        except Exception as e:
            logger.error(f"Nominatim autocomplete error: {e}")
            return []

    def reverse(self, lat: float, lon: float, zoom: int = 18) -> Optional[ReverseGeocodeResult]:
        """
        Reverse geocoding: convert coordinates to an address.

        Args:
            lat: Latitude
            lon: Longitude
            zoom: Detail level (18 = building, 16 = street, 10 = city)

        Returns:
            ReverseGeocodeResult or None if unavailable
        """
        try:
            params = {
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": zoom,
            }
            response = self.client.get(f"{self.base_url}/reverse", params=params)
            if response.status_code != 200:
                logger.warning(f"Nominatim reverse error: {response.status_code}")
                return None

            data = response.json()
            if "error" in data:
                return None

            return ReverseGeocodeResult(
                place_id=data.get("place_id", 0),
                display_name=data.get("display_name", ""),
                lat=float(data.get("lat", lat)),
                lon=float(data.get("lon", lon)),
                address=data.get("address", {}),
                osm_type=data.get("osm_type", ""),
                type=data.get("type", ""),
            )

        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"Nominatim unavailable at {self.base_url}")
            return None
        except Exception as e:
            logger.error(f"Nominatim reverse error: {e}")
            return None

    def check_health(self) -> Dict[str, Any]:
        """Check if Nominatim service is healthy and ready."""
        try:
            response = self.client.get(f"{self.base_url}/status", params={"format": "json"})
            if response.status_code == 200:
                data = response.json()
                # Nominatim /status returns {"status": 0, "message": "OK", ...} when healthy
                if data.get("status") == 0:
                    return {
                        "status": "healthy",
                        "nominatim": "available",
                        "url": self.base_url,
                        "details": data,
                    }
                else:
                    return {
                        "status": "starting",
                        "nominatim": "initializing",
                        "url": self.base_url,
                        "details": data,
                    }
            else:
                return {
                    "status": "unhealthy",
                    "error": f"Status code: {response.status_code}",
                    "url": self.base_url,
                }
        except httpx.ConnectError:
            return {
                "status": "unavailable",
                "error": f"Cannot connect to Nominatim at {self.base_url}",
                "url": self.base_url,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "url": self.base_url,
            }

    def _parse_search_results(self, data: list) -> List[GeocodeResult]:
        """Parse raw Nominatim JSON search results into GeocodeResult objects."""
        results = []
        for item in data:
            try:
                # Nominatim bbox: [min_lat, max_lat, min_lon, max_lon] → reorder to [min_lon, min_lat, max_lon, max_lat]
                raw_bbox = item.get("boundingbox", [])
                if len(raw_bbox) == 4:
                    bbox = [
                        float(raw_bbox[2]),  # min_lon
                        float(raw_bbox[0]),  # min_lat
                        float(raw_bbox[3]),  # max_lon
                        float(raw_bbox[1]),  # max_lat
                    ]
                else:
                    lon = float(item.get("lon", 0))
                    lat = float(item.get("lat", 0))
                    bbox = [lon, lat, lon, lat]

                display_name = item.get("display_name", "")
                name = display_name.split(",")[0].strip() if display_name else ""

                results.append(GeocodeResult(
                    place_id=item.get("place_id", 0),
                    display_name=display_name,
                    name=name,
                    lat=float(item.get("lat", 0)),
                    lon=float(item.get("lon", 0)),
                    bbox=bbox,
                    type=item.get("type", ""),
                    osm_type=item.get("osm_type", ""),
                    importance=float(item.get("importance", 0)),
                    address=item.get("address", {}),
                ))
            except Exception as e:
                logger.warning(f"Could not parse geocode result: {e}")

        return results


# Singleton instance for the application
geocoder_service = GeocoderService()
