"""
Geocoding API endpoints for address resolution and location lookup.

Provides forward geocoding, autocomplete, and reverse geocoding
via self-hosted Nominatim (no external API calls).
"""

import logging
from fastapi import APIRouter, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/geocode", tags=["geocoding"])


# ── Pydantic response models ──────────────────────────────────────────────────

class GeocodeResultModel(BaseModel):
    place_id: int
    display_name: str
    name: str
    lat: float
    lon: float
    bbox: List[float]  # [min_lon, min_lat, max_lon, max_lat]
    type: str
    osm_type: str
    importance: float
    address: Dict[str, str] = {}


class GeocodeSearchResponse(BaseModel):
    success: bool
    query: str
    results: List[GeocodeResultModel]
    count: int
    source: str = "nominatim"


class ReverseGeocodeResponse(BaseModel):
    success: bool
    lat: float
    lon: float
    display_name: Optional[str] = None
    address: Dict[str, str] = {}
    osm_type: str = ""
    type: str = ""
    source: str = "nominatim"


class GeocoderHealthResponse(BaseModel):
    status: str  # "healthy" | "starting" | "unavailable" | "error"
    nominatim: Optional[str] = None
    url: str
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/search", response_model=GeocodeSearchResponse)
async def geocode_search(
    q: str = Query(..., description="Address or place name to geocode"),
    limit: int = Query(5, ge=1, le=20, description="Maximum results to return"),
) -> GeocodeSearchResponse:
    """
    Forward geocoding: resolve an address or place name to coordinates.

    Biased to Berlin; falls back gracefully if Nominatim is unavailable.
    """
    from app.utils.geocoder import geocoder_service

    results = geocoder_service.search(q, limit=limit)
    return GeocodeSearchResponse(
        success=True,
        query=q,
        results=[
            GeocodeResultModel(
                place_id=r.place_id,
                display_name=r.display_name,
                name=r.name,
                lat=r.lat,
                lon=r.lon,
                bbox=r.bbox,
                type=r.type,
                osm_type=r.osm_type,
                importance=r.importance,
                address=r.address,
            )
            for r in results
        ],
        count=len(results),
    )


@router.get("/autocomplete", response_model=GeocodeSearchResponse)
async def geocode_autocomplete(
    q: str = Query(..., description="Partial query string for typeahead"),
    limit: int = Query(7, ge=1, le=20, description="Maximum suggestions to return"),
) -> GeocodeSearchResponse:
    """
    Typeahead autocomplete: return ranked suggestions for a partial query.

    Tries Berlin-bounded search first; retries globally if empty.
    """
    from app.utils.geocoder import geocoder_service

    results = geocoder_service.autocomplete(q, limit=limit)
    return GeocodeSearchResponse(
        success=True,
        query=q,
        results=[
            GeocodeResultModel(
                place_id=r.place_id,
                display_name=r.display_name,
                name=r.name,
                lat=r.lat,
                lon=r.lon,
                bbox=r.bbox,
                type=r.type,
                osm_type=r.osm_type,
                importance=r.importance,
                address=r.address,
            )
            for r in results
        ],
        count=len(results),
    )


@router.get("/reverse", response_model=ReverseGeocodeResponse)
async def geocode_reverse(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    zoom: int = Query(18, ge=0, le=18, description="Detail level (18=building, 16=street, 10=city)"),
) -> ReverseGeocodeResponse:
    """
    Reverse geocoding: convert coordinates to a human-readable address.
    """
    from app.utils.geocoder import geocoder_service

    result = geocoder_service.reverse(lat, lon, zoom=zoom)
    if result:
        return ReverseGeocodeResponse(
            success=True,
            lat=result.lat,
            lon=result.lon,
            display_name=result.display_name,
            address=result.address,
            osm_type=result.osm_type,
            type=result.type,
        )
    return ReverseGeocodeResponse(
        success=False,
        lat=lat,
        lon=lon,
        display_name=None,
    )


class GeocodedFeatureResponse(BaseModel):
    success: bool
    query: str
    display_name: Optional[str] = None
    name: Optional[str] = None
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]
    source: str                         # "building_polygon" | "nominatim_point"
    feature: Dict[str, Any]             # GeoJSON Feature object


def _envelope_wkt_to_bbox(wkt: Optional[str]) -> Optional[List[float]]:
    if not wkt:
        return None
    try:
        coords_str = wkt.split("((")[1].split("))")[0]
        coords = [tuple(map(float, p.strip().split())) for p in coords_str.split(",")]
        lons, lats = [c[0] for c in coords], [c[1] for c in coords]
        return [min(lons), min(lats), max(lons), max(lats)]
    except Exception:
        return None


@router.get("/feature", response_model=GeocodedFeatureResponse)
async def geocode_feature(q: str = Query(...)) -> GeocodedFeatureResponse:
    """
    Geocode an address and return the building polygon (if found) or a point fallback.

    Uses Nominatim to resolve the address, then performs a ST_Contains lookup on
    vector.alkis_buildings to return the actual building footprint when available.
    """
    from app.utils.geocoder import geocoder_service
    from app.utils.database import db_manager
    from sqlalchemy import text

    # Step 1: Nominatim geocode
    results = geocoder_service.search(q, limit=1)
    if not results:
        return GeocodedFeatureResponse(success=False, query=q, source="nominatim_point", feature={})

    loc = results[0]

    # Step 2a: Exact point-in-polygon
    sql_contains = text("""
        SELECT ST_AsGeoJSON(geometry)::json, ST_AsText(ST_Envelope(geometry)), bezgfk, nam
        FROM vector.alkis_buildings
        WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        LIMIT 1
    """)
    # Step 2b: Nearest building within 50 m (street-addressed buildings)
    sql_nearest = text("""
        SELECT ST_AsGeoJSON(geometry)::json, ST_AsText(ST_Envelope(geometry)), bezgfk, nam
        FROM vector.alkis_buildings
        WHERE ST_DWithin(
            geometry::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            50
        )
        ORDER BY ST_Distance(
            geometry::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
        )
        LIMIT 1
    """)
    building = None
    try:
        with db_manager.engine.connect() as conn:
            params = {"lon": loc.lon, "lat": loc.lat}
            building = conn.execute(sql_contains, params).fetchone()
            if building is None:
                building = conn.execute(sql_nearest, params).fetchone()
    except Exception as e:
        logger.warning(f"Building lookup failed: {e}")

    # Step 3: Return building polygon if found
    if building and building[0] is not None:
        geom_json, env_wkt, bezgfk, nam = building
        bbox = _envelope_wkt_to_bbox(env_wkt) or loc.bbox
        return GeocodedFeatureResponse(
            success=True, query=q,
            display_name=loc.display_name,
            name=nam or loc.name or q,
            bbox=bbox, source="building_polygon",
            feature={
                "type": "Feature", "geometry": geom_json,
                "properties": {
                    "name": nam or loc.name or q,
                    "display_name": loc.display_name,
                    "building_type": bezgfk,
                    "source": "building_polygon",
                }
            }
        )

    # Step 4: Fallback — Nominatim point
    addr = {f"addr_{k}": v for k, v in (loc.address or {}).items()}
    return GeocodedFeatureResponse(
        success=True, query=q,
        display_name=loc.display_name,
        name=loc.name or q,
        bbox=loc.bbox, source="nominatim_point",
        feature={
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [loc.lon, loc.lat]},
            "properties": {"name": loc.name or q, "display_name": loc.display_name,
                           "type": loc.type or "place", "source": "nominatim_point", **addr}
        }
    )


@router.get("/health", response_model=GeocoderHealthResponse)
async def geocoder_health() -> GeocoderHealthResponse:
    """
    Check if the Nominatim geocoder service is available and ready.
    """
    from app.utils.geocoder import geocoder_service

    health = geocoder_service.check_health()
    return GeocoderHealthResponse(
        status=health.get("status", "unknown"),
        nominatim=health.get("nominatim"),
        url=health.get("url", ""),
        error=health.get("error"),
        details=health.get("details"),
    )
