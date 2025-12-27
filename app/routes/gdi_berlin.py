"""
GDI Berlin WFS Proxy Router

Provides endpoints to fetch WFS layers from Berlin Geodata Infrastructure
to avoid CORS issues when fetching from the frontend.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import httpx

router = APIRouter(prefix="/api/gdi-berlin", tags=["GDI Berlin"])

# Available GDI Berlin WFS layers with their configurations
# URLs verified from GetCapabilities responses
# No feature limits - all features will be fetched by default
GDI_BERLIN_LAYERS = {
    # === ADMINISTRATIVE BOUNDARIES ===
    "bezirke": {
        "name": "Bezirke (Districts)",
        "description": "Berlin's 12 administrative districts",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_bezirke",
        "typename": "alkis_bezirke:bezirksgrenzen",
        "category": "administrative"
    },
    "ortsteile": {
        "name": "Ortsteile (Neighborhoods)", 
        "description": "Berlin neighborhoods/localities (96 areas)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_ortsteile",
        "typename": "alkis_ortsteile:ortsteile",
        "category": "administrative"
    },
    "landesgrenze": {
        "name": "Landesgrenze (State Border)",
        "description": "Berlin state boundary",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_land",
        "typename": "alkis_land:landesgrenze",
        "category": "administrative"
    },
    
    # === LOR SYSTEM (Lebensweltlich orientierte Räume) ===
    "lor_planungsraeume": {
        "name": "LOR Planungsräume",
        "description": "Berlin planning areas - smallest LOR units (448 areas)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/lor_planungsraeume_2021",
        "typename": "lor_planungsraeume_2021:lor_planungsraeume_2021",
        "category": "lor"
    },
    "lor_bezirksregionen": {
        "name": "LOR Bezirksregionen",
        "description": "Berlin district regions - medium LOR units (138 areas)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/lor_bezirksregionen_2021",
        "typename": "lor_bezirksregionen_2021:lor_bezirksregionen_2021",
        "category": "lor"
    },
    "lor_prognoseraeume": {
        "name": "LOR Prognoseräume",
        "description": "Berlin forecast/prognosis areas - large LOR units (60 areas)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/lor_prognoseraeume_2021",
        "typename": "lor_prognoseraeume_2021:lor_prognoseraeume_2021",
        "category": "lor"
    },
    
    # === BUILDINGS & INFRASTRUCTURE ===
    "gebaeude": {
        "name": "Gebäude (Buildings)",
        "description": "Building footprints from ALKIS cadastre (⚠️ Large dataset)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_gebaeude",
        "typename": "alkis_gebaeude:gebaeude",
        "category": "buildings"
    },
    "gebaeudehoehen": {
        "name": "Gebäudehöhen (Building Heights)",
        "description": "Building heights from 3D city model (⚠️ Large dataset)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/gebaeudehoehen",
        "typename": "gebaeudehoehen:gebaeudehoehen",
        "category": "buildings"
    },
    
    # === LAND & PROPERTY ===
    "flurstuecke": {
        "name": "Flurstücke (Land Parcels)",
        "description": "Cadastral land parcels from ALKIS (⚠️ Large dataset)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_flurstuecke",
        "typename": "alkis_flurstuecke:flurstuecke",
        "category": "land"
    },
    "nutzung": {
        "name": "Tatsächliche Nutzung (Land Use)",
        "description": "Actual land use categories from ALKIS (⚠️ Large dataset)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/alkis_nutzung",
        "typename": "alkis_nutzung:nutzung",
        "category": "land"
    },
    
    # === GREEN SPACES & RECREATION ===
    "gruenflaechen": {
        "name": "Grünflächen (Green Areas)",
        "description": "Public green spaces and parks",
        "wfs_url": "https://gdi.berlin.de/services/wfs/ua_gruenflaechen",
        "typename": "ua_gruenflaechen:gruenflaechen",
        "category": "environment"
    },
    "spielplaetze": {
        "name": "Spielplätze (Playgrounds)",
        "description": "Public playgrounds in Berlin",
        "wfs_url": "https://gdi.berlin.de/services/wfs/spielplaetze",
        "typename": "spielplaetze:spielplaetze",
        "category": "recreation"
    },
    "friedhoefe": {
        "name": "Friedhöfe (Cemeteries)",
        "description": "Cemetery locations and boundaries",
        "wfs_url": "https://gdi.berlin.de/services/wfs/friedhoefe",
        "typename": "friedhoefe:friedhoefe",
        "category": "environment"
    },
    
    # === TRANSPORTATION ===
    "strassennetz": {
        "name": "Straßennetz (Street Network)",
        "description": "Berlin road network (⚠️ Large dataset)",
        "wfs_url": "https://gdi.berlin.de/services/wfs/inspire_tn_strassennetz",
        "typename": "inspire_tn_strassennetz:RoadLink",
        "category": "transport"
    },
    "radverkehrsanlagen": {
        "name": "Radverkehrsanlagen (Cycling Infrastructure)",
        "description": "Bicycle lanes and cycling paths",
        "wfs_url": "https://gdi.berlin.de/services/wfs/radverkehrsanlagen",
        "typename": "radverkehrsanlagen:radverkehrsanlagen",
        "category": "transport"
    },
    "oepnv_haltestellen": {
        "name": "ÖPNV Haltestellen (Public Transport Stops)",
        "description": "Bus, tram, U-Bahn and S-Bahn stops",
        "wfs_url": "https://gdi.berlin.de/services/wfs/oepnv_haltestellen",
        "typename": "oepnv_haltestellen:oepnv_haltestellen",
        "category": "transport"
    },
    
    # === PUBLIC FACILITIES ===
    "schulen": {
        "name": "Schulen (Schools)",
        "description": "School locations in Berlin",
        "wfs_url": "https://gdi.berlin.de/services/wfs/schulen",
        "typename": "schulen:schulen",
        "category": "facilities"
    },
    "krankenhaeuser": {
        "name": "Krankenhäuser (Hospitals)",
        "description": "Hospital and clinic locations",
        "wfs_url": "https://gdi.berlin.de/services/wfs/krankenhaeuser",
        "typename": "krankenhaeuser:krankenhaeuser",
        "category": "facilities"
    }
}


@router.get("/layers")
async def list_available_layers():
    """List all available GDI Berlin layers that can be imported"""
    layers = []
    for layer_id, config in GDI_BERLIN_LAYERS.items():
        layers.append({
            "id": layer_id,
            "name": config["name"],
            "description": config["description"],
            "category": config.get("category", "other")
        })
    return {"success": True, "layers": layers, "total": len(layers)}


@router.get("/wfs/{layer_id}")
async def get_wfs_layer(
    layer_id: str,
    max_features: Optional[int] = Query(None, description="Maximum features to return"),
    bbox: Optional[str] = Query(None, description="Bounding box: minx,miny,maxx,maxy")
):
    """
    Fetch GeoJSON from a GDI Berlin WFS layer.
    
    This endpoint proxies requests to GDI Berlin WFS services to avoid CORS issues.
    """
    if layer_id not in GDI_BERLIN_LAYERS:
        raise HTTPException(
            status_code=404,
            detail=f"Layer '{layer_id}' not found. Available layers: {list(GDI_BERLIN_LAYERS.keys())}"
        )
    
    config = GDI_BERLIN_LAYERS[layer_id]
    
    # Build WFS GetFeature request
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": config["typename"],  # WFS 2.0 uses typeNames (plural)
        "outputFormat": "json",
        "srsName": "EPSG:4326"
    }
    
    # Only add count parameter if user explicitly requests a limit
    if max_features:
        params["count"] = max_features
    
    if bbox:
        params["bbox"] = bbox
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(config["wfs_url"], params=params)
            response.raise_for_status()
            
            geojson = response.json()
            
            # Add layer metadata
            return {
                "success": True,
                "layer_id": layer_id,
                "layer_name": config["name"],
                "feature_count": len(geojson.get("features", [])),
                "geojson": geojson
            }
            
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="WFS request timed out")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"WFS error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching WFS layer: {str(e)}")
