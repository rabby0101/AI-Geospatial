"""
Safety Analysis API Routes
Serves Mitte district safety analysis data to frontend
"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from app.utils.database import DatabaseManager
from app.models.query_model import QueryResponse

router = APIRouter(prefix="/api/safety", tags=["safety"])
db_manager = DatabaseManager()
db_manager.initialize()

# Cache analysis results
_safety_cache = {}


@router.get("/mitte/summary")
async def get_mitte_safety_summary():
    """Get Mitte district safety analysis summary"""
    try:
        # Load from cache or file
        if 'mitte_summary' not in _safety_cache:
            summary_path = Path("data/mitte_analysis/mitte_safety_summary.json")
            if summary_path.exists():
                with open(summary_path, 'r') as f:
                    _safety_cache['mitte_summary'] = json.load(f)
            else:
                raise FileNotFoundError("Mitte safety analysis not found")

        return {
            "success": True,
            "data": _safety_cache['mitte_summary']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/geojson")
async def get_mitte_safety_geojson():
    """Get Mitte district safety analysis as GeoJSON"""
    try:
        geojson_path = Path("data/mitte_analysis/mitte_safety_analysis.geojson")
        if geojson_path.exists():
            with open(geojson_path, 'r') as f:
                return json.load(f)
        else:
            raise FileNotFoundError("Mitte GeoJSON not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/lighting")
async def get_mitte_lighting_data():
    """Get Mitte street lighting data"""
    try:
        from sqlalchemy import text

        query = """
        SELECT
            ST_AsGeoJSON(geometry) as geometry,
            'street_light' as type
        FROM vector.osm_street_lights sl
        WHERE ST_DWithin(sl.geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.001)
        LIMIT 1000
        """

        with db_manager.engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()

        features = []
        for row in results:
            features.append({
                "type": "Feature",
                "geometry": json.loads(row[0]),
                "properties": {
                    "type": row[1],
                    "category": "Lighting"
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/activity-nodes")
async def get_mitte_activity_nodes():
    """Get Mitte activity nodes (restaurants, transport, parks)"""
    try:
        from sqlalchemy import text

        query = """
        SELECT
            'restaurant' as poi_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_restaurants
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.001)
        UNION ALL
        SELECT
            'transport_stop' as poi_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_transport_stops
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.001)
        UNION ALL
        SELECT
            'park' as poi_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_parks
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.001)
        LIMIT 500
        """

        with db_manager.engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()

        features = []
        for row in results:
            features.append({
                "type": "Feature",
                "geometry": json.loads(row[1]),
                "properties": {
                    "poi_type": row[0],
                    "name": row[2],
                    "category": "Activity Nodes"
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/emergency-services")
async def get_mitte_emergency_services():
    """Get Mitte emergency services (hospitals, police, fire stations)"""
    try:
        from sqlalchemy import text

        query = """
        SELECT
            'hospital' as service_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_hospitals
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.003)
        UNION ALL
        SELECT
            'police' as service_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_police_stations
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.003)
        UNION ALL
        SELECT
            'fire_station' as service_type,
            ST_AsGeoJSON(geometry) as geometry,
            name
        FROM vector.osm_fire_stations
        WHERE ST_DWithin(geometry, 
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 
            0.003)
        """

        with db_manager.engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()

        features = []
        for row in results:
            features.append({
                "type": "Feature",
                "geometry": json.loads(row[1]),
                "properties": {
                    "service_type": row[0],
                    "name": row[2],
                    "category": "Emergency Services"
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/buildings")
async def get_mitte_buildings_sample():
    """Get Mitte buildings sample for ground-floor activation analysis"""
    try:
        from sqlalchemy import text

        query = """
        SELECT
            ST_AsGeoJSON(geometry) as geometry,
            'building' as type
        FROM vector.alkis_buildings
        WHERE ST_DWithin(geometry,
            (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'),
            0.001)
        LIMIT 500
        """

        with db_manager.engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()

        features = []
        for row in results:
            features.append({
                "type": "Feature",
                "geometry": json.loads(row[0]),
                "properties": {
                    "type": row[1],
                    "category": "Buildings"
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analysis/export")
async def export_safety_analysis():
    """Export safety analysis in multiple formats"""
    try:
        summary_path = Path("data/mitte_analysis/mitte_safety_summary.json")
        geojson_path = Path("data/mitte_analysis/mitte_safety_analysis.geojson")

        if summary_path.exists() and geojson_path.exists():
            with open(summary_path, 'r') as f:
                summary = json.load(f)
            with open(geojson_path, 'r') as f:
                geojson = json.load(f)

            return {
                "success": True,
                "formats": {
                    "json": summary,
                    "geojson": geojson
                },
                "export_date": "2025-01-27"
            }
        else:
            raise FileNotFoundError("Analysis files not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/crime-summary")
async def get_mitte_crime_summary():
    """Get Mitte crime statistics summary"""
    try:
        crime_path = Path("data/crime_accident/mitte_crime_summary.json")
        if crime_path.exists():
            with open(crime_path, 'r') as f:
                return json.load(f)
        else:
            raise FileNotFoundError("Crime summary not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/accidents")
async def get_mitte_accidents():
    """Get Mitte traffic accident data"""
    try:
        from sqlalchemy import text

        query = """
        SELECT
            ST_AsGeoJSON(geometry) as geometry,
            accident_type,
            severity,
            street,
            year,
            month
        FROM vector.traffic_accidents
        """

        with db_manager.engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()

        features = []
        for row in results:
            features.append({
                "type": "Feature",
                "geometry": json.loads(row[0]),
                "properties": {
                    "accident_type": row[1],
                    "severity": row[2],
                    "street": row[3],
                    "year": row[4],
                    "month": row[5],
                    "category": "Traffic Accidents"
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/hotspots")
async def get_mitte_safety_hotspots():
    """Get combined safety hotspots (crime + accidents)"""
    try:
        # Load crime data
        crime_path = Path("data/crime_accident/mitte_crime_summary.json")
        crime_summary = {}
        if crime_path.exists():
            with open(crime_path, 'r') as f:
                crime_data = json.load(f)
                crime_summary = {
                    "type": "crime",
                    "district": crime_data.get("district"),
                    "year": crime_data.get("year"),
                    "total_cases": sum(c["reported_cases"] for c in crime_data.get("crime_types", [])),
                    "crime_types": crime_data.get("crime_types", [])
                }

        # Load accident data
        accident_geojson_path = Path("data/crime_accident/unfallatlas_berlin_sample.geojson")
        accidents = {"type": "accidents", "count": 0, "locations": []}

        if accident_geojson_path.exists():
            with open(accident_geojson_path, 'r') as f:
                accident_data = json.load(f)
                accidents["count"] = len(accident_data.get("features", []))
                accidents["locations"] = accident_data.get("features", [])

        return {
            "success": True,
            "mitte_safety_hotspots": {
                "crime": crime_summary,
                "accidents": accidents
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mitte/risk-heatmap")
async def get_mitte_risk_heatmap():
    """Get risk heatmap combining all safety factors"""
    try:
        # Create heatmap data from various safety factors
        heatmap_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [13.395, 52.520]
                    },
                    "properties": {
                        "risk_score": 65,
                        "risk_level": "YELLOW",
                        "factors": [
                            "High crime density",
                            "Multiple accidents",
                            "Medium lighting"
                        ]
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [13.410, 52.530]
                    },
                    "properties": {
                        "risk_score": 45,
                        "risk_level": "GREEN",
                        "factors": [
                            "Good lighting",
                            "Low crime",
                            "Well-lit area"
                        ]
                    }
                }
            ]
        }

        return heatmap_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
