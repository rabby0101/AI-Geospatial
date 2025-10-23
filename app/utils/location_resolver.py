"""
Location Resolver - Dynamically resolve location names to geometries and bounding boxes.
Replaces hardcoded district bounding boxes with real database queries.
"""

import logging
from typing import Dict, Optional, Tuple, Any
from app.utils.database import db_manager

logger = logging.getLogger(__name__)


class LocationResolver:
    """Resolves location names (districts, landmarks) to geometries and bounding boxes."""

    def __init__(self):
        self.db = db_manager

    def resolve_location(self, location_name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a location name to its geometry and bounding box using the unified landmarks table.

        Args:
            location_name: Name of location (district, subdivision, park, station, hospital, etc.)
                          e.g., "Mitte", "Kladow", "Alexanderplatz", "Tiergarten"

        Returns:
            Dict with:
                - name: resolved name
                - type: 'bezirk' | 'ortsteil' | 'park' | 'hospital' | 'train_station' | 'transit_stop'
                - parent_bezirk: parent district (if applicable)
                - geometry: WKT geometry
                - bbox: [min_lon, min_lat, max_lon, max_lat]
            Or None if not found
        """
        # Use centralized landmarks table for unified location lookup
        result = self._resolve_from_landmarks(location_name)
        if result:
            return result

        logger.warning(f"Location not found: {location_name}")
        return None

    def _resolve_from_landmarks(self, location_name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve location from the unified landmarks table.
        Supports exact and fuzzy matching.

        Args:
            location_name: Location name to search for

        Returns:
            Location dict with type, geometry, bbox, or None
        """
        try:
            from sqlalchemy import text

            # First try exact match (case-insensitive)
            sql_exact = """
                SELECT name, type, parent_bezirk,
                       ST_AsText(geometry) as geom_wkt,
                       ST_AsText(ST_Envelope(geometry)) as bbox_wkt
                FROM vector.landmarks
                WHERE LOWER(name) = LOWER(:name)
                LIMIT 1
            """

            with self.db.engine.connect() as conn:
                result = conn.execute(text(sql_exact), {"name": location_name}).fetchone()

                if result:
                    name, location_type, parent_bezirk, geom_wkt, bbox_wkt = result
                    bbox = self._extract_bbox_from_wkt(bbox_wkt) if bbox_wkt else None

                    return {
                        "name": name,
                        "type": location_type,
                        "parent_bezirk": parent_bezirk,
                        "geometry": geom_wkt,
                        "bbox": bbox,
                        "match_type": "exact",
                    }

                # Try fuzzy match (ILIKE substring)
                sql_fuzzy = """
                    SELECT name, type, parent_bezirk,
                           ST_AsText(geometry) as geom_wkt,
                           ST_AsText(ST_Envelope(geometry)) as bbox_wkt
                    FROM vector.landmarks
                    WHERE name ILIKE :pattern
                    LIMIT 1
                """

                result = conn.execute(
                    text(sql_fuzzy), {"pattern": f"%{location_name}%"}
                ).fetchone()

                if result:
                    name, location_type, parent_bezirk, geom_wkt, bbox_wkt = result
                    bbox = self._extract_bbox_from_wkt(bbox_wkt) if bbox_wkt else None

                    return {
                        "name": name,
                        "type": location_type,
                        "parent_bezirk": parent_bezirk,
                        "geometry": geom_wkt,
                        "bbox": bbox,
                        "match_type": "fuzzy",
                    }

        except Exception as e:
            logger.error(f"Error resolving location '{location_name}' from landmarks: {e}")

        return None

    def _resolve_district(self, district_name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a Berlin district name using the berlin_districts table.

        Args:
            district_name: District name (e.g., "Mitte", "Spandau")

        Returns:
            Location dict or None
        """
        try:
            # Try exact match first
            sql = """
                SELECT
                    name,
                    bezirk,
                    area_ha,
                    ST_AsText(geometry) as geom_wkt,
                    ST_Bounds(geometry) as bbox
                FROM vector.berlin_districts
                WHERE LOWER(bezirk) = LOWER(%s)
                LIMIT 1;
            """

            result = self.db.execute_scalar_query(sql, (district_name,), fetch_one=True)

            if not result:
                # Try fuzzy match (substring)
                sql = """
                    SELECT
                        name,
                        bezirk,
                        area_ha,
                        ST_AsText(geometry) as geom_wkt,
                        ST_Bounds(geometry) as bbox
                    FROM vector.berlin_districts
                    WHERE LOWER(bezirk) LIKE LOWER(%s)
                    LIMIT 1;
                """
                result = self.db.execute_scalar_query(sql, (f"%{district_name}%",), fetch_one=True)

            if result:
                name, bezirk, area_ha, geom_wkt, bbox_geom = result

                # Extract bbox from geometry
                bbox = self._extract_bbox_from_wkt(bbox_geom) if bbox_geom else None

                return {
                    "name": bezirk or name,
                    "geometry": geom_wkt,
                    "bbox": bbox,
                    "type": "district",
                    "area_ha": area_ha,
                    "fuzzy_match": "LIKE" in sql,
                }

        except Exception as e:
            logger.error(f"Error resolving district '{district_name}': {e}")

        return None

    def _resolve_landmark(self, landmark_name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a landmark (transport stop, park, etc.) using osm tables.

        Args:
            landmark_name: Landmark name (e.g., "Alexanderplatz", "Tiergarten")

        Returns:
            Location dict or None
        """
        try:
            # Search transport stops first (most common landmarks)
            sql = """
                SELECT
                    name,
                    ST_AsText(geometry) as geom_wkt,
                    ST_Bounds(geometry) as bbox
                FROM vector.osm_transport_stops
                WHERE name ILIKE %s
                LIMIT 1;
            """

            result = self.db.execute_scalar_query(sql, (f"%{landmark_name}%",), fetch_one=True)

            if result:
                name, geom_wkt, bbox_geom = result
                bbox = self._extract_bbox_from_wkt(bbox_geom) if bbox_geom else None

                return {
                    "name": name,
                    "geometry": geom_wkt,
                    "bbox": bbox,
                    "type": "transport_stop",
                }

            # Try parks
            sql = """
                SELECT
                    name,
                    ST_AsText(geometry) as geom_wkt,
                    ST_Bounds(geometry) as bbox
                FROM vector.osm_parks
                WHERE name ILIKE %s
                LIMIT 1;
            """

            result = self.db.execute_scalar_query(sql, (f"%{landmark_name}%",), fetch_one=True)

            if result:
                name, geom_wkt, bbox_geom = result
                bbox = self._extract_bbox_from_wkt(bbox_geom) if bbox_geom else None

                return {
                    "name": name,
                    "geometry": geom_wkt,
                    "bbox": bbox,
                    "type": "park",
                }

        except Exception as e:
            logger.error(f"Error resolving landmark '{landmark_name}': {e}")

        return None

    def get_bbox_for_location(self, location_name: str) -> Optional[Tuple[float, float, float, float]]:
        """
        Get bounding box for a location (district or landmark).

        Args:
            location_name: Location name

        Returns:
            Tuple of (min_lon, min_lat, max_lon, max_lat) or None
        """
        location = self.resolve_location(location_name)
        if location:
            return location.get("bbox")
        return None

    def get_geometry_for_location(self, location_name: str) -> Optional[str]:
        """
        Get WKT geometry for a location.

        Args:
            location_name: Location name

        Returns:
            WKT geometry string or None
        """
        location = self.resolve_location(location_name)
        if location:
            return location.get("geometry")
        return None

    def _extract_bbox_from_wkt(self, bbox_wkt: str) -> Optional[Tuple[float, float, float, float]]:
        """
        Extract bounding box coordinates from WKT POLYGON.

        Args:
            bbox_wkt: WKT representation of bounding box (e.g., "POLYGON((13.1 52.1, 13.1 52.5, ...))")

        Returns:
            Tuple of (min_lon, min_lat, max_lon, max_lat) or None
        """
        try:
            if not bbox_wkt:
                return None

            # Extract coordinates from WKT POLYGON
            # Format: POLYGON((lon1 lat1, lon2 lat2, ...))
            coords_str = bbox_wkt.split("((")[1].split("))")[0]
            coords = []
            for point in coords_str.split(","):
                lon, lat = map(float, point.strip().split())
                coords.append((lon, lat))

            if coords:
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                return (min(lons), min(lats), max(lons), max(lats))

        except Exception as e:
            logger.warning(f"Could not extract bbox from WKT: {e}")

        return None


# Global instance
_resolver = None


def get_location_resolver() -> LocationResolver:
    """Get singleton instance of LocationResolver."""
    global _resolver
    if _resolver is None:
        _resolver = LocationResolver()
    return _resolver


def resolve_location(location_name: str) -> Optional[Dict[str, Any]]:
    """Convenience function to resolve a location."""
    return get_location_resolver().resolve_location(location_name)


def get_bbox_for_location(location_name: str) -> Optional[Tuple[float, float, float, float]]:
    """Convenience function to get bbox for a location."""
    return get_location_resolver().get_bbox_for_location(location_name)
