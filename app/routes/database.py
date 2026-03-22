"""
Database schema and metadata management endpoints
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session
import os
import json
import tempfile
import shutil
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

router = APIRouter(prefix="/api/database", tags=["database"])

# Database connection helper
def get_db_engine():
    """Get database engine"""
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')

    connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    return create_engine(connection_string)


def get_table_info(table_name: str, schema: str = 'vector') -> Dict:
    """Get table structure from database"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        if not inspector.has_table(table_name, schema=schema):
            return None

        columns = inspector.get_columns(table_name, schema=schema)

        # Get row count
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table_name}"))
            row_count = result.scalar()

            # Try to get geometry type
            geometry_type = None
            geometry_col = None
            for col in columns:
                # Check for geometry column (PostGIS doesn't have standard python_type)
                col_type_str = str(col['type']).lower()
                if 'geometry' in col_type_str:
                    geometry_col = col['name']
                    break

            if geometry_col:
                try:
                    result = conn.execute(
                        text(f"SELECT ST_GeometryType(ST_AsText({geometry_col})) FROM {schema}.{table_name} WHERE {geometry_col} IS NOT NULL LIMIT 1")
                    )
                    geom_type_result = result.scalar()
                    if geom_type_result:
                        geometry_type = geom_type_result
                except Exception as e:
                    logger.debug(f"Error getting geometry type: {e}")
                    pass

        return {
            'table_name': table_name,
            'schema': schema,
            'row_count': row_count,
            'geometry_type': geometry_type,
            'columns': [
                {
                    'name': col['name'],
                    'type': str(col['type'])
                }
                for col in columns
            ]
        }
    except Exception as e:
        logger.error(f"Error getting table info: {e}")
        return None


@router.get("/tables")
async def list_tables():
    """List all tables with their metadata"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        # Get all tables from vector schema
        table_names = inspector.get_table_names(schema='vector')

        tables_data = []
        for table_name in sorted(table_names):
            table_info = get_table_info(table_name)
            if table_info:
                # Try to get metadata from metadata table
                with engine.connect() as conn:
                    try:
                        result = conn.execute(
                            text("""
                                SELECT description, category, source, geometry_type
                                FROM metadata.table_descriptions
                                WHERE table_name = :table_name
                            """),
                            {'table_name': table_name}
                        )
                        metadata = result.fetchone()
                        if metadata:
                            table_info['description'] = metadata[0]
                            table_info['category'] = metadata[1]
                            table_info['source'] = metadata[2]
                            table_info['geometry_type'] = metadata[3] or table_info['geometry_type']
                        else:
                            table_info['description'] = None
                            table_info['category'] = None
                            table_info['source'] = None
                    except:
                        table_info['description'] = None
                        table_info['category'] = None
                        table_info['source'] = None

                tables_data.append(table_info)

        return {
            'success': True,
            'tables': tables_data,
            'total': len(tables_data)
        }
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables/{table_name}")
async def get_table_details(table_name: str):
    """Get detailed information about a specific table"""
    try:
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        # Get metadata
        with engine.connect() as conn:
            # Table metadata
            result = conn.execute(
                text("""
                    SELECT id, description, category, source, geometry_type, usage_hint
                    FROM metadata.table_descriptions
                    WHERE table_name = :table_name
                """),
                {'table_name': table_name}
            )
            table_meta = result.fetchone()

            if table_meta:
                table_info['metadata_id'] = table_meta[0]
                table_info['description'] = table_meta[1]
                table_info['category'] = table_meta[2]
                table_info['source'] = table_meta[3]
                table_info['geometry_type'] = table_meta[4] or table_info['geometry_type']
                table_info['usage_hint'] = table_meta[5]
            else:
                table_info['metadata_id'] = None
                table_info['description'] = None
                table_info['category'] = None
                table_info['source'] = None
                table_info['usage_hint'] = None

            # Column metadata
            column_descriptions = {}
            result = conn.execute(
                text("""
                    SELECT column_name, description, data_type, example_value, english_name, is_german
                    FROM metadata.column_descriptions
                    WHERE table_name = :table_name
                    ORDER BY column_name
                """),
                {'table_name': table_name}
            )

            for col_meta in result.fetchall():
                column_descriptions[col_meta[0]] = {
                    'description': col_meta[1],
                    'data_type': col_meta[2],
                    'example_value': col_meta[3],
                    'english_name': col_meta[4],
                    'is_german': col_meta[5]
                }

            # Merge with column info
            for col in table_info['columns']:
                if col['name'] in column_descriptions:
                    col['metadata'] = column_descriptions[col['name']]
                else:
                    col['metadata'] = None

        return {
            'success': True,
            'table': table_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting table details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tables/{table_name}")
async def update_table_description(
    table_name: str,
    description: str,
    category: Optional[str] = None,
    source: Optional[str] = None,
    updated_by: Optional[str] = "api_user"
):
    """Add or update table description"""
    try:
        # Verify table exists
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if exists
            result = conn.execute(
                text("SELECT id FROM metadata.table_descriptions WHERE table_name = :table_name"),
                {'table_name': table_name}
            )
            exists = result.fetchone() is not None

            if exists:
                # Update
                conn.execute(
                    text("""
                        UPDATE metadata.table_descriptions
                        SET description = :description,
                            category = :category,
                            source = :source,
                            updated_at = CURRENT_TIMESTAMP,
                            updated_by = :updated_by,
                            geometry_type = :geometry_type,
                            row_count = :row_count
                        WHERE table_name = :table_name
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'category': category,
                        'source': source,
                        'updated_by': updated_by,
                        'geometry_type': table_info['geometry_type'],
                        'row_count': table_info['row_count']
                    }
                )
            else:
                # Insert
                conn.execute(
                    text("""
                        INSERT INTO metadata.table_descriptions
                        (table_name, description, category, source, geometry_type, row_count, updated_by)
                        VALUES (:table_name, :description, :category, :source, :geometry_type, :row_count, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'category': category,
                        'source': source,
                        'geometry_type': table_info['geometry_type'],
                        'row_count': table_info['row_count'],
                        'updated_by': updated_by
                    }
                )

            conn.commit()

        return {
            'success': True,
            'message': f"Table {table_name} description updated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating table description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/columns")
async def update_column_description(
    table_name: str,
    column_name: str,
    description: str,
    english_name: Optional[str] = None,
    example_value: Optional[str] = None,
    is_german: bool = False,
    updated_by: Optional[str] = "api_user"
):
    """Add or update column description"""
    try:
        # Verify table and column exist
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        col_names = [col['name'] for col in table_info['columns']]
        if column_name not in col_names:
            raise HTTPException(status_code=404, detail=f"Column {column_name} not found in {table_name}")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if exists
            result = conn.execute(
                text("""
                    SELECT id FROM metadata.column_descriptions
                    WHERE table_name = :table_name AND column_name = :column_name
                """),
                {'table_name': table_name, 'column_name': column_name}
            )
            exists = result.fetchone() is not None

            data_type = next((col['type'] for col in table_info['columns'] if col['name'] == column_name), None)

            if exists:
                # Update
                conn.execute(
                    text("""
                        UPDATE metadata.column_descriptions
                        SET description = :description,
                            english_name = :english_name,
                            example_value = :example_value,
                            is_german = :is_german,
                            data_type = :data_type,
                            updated_at = CURRENT_TIMESTAMP,
                            updated_by = :updated_by
                        WHERE table_name = :table_name AND column_name = :column_name
                    """),
                    {
                        'table_name': table_name,
                        'column_name': column_name,
                        'description': description,
                        'english_name': english_name,
                        'example_value': example_value,
                        'is_german': is_german,
                        'data_type': data_type,
                        'updated_by': updated_by
                    }
                )
            else:
                # Insert
                conn.execute(
                    text("""
                        INSERT INTO metadata.column_descriptions
                        (table_name, column_name, description, english_name, example_value, is_german, data_type, updated_by)
                        VALUES (:table_name, :column_name, :description, :english_name, :example_value, :is_german, :data_type, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'column_name': column_name,
                        'description': description,
                        'english_name': english_name,
                        'example_value': example_value,
                        'is_german': is_german,
                        'data_type': data_type,
                        'updated_by': updated_by
                    }
                )

            conn.commit()

        return {
            'success': True,
            'message': f"Column {table_name}.{column_name} description updated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating column description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema-for-prompt")
async def get_schema_for_prompt():
    """Get formatted schema for LLM prompt"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        table_names = inspector.get_table_names(schema='vector')

        schema_text = "# AVAILABLE DATABASE TABLES\n\n"

        for table_name in sorted(table_names):
            table_info = get_table_info(table_name)
            if not table_info:
                continue

            # Get metadata
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT description, category
                        FROM metadata.table_descriptions
                        WHERE table_name = :table_name
                    """),
                    {'table_name': table_name}
                )
                table_meta = result.fetchone()

            # Table header
            if table_meta and table_meta[0]:
                schema_text += f"## Table: {table_name}\n"
                schema_text += f"**Description**: {table_meta[0]}\n"
                if table_meta[1]:
                    schema_text += f"**Category**: {table_meta[1]}\n"
            else:
                schema_text += f"## Table: {table_name}\n"

            schema_text += f"**Geometry**: {table_info['geometry_type'] or 'None'}\n"
            schema_text += f"**Records**: {table_info['row_count']:,}\n"
            schema_text += "**Columns**:\n"

            # Columns with metadata
            with engine.connect() as conn:
                for col in table_info['columns']:
                    result = conn.execute(
                        text("""
                            SELECT description, english_name, is_german
                            FROM metadata.column_descriptions
                            WHERE table_name = :table_name AND column_name = :column_name
                        """),
                        {'table_name': table_name, 'column_name': col['name']}
                    )
                    col_meta = result.fetchone()

                    col_text = f"  - `{col['name']}`"
                    if col_meta and col_meta[0]:
                        col_text += f": {col_meta[0]}"
                        if col_meta[1] and col_meta[2]:
                            col_text += f" (English: {col_meta[1]})"
                    schema_text += col_text + "\n"

            schema_text += "\n"

        return {
            'success': True,
            'schema': schema_text
        }
    except Exception as e:
        logger.error(f"Error generating schema for prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/table-description")
async def update_table_description(table_name: str, description: str, usage_hint: Optional[str] = None):
    """
    Update the description and usage_hint for a table in metadata.table_descriptions.

    This is the single source of truth for table descriptions displayed in the UI.

    Args:
        table_name: Name of the table to update
        description: New description text
        usage_hint: Optional LLM hint — tells the AI how to query this table correctly

    Returns:
        Success message with updated description
    """
    try:
        if not table_name or not description:
            raise HTTPException(status_code=400, detail="table_name and description are required")

        # Verify table exists
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if metadata record exists
            result = conn.execute(
                text("SELECT id FROM metadata.table_descriptions WHERE table_name = :table_name"),
                {'table_name': table_name}
            )
            exists = result.fetchone() is not None

            if exists:
                # Update existing record
                conn.execute(
                    text("""
                        UPDATE metadata.table_descriptions
                        SET description = :description,
                            usage_hint = COALESCE(:usage_hint, usage_hint),
                            updated_at = CURRENT_TIMESTAMP,
                            row_count = :row_count,
                            geometry_type = :geometry_type
                        WHERE table_name = :table_name
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'usage_hint': usage_hint,
                        'row_count': table_info['row_count'],
                        'geometry_type': table_info['geometry_type']
                    }
                )
            else:
                # Insert new record
                conn.execute(
                    text("""
                        INSERT INTO metadata.table_descriptions
                        (table_name, description, usage_hint, row_count, geometry_type, updated_by)
                        VALUES (:table_name, :description, :usage_hint, :row_count, :geometry_type, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'usage_hint': usage_hint,
                        'row_count': table_info['row_count'],
                        'geometry_type': table_info['geometry_type'],
                        'updated_by': 'ui_user'
                    }
                )

            conn.commit()

        return {
            'success': True,
            'table_name': table_name,
            'description': description,
            'usage_hint': usage_hint,
            'message': f"Description updated for table: {table_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating table description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables-with-metadata")
async def get_tables_with_metadata():
    """
    Get all tables with their descriptions from database.

    This is used by the database inspector UI to show available tables.

    Returns:
        List of tables with metadata
    """
    try:
        from app.utils.database import db_manager

        tables_data = db_manager.get_schema_with_descriptions()

        if not tables_data:
            return {
                'success': True,
                'tables': [],
                'message': 'No tables found'
            }

        return {
            'success': True,
            'tables': tables_data,
            'count': len(tables_data)
        }
    except Exception as e:
        logger.error(f"Error fetching tables with metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OSM UPDATE  –  PBF-based: download from Geofabrik, extract & ingest
# ---------------------------------------------------------------------------

import subprocess
import requests as http_requests
import geopandas as gpd
import time as _time

# Geofabrik PBF download URL for Berlin
GEOFABRIK_PBF_URL = "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf"
PBF_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PBF_FILE = PBF_DIR / "berlin-latest.osm.pbf"

# Environment tweaks for GDAL OSM driver (set once at import time)
OSM_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "osmconf.ini"
os.environ["OSM_CONFIG_FILE"] = str(OSM_CONFIG_PATH)
os.environ["OGR_INTERLEAVED_READING"] = "YES"
os.environ["OSM_USE_CUSTOM_INDEXING"] = "NO"
os.environ["GDAL_PAM_ENABLED"] = "NO"

# ---------------------------------------------------------------------------
# PBF extraction categories
#
# Each entry: (table_name_suffix, ogr_layer, sql_where, description, category)
#
# The 5 OGR layers in a PBF:
#   points, lines, multilinestrings, multipolygons, other_relations
# ---------------------------------------------------------------------------

PBF_CATEGORIES = [
    # ── Land Use / Land Cover / Natural (polygons) ──
    ("landuse",        "multipolygons", "landuse IS NOT NULL",                     "Land use areas (residential, industrial, commercial …)",  "Land Use"),
    ("natural",        "multipolygons", "natural IS NOT NULL",                     "Natural features (wood, scrub, grassland, water …)",      "Natural"),
    ("buildings",      "multipolygons", "building IS NOT NULL",                    "Buildings",                                                "Buildings"),
    ("water_areas",    "multipolygons", "natural = 'water' OR water IS NOT NULL OR waterway IS NOT NULL", "Water bodies (lakes, rivers, reservoirs)", "Water"),
    ("leisure_areas",  "multipolygons", "leisure IS NOT NULL",                     "Leisure areas (parks, pitches, gardens …)",                "Leisure"),
    ("amenity_areas",  "multipolygons", "amenity IS NOT NULL",                     "Amenity areas (parking, school grounds …)",                "Amenity"),
    ("boundary",       "multipolygons", "boundary IS NOT NULL",                    "Administrative and other boundaries",                      "Boundary"),

    # ── Roads & Transport (lines) ──
    ("roads",          "lines",         "highway IS NOT NULL",                     "Roads and paths",                                          "Transport"),
    ("railways",       "lines",         "railway IS NOT NULL",                     "Railways and tram lines",                                  "Transport"),
    ("waterways",      "lines",         "waterway IS NOT NULL",                    "Waterways (rivers, streams, canals …)",                    "Water"),
    ("cycleways",      "lines",         "highway = 'cycleway' OR bicycle = 'designated'", "Cycle paths",                                      "Transport"),

    # ── Points of interest (points) ──
    ("hospitals",      "points",        "amenity = 'hospital'",                    "Hospitals and medical centres",                            "Healthcare"),
    ("clinics",        "points",        "amenity = 'clinic'",                      "Medical clinics",                                          "Healthcare"),
    ("pharmacies",     "points",        "amenity = 'pharmacy'",                    "Pharmacies",                                               "Healthcare"),
    ("dentists",       "points",        "amenity = 'dentist'",                     "Dental surgeries",                                         "Healthcare"),
    ("doctors",        "points",        "amenity = 'doctors'",                     "Doctor offices",                                           "Healthcare"),
    ("veterinary",     "points",        "amenity = 'veterinary'",                  "Veterinary clinics",                                       "Healthcare"),
    ("fire_stations",  "points",        "amenity = 'fire_station'",                "Fire stations",                                            "Emergency"),
    ("police_stations","points",        "amenity = 'police'",                      "Police stations",                                          "Emergency"),
    ("toilets",        "points",        "amenity = 'toilets'",                     "Public toilets",                                           "Emergency"),
    ("schools",        "points",        "amenity = 'school'",                      "Schools",                                                  "Education"),
    ("universities",   "points",        "amenity = 'university'",                  "Universities",                                             "Education"),
    ("kindergartens",  "points",        "amenity = 'kindergarten'",                "Kindergartens",                                             "Education"),
    ("libraries",      "points",        "amenity = 'library'",                     "Libraries",                                                "Education"),
    ("transport_stops","points",        "public_transport = 'stop_position' OR public_transport = 'platform' OR highway = 'bus_stop' OR railway = 'station' OR railway = 'halt'", "Public transport stops", "Transport"),
    ("parking",        "points",        "amenity = 'parking'",                     "Parking facilities",                                       "Transport"),
    ("fuel_stations",  "points",        "amenity = 'fuel'",                        "Fuel / petrol stations",                                   "Transport"),
    ("bicycle_parking","points",        "amenity = 'bicycle_parking'",             "Bicycle parking",                                          "Transport"),
    ("ev_charging",    "points",        "amenity = 'charging_station'",            "EV charging stations",                                     "Transport"),
    ("restaurants",    "points",        "amenity = 'restaurant'",                  "Restaurants",                                               "Food & Drink"),
    ("cafes",          "points",        "amenity = 'cafe'",                        "Cafés",                                                    "Food & Drink"),
    ("bars",           "points",        "amenity = 'bar' OR amenity = 'pub'",      "Bars and pubs",                                            "Food & Drink"),
    ("fast_food",      "points",        "amenity = 'fast_food'",                   "Fast-food restaurants",                                    "Food & Drink"),
    ("supermarkets",   "points",        "shop = 'supermarket'",                    "Supermarkets",                                             "Shopping"),
    ("marketplaces",   "points",        "amenity = 'marketplace'",                 "Marketplaces",                                             "Shopping"),
    ("parks",          "points",        "leisure = 'park'",                        "Parks and gardens",                                         "Leisure"),
    ("playgrounds",    "points",        "leisure = 'playground'",                  "Playgrounds",                                               "Leisure"),
    ("sports_centres", "points",        "leisure = 'sports_centre'",               "Sports centres",                                            "Leisure"),
    ("swimming_pools", "points",        "leisure = 'swimming_pool'",               "Swimming pools",                                            "Leisure"),
    ("theatres",       "points",        "amenity = 'theatre'",                     "Theatres",                                                  "Leisure"),
    ("cinemas",        "points",        "amenity = 'cinema'",                      "Cinemas",                                                   "Leisure"),
    ("museums",        "points",        "tourism = 'museum'",                      "Museums",                                                   "Tourism"),
    ("hotels",         "points",        "tourism = 'hotel'",                       "Hotels",                                                    "Tourism"),
    ("hostels",        "points",        "tourism = 'hostel'",                      "Hostels",                                                   "Tourism"),
    ("tourist_info",   "points",        "tourism = 'information'",                 "Tourist information",                                       "Tourism"),
    ("viewpoints",     "points",        "tourism = 'viewpoint'",                   "Viewpoints",                                                "Tourism"),
    ("places_of_worship","points",      "amenity = 'place_of_worship'",            "Places of worship",                                         "Community"),
    ("community_centres","points",      "amenity = 'community_centre'",            "Community centres",                                         "Community"),
    ("social_facilities","points",      "amenity = 'social_facility'",             "Social facilities",                                         "Community"),
    ("post_offices",   "points",        "amenity = 'post_office'",                 "Post offices",                                              "Misc"),
    ("banks",          "points",        "amenity = 'bank'",                        "Banks",                                                     "Misc"),
    ("atms",           "points",        "amenity = 'atm'",                         "ATMs",                                                      "Misc"),
    ("recycling",      "points",        "amenity = 'recycling'",                   "Recycling points",                                          "Misc"),
    ("waste_disposal", "points",        "amenity = 'waste_disposal'",              "Waste disposal sites",                                      "Misc"),
    ("benches",        "points",        "amenity = 'bench'",                       "Public benches",                                            "Misc"),
    ("drinking_water", "points",        "amenity = 'drinking_water'",              "Drinking water fountains",                                  "Misc"),
    ("shelters",       "points",        "amenity = 'shelter'",                     "Public shelters",                                           "Misc"),
]

# Module-level status tracker (shared between request and background task)
osm_update_status: Dict = {
    "running": False,
    "phase": None,          # "downloading", "extracting", "done"
    "progress": 0,
    "total": len(PBF_CATEGORIES),
    "current_category": None,
    "download_progress": 0,  # bytes downloaded
    "download_total": 0,     # total bytes (from Content-Length)
    "log": [],
    "last_run": None,
    "error": None,
}


def _log_change(engine, table_name: str, action: str, details: dict, performed_by: str = "system"):
    """Write an entry to metadata.data_change_log."""
    try:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO metadata.data_change_log (table_name, action, details, performed_by)
                    VALUES (:table_name, :action, :details, :performed_by)
                """),
                {
                    "table_name": table_name,
                    "action": action,
                    "details": json.dumps(details),
                    "performed_by": performed_by,
                },
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not write change log: {e}")


def _download_pbf() -> bool:
    """Download Berlin PBF from Geofabrik with progress tracking."""
    global osm_update_status

    osm_update_status["phase"] = "downloading"
    osm_update_status["log"].append("📥 Downloading Berlin PBF from Geofabrik...")
    logger.info(f"Downloading PBF from {GEOFABRIK_PBF_URL}")

    PBF_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resp = http_requests.get(GEOFABRIK_PBF_URL, stream=True, timeout=600)
        resp.raise_for_status()

        total_size = int(resp.headers.get("content-length", 0))
        osm_update_status["download_total"] = total_size

        downloaded = 0
        with open(PBF_FILE, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                osm_update_status["download_progress"] = downloaded

        size_mb = PBF_FILE.stat().st_size / (1024 * 1024)
        msg = f"  ✅ PBF downloaded: {size_mb:.1f} MB"
        osm_update_status["log"].append(msg)
        logger.info(msg)
        return True

    except Exception as e:
        msg = f"  ❌ PBF download failed: {str(e)[:200]}"
        osm_update_status["log"].append(msg)
        logger.error(msg)
        return False


def _run_osm_update():
    """Background task: download PBF, extract all categories, ingest into PostGIS."""
    global osm_update_status

    osm_update_status["running"] = True
    osm_update_status["phase"] = "downloading"
    osm_update_status["progress"] = 0
    osm_update_status["total"] = len(PBF_CATEGORIES)
    osm_update_status["log"] = []
    osm_update_status["error"] = None
    osm_update_status["current_category"] = None
    osm_update_status["download_progress"] = 0
    osm_update_status["download_total"] = 0

    engine = get_db_engine()
    tmp_dir = None

    try:
        # ── Phase 1: Download PBF ──
        if not _download_pbf():
            osm_update_status["error"] = "PBF download failed"
            return

        # ── Phase 2 & 3: Extract + Ingest each category ──
        osm_update_status["phase"] = "extracting"
        tmp_dir = tempfile.mkdtemp(prefix="osm_extract_")
        total = len(PBF_CATEGORIES)
        successful = 0
        failed = 0

        for idx, (name, ogr_layer, sql_where, description, category) in enumerate(PBF_CATEGORIES):
            osm_update_status["progress"] = idx
            osm_update_status["current_category"] = name
            table_name = f"osm_{name}"
            msg = f"[{idx + 1}/{total}] Extracting {name} from {ogr_layer}..."
            osm_update_status["log"].append(msg)
            logger.info(msg)

            try:
                # Extract from PBF to temp GeoJSON using ogr2ogr
                geojson_path = Path(tmp_dir) / f"{name}.geojson"
                if geojson_path.exists():
                    geojson_path.unlink()

                cmd = [
                    "ogr2ogr",
                    "-f", "GeoJSON",
                    "-t_srs", "EPSG:4326",
                    "-where", sql_where,
                    str(geojson_path),
                    str(PBF_FILE),
                    ogr_layer,
                ]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )

                if result.returncode != 0:
                    logger.warning(f"ogr2ogr stderr for {name}: {result.stderr[:300]}")

                if not geojson_path.exists() or geojson_path.stat().st_size < 50:
                    msg = f"  ⚠️  {name}: no features extracted"
                    osm_update_status["log"].append(msg)
                    continue

                # Load GeoJSON into GeoDataFrame
                gdf = gpd.read_file(str(geojson_path))

                # Ensure valid geometry and CRS
                gdf = gdf[gdf.geometry.notna()]
                if len(gdf) > 0:
                    gdf = gdf[gdf.geometry.is_valid]
                if gdf.crs is None:
                    gdf = gdf.set_crs(epsg=4326)
                elif str(gdf.crs) != "EPSG:4326":
                    gdf = gdf.to_crs(epsg=4326)

                # Lowercase column names
                gdf = gdf.rename(columns=lambda c: c.lower())

                if len(gdf) == 0:
                    msg = f"  ⚠️  {name}: no valid features after cleanup"
                    osm_update_status["log"].append(msg)
                    continue

                # Write to PostGIS (replace existing)
                gdf.to_postgis(
                    table_name,
                    engine,
                    schema="vector",
                    if_exists="replace",
                    index=False,
                )

                # Create spatial index on geometry (EPSG:4326)
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"""
                            CREATE INDEX IF NOT EXISTS idx_{table_name}_geom
                            ON vector.{table_name} USING GIST(geometry)
                        """))
                        conn.commit()
                except Exception:
                    pass

                # Add projected geom_25833 column for faster spatial queries
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"""
                            ALTER TABLE vector.{table_name}
                            ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
                        """))
                        conn.execute(text(f"""
                            UPDATE vector.{table_name}
                            SET geom_25833 = ST_Transform(geometry, 25833)
                            WHERE geometry IS NOT NULL
                        """))
                        conn.execute(text(f"""
                            CREATE INDEX IF NOT EXISTS idx_{table_name}_geom25833
                            ON vector.{table_name} USING GIST(geom_25833)
                        """))
                        conn.commit()
                except Exception as e:
                    logger.warning(f"Could not create geom_25833 for {table_name}: {e}")

                row_count = len(gdf)
                successful += 1
                msg = f"  ✅ {name}: {row_count:,} features"
                osm_update_status["log"].append(msg)

                # Log the change
                _log_change(engine, table_name, "osm_update", {
                    "rows": row_count,
                    "description": description,
                    "source": "Geofabrik PBF",
                    "ogr_layer": ogr_layer,
                })

                # Upsert metadata.table_descriptions
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO metadata.table_descriptions
                            (table_name, description, category, source, row_count, updated_by)
                        VALUES (:tn, :desc, :cat, 'Geofabrik PBF', :rc, 'osm_update')
                        ON CONFLICT (table_name) DO UPDATE
                            SET description = EXCLUDED.description,
                                category     = EXCLUDED.category,
                                row_count    = EXCLUDED.row_count,
                                source       = EXCLUDED.source,
                                updated_at   = CURRENT_TIMESTAMP
                    """), {"tn": table_name, "desc": description, "cat": category, "rc": row_count})
                    conn.commit()

                # Auto-populate metadata.column_descriptions
                try:
                    with engine.connect() as conn:
                        # Clear old column descriptions for this table
                        conn.execute(text(
                            "DELETE FROM metadata.column_descriptions WHERE table_name = :tn"
                        ), {"tn": table_name})

                        for col_name in gdf.columns:
                            col_lower = col_name.lower()
                            # Skip internal/geometry columns
                            if col_lower in ('fid', 'ogc_fid'):
                                continue

                            # Determine data type
                            dtype = str(gdf[col_name].dtype)
                            if col_lower in ('geometry', 'geom_25833'):
                                data_type = 'geometry'
                            elif 'int' in dtype:
                                data_type = 'integer'
                            elif 'float' in dtype:
                                data_type = 'real'
                            else:
                                data_type = 'text'

                            # Get an example value (first non-null)
                            example = None
                            if col_lower not in ('geometry', 'geom_25833'):
                                non_null = gdf[col_name].dropna()
                                if len(non_null) > 0:
                                    example = str(non_null.iloc[0])[:100]

                            # Generate description
                            col_desc = f"OSM '{col_lower}' attribute from {ogr_layer} layer"
                            if col_lower == 'geometry':
                                col_desc = "Geometry in EPSG:4326 (WGS 84)"
                            elif col_lower == 'geom_25833':
                                col_desc = "Projected geometry in EPSG:25833 (ETRS89 / UTM zone 33N)"
                            elif col_lower == 'osm_id':
                                col_desc = "OpenStreetMap feature ID"
                            elif col_lower == 'name':
                                col_desc = "Feature name"

                            conn.execute(text("""
                                INSERT INTO metadata.column_descriptions
                                (table_name, column_name, description, english_name, example_value, is_german, data_type, updated_by)
                                VALUES (:tn, :cn, :desc, :en, :ex, false, :dt, 'osm_update')
                            """), {
                                "tn": table_name,
                                "cn": col_lower,
                                "desc": col_desc,
                                "en": col_lower,
                                "ex": example,
                                "dt": data_type,
                            })
                        conn.commit()
                except Exception as e:
                    logger.warning(f"Could not populate column_descriptions for {table_name}: {e}")

            except Exception as e:
                failed += 1
                msg = f"  ❌ {name}: {str(e)[:120]}"
                osm_update_status["log"].append(msg)
                logger.error(f"OSM update – {name} failed: {e}")

        osm_update_status["phase"] = "done"
        summary = f"✅ OSM update complete – {successful} succeeded, {failed} failed out of {total}"
        osm_update_status["log"].append(summary)
        osm_update_status["last_run"] = datetime.utcnow().isoformat()

        _log_change(engine, None, "osm_update_batch", {
            "successful": successful,
            "failed": failed,
            "total": total,
            "source": "Geofabrik PBF",
        })

    except Exception as e:
        osm_update_status["error"] = str(e)
        osm_update_status["log"].append(f"❌ Fatal error: {str(e)}")
        logger.error(f"OSM update fatal error: {e}")
    finally:
        osm_update_status["running"] = False
        osm_update_status["progress"] = osm_update_status["total"]
        osm_update_status["current_category"] = None
        # Clean up temp directory
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/osm-update")
async def trigger_osm_update(background_tasks: BackgroundTasks):
    """Start a background OSM data refresh via PBF download + extract."""
    if osm_update_status["running"]:
        raise HTTPException(status_code=409, detail="An OSM update is already running")

    background_tasks.add_task(_run_osm_update)
    return {"success": True, "message": "OSM PBF update started", "total_categories": len(PBF_CATEGORIES)}


@router.get("/osm-update/status")
async def get_osm_update_status():
    """Poll the current OSM update progress."""
    return {
        "success": True,
        "running": osm_update_status["running"],
        "phase": osm_update_status["phase"],
        "progress": osm_update_status["progress"],
        "total": osm_update_status["total"],
        "current_category": osm_update_status["current_category"],
        "download_progress": osm_update_status["download_progress"],
        "download_total": osm_update_status["download_total"],
        "log": osm_update_status["log"],
        "last_run": osm_update_status["last_run"],
        "error": osm_update_status["error"],
    }


@router.post("/osm-update/supermarkets")
async def download_osm_supermarkets():
    """Download OSM supermarkets via Overpass API for Berlin and ingest into vector.osm_supermarkets."""
    from app.utils.data_loaders.osm_loader import OSMLoader
    import geopandas as gpd
    
    table_name = "osm_supermarkets"
    bbox = (13.088, 52.338, 13.761, 52.675) # Berlin bbox
    
    try:
        loader = OSMLoader()
        gdf = loader.query_overpass(bbox, ['supermarket'])
        
        if gdf.empty or len(gdf) == 0:
            return {"success": False, "message": "No supermarkets found for the specified bounding box."}
        
        # Ensure valid geometry and CRS
        gdf = gdf[gdf.geometry.notna()]
        if len(gdf) > 0:
            gdf = gdf[gdf.geometry.is_valid]
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        elif str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)
            
        # Clean and deduplicate column names
        import re
        new_cols = []
        seen = set()
        for c in gdf.columns:
            if c == 'geometry':
                new_cols.append('geometry')
                seen.add('geometry')
                continue
            # Lowercase, replace non-alphanumeric with underscore
            clean_c = re.sub(r'[^a-z0-9_]', '_', str(c).lower())
            clean_c = re.sub(r'_+', '_', clean_c).strip('_')
            if not clean_c:
                clean_c = "col"
            clean_c = clean_c[:60] # leave room for suffix
            base_c = clean_c
            counter = 1
            while clean_c in seen:
                clean_c = f"{base_c}_{counter}"
                counter += 1
            seen.add(clean_c)
            new_cols.append(clean_c)
        gdf.columns = new_cols
        
        engine = get_db_engine()
        
        # Write to PostGIS
        gdf.to_postgis(
            table_name,
            engine,
            schema="vector",
            if_exists="replace",
            index=False,
        )
        
        row_count = len(gdf)
        
        # Create spatial index and geom_25833
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geom
                ON vector.{table_name} USING GIST(geometry)
            """))
            # Add projected geom_25833 column
            conn.execute(text(f"""
                ALTER TABLE vector.{table_name}
                ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
            """))
            conn.execute(text(f"""
                UPDATE vector.{table_name}
                SET geom_25833 = ST_Transform(ST_SetSRID(geometry, 4326), 25833)
                WHERE geometry IS NOT NULL
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geom25833
                ON vector.{table_name} USING GIST(geom_25833)
            """))
            conn.commit()
            
        description = "Supermarkets in Berlin fetched via Overpass API"
        category = "Shopping"
        source = "Overpass API"
        
        # Log the change
        _log_change(engine, table_name, "osm_update_supermarkets", {
            "rows": row_count,
            "description": description,
            "source": source,
        })
        
        # Upsert table_descriptions
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO metadata.table_descriptions
                    (table_name, description, category, source, row_count, updated_by)
                VALUES (:tn, :desc, :cat, :src, :rc, 'osm_update_supermarkets')
                ON CONFLICT (table_name) DO UPDATE
                    SET description = EXCLUDED.description,
                        category     = EXCLUDED.category,
                        row_count    = EXCLUDED.row_count,
                        source       = EXCLUDED.source,
                        updated_at   = CURRENT_TIMESTAMP
            """), {"tn": table_name, "desc": description, "cat": category, "src": source, "rc": row_count})
            
            # Auto-populate metadata.column_descriptions
            conn.execute(text(
                "DELETE FROM metadata.column_descriptions WHERE table_name = :tn"
            ), {"tn": table_name})

            for col_name in gdf.columns:
                col_lower = str(col_name).lower()
                # Skip internal/geometry columns
                if col_lower in ('fid', 'ogc_fid'):
                    continue

                # Determine data type
                dtype = str(gdf[col_name].dtype)
                if col_lower in ('geometry', 'geom_25833'):
                    data_type = 'geometry'
                elif 'int' in dtype:
                    data_type = 'integer'
                elif 'float' in dtype:
                    data_type = 'real'
                else:
                    data_type = 'text'

                # Get an example value (first non-null)
                example = None
                if col_lower not in ('geometry', 'geom_25833'):
                    non_null = gdf[col_name].dropna()
                    if len(non_null) > 0:
                        example = str(non_null.iloc[0])[:100]

                # Generate description
                col_desc = f"OSM '{col_lower}' attribute"
                if col_lower == 'geometry':
                    col_desc = "Geometry in EPSG:4326 (WGS 84)"
                elif col_lower == 'geom_25833':
                    col_desc = "Projected geometry in EPSG:25833 (ETRS89 / UTM zone 33N)"
                elif col_lower == 'osm_id':
                    col_desc = "OpenStreetMap feature ID"
                elif col_lower == 'name':
                    col_desc = "Feature name"

                conn.execute(text("""
                    INSERT INTO metadata.column_descriptions
                    (table_name, column_name, description, english_name, example_value, is_german, data_type, updated_by)
                    VALUES (:tn, :cn, :desc, :en, :ex, false, :dt, 'osm_update_supermarkets')
                """), {
                    "tn": table_name,
                    "cn": col_lower,
                    "desc": col_desc,
                    "en": col_lower,
                    "ex": example,
                    "dt": data_type,
                })
            conn.commit()

        return {"success": True, "message": f"Successfully updated {row_count} supermarkets via Overpass API.", "row_count": row_count}

    except Exception as e:
        logger.error(f"Error updating supermarkets via Overpass: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/osm-update/transport_stops")
async def download_osm_transport_stops():
    """Download OSM transport stops via Overpass API for Berlin and ingest into vector.osm_transport_stops."""
    from app.utils.data_loaders.osm_loader import OSMLoader
    import geopandas as gpd
    
    table_name = "osm_transport_stops"
    bbox = (13.088, 52.338, 13.761, 52.675) # Berlin bbox
    
    try:
        loader = OSMLoader()
        gdf = loader.query_overpass(bbox, ['transport_stop'])
        
        if gdf.empty or len(gdf) == 0:
            return {"success": False, "message": "No transport stops found for the specified bounding box."}
        
        # Ensure valid geometry and CRS
        gdf = gdf[gdf.geometry.notna()]
        if len(gdf) > 0:
            gdf = gdf[gdf.geometry.is_valid]
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)
        elif str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)
            
        # Clean and deduplicate column names
        import re
        new_cols = []
        seen = set()
        for c in gdf.columns:
            if c == 'geometry':
                new_cols.append('geometry')
                seen.add('geometry')
                continue
            # Lowercase, replace non-alphanumeric with underscore
            clean_c = re.sub(r'[^a-z0-9_]', '_', str(c).lower())
            clean_c = re.sub(r'_+', '_', clean_c).strip('_')
            if not clean_c:
                clean_c = "col"
            clean_c = clean_c[:60] # leave room for suffix
            base_c = clean_c
            counter = 1
            while clean_c in seen:
                clean_c = f"{base_c}_{counter}"
                counter += 1
            seen.add(clean_c)
            new_cols.append(clean_c)
        gdf.columns = new_cols
        
        engine = get_db_engine()
        
        # Write to PostGIS
        gdf.to_postgis(
            table_name,
            engine,
            schema="vector",
            if_exists="replace",
            index=False,
        )
        
        row_count = len(gdf)
        
        # Create spatial index and geom_25833
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geom
                ON vector.{table_name} USING GIST(geometry)
            """))
            # Add projected geom_25833 column
            conn.execute(text(f"""
                ALTER TABLE vector.{table_name}
                ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
            """))
            conn.execute(text(f"""
                UPDATE vector.{table_name}
                SET geom_25833 = ST_Transform(ST_SetSRID(geometry, 4326), 25833)
                WHERE geometry IS NOT NULL
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geom25833
                ON vector.{table_name} USING GIST(geom_25833)
            """))
            conn.commit()
            
        description = "Public transport stops in Berlin fetched via Overpass API"
        category = "Transport"
        source = "Overpass API"
        
        # Log the change
        _log_change(engine, table_name, "osm_update_transport_stops", {
            "rows": row_count,
            "description": description,
            "source": source,
        })
        
        # Upsert table_descriptions
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO metadata.table_descriptions
                    (table_name, description, category, source, row_count, updated_by)
                VALUES (:tn, :desc, :cat, :src, :rc, 'osm_update_transport_stops')
                ON CONFLICT (table_name) DO UPDATE
                    SET description = EXCLUDED.description,
                        category     = EXCLUDED.category,
                        row_count    = EXCLUDED.row_count,
                        source       = EXCLUDED.source,
                        updated_at   = CURRENT_TIMESTAMP
            """), {"tn": table_name, "desc": description, "cat": category, "src": source, "rc": row_count})
            
            # Auto-populate metadata.column_descriptions
            conn.execute(text(
                "DELETE FROM metadata.column_descriptions WHERE table_name = :tn"
            ), {"tn": table_name})

            for col_name in gdf.columns:
                col_lower = str(col_name).lower()
                # Skip internal/geometry columns
                if col_lower in ('fid', 'ogc_fid'):
                    continue

                # Determine data type
                dtype = str(gdf[col_name].dtype)
                if col_lower in ('geometry', 'geom_25833'):
                    data_type = 'geometry'
                elif 'int' in dtype:
                    data_type = 'integer'
                elif 'float' in dtype:
                    data_type = 'real'
                else:
                    data_type = 'text'

                # Get an example value (first non-null)
                example = None
                if col_lower not in ('geometry', 'geom_25833'):
                    non_null = gdf[col_name].dropna()
                    if len(non_null) > 0:
                        example = str(non_null.iloc[0])[:100]

                # Generate description
                col_desc = f"OSM '{col_lower}' attribute"
                if col_lower == 'geometry':
                    col_desc = "Geometry in EPSG:4326 (WGS 84)"
                elif col_lower == 'geom_25833':
                    col_desc = "Projected geometry in EPSG:25833 (ETRS89 / UTM zone 33N)"
                elif col_lower == 'osm_id':
                    col_desc = "OpenStreetMap feature ID"
                elif col_lower == 'name':
                    col_desc = "Feature name"

                conn.execute(text("""
                    INSERT INTO metadata.column_descriptions
                    (table_name, column_name, description, english_name, example_value, is_german, data_type, updated_by)
                    VALUES (:tn, :cn, :desc, :en, :ex, false, :dt, 'osm_update_transport_stops')
                """), {
                    "tn": table_name,
                    "cn": col_lower,
                    "desc": col_desc,
                    "en": col_lower,
                    "ex": example,
                    "dt": data_type,
                })
            conn.commit()

        return {"success": True, "message": f"Successfully updated {row_count} transport stops via Overpass API.", "row_count": row_count}

    except Exception as e:
        logger.error(f"Error updating transport stops via Overpass: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/osm-update/categories")
async def list_osm_categories():
    """Return the full list of OSM categories that will be extracted from PBF."""
    return {
        "success": True,
        "categories": [
            {"name": name, "layer": layer, "description": desc, "category": cat}
            for name, layer, _where, desc, cat in PBF_CATEGORIES
        ],
        "total": len(PBF_CATEGORIES),
    }


# ---------------------------------------------------------------------------
# CHANGE LOG
# ---------------------------------------------------------------------------

@router.get("/changelog")
async def get_changelog(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    table_name: Optional[str] = None,
):
    """Return paginated change log entries with optional filters."""
    try:
        engine = get_db_engine()
        offset = (page - 1) * per_page

        where_clauses = []
        params: Dict = {"limit": per_page, "offset": offset}

        if action:
            where_clauses.append("action = :action")
            params["action"] = action
        if table_name:
            where_clauses.append("table_name = :table_name")
            params["table_name"] = table_name

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with engine.connect() as conn:
            # Total count
            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM metadata.data_change_log {where_sql}"), params
            )
            total = count_result.scalar() or 0

            # Rows
            result = conn.execute(
                text(f"""
                    SELECT id, table_name, action, details, performed_by, created_at
                    FROM metadata.data_change_log
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )

            entries = []
            for row in result.fetchall():
                details = row[3]
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except Exception:
                        pass
                entries.append({
                    "id": row[0],
                    "table_name": row[1],
                    "action": row[2],
                    "details": details,
                    "performed_by": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                })

        return {
            "success": True,
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
    except Exception as e:
        logger.error(f"Error fetching changelog: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# FILE UPLOAD  –  GeoJSON, Shapefile (.zip), CSV
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    table_name: Optional[str] = Query(None, description="Custom table name (auto-generated if empty)"),
    uploaded_by: str = Query("api_user"),
):
    """Upload a GeoJSON, Shapefile (.zip), or CSV file and ingest into PostGIS."""
    import geopandas as gpd
    import pandas as pd

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    allowed = {"geojson", "json", "zip", "csv"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported format '.{ext}'. Allowed: {', '.join(allowed)}")

    # Derive a clean table name
    if not table_name:
        base = file.filename.rsplit(".", 1)[0]
        # PostgreSQL identifiers max 63 chars; to_postgis auto-creates
        # idx_{table}_geometry, so keep table name ≤ 50 chars total.
        table_name = "custom_" + "".join(c if c.isalnum() else "_" for c in base.lower()).strip("_")[:43]

    # Ensure table name is safe
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name.lower()).strip("_")
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid table name")

    tmpdir = None
    try:
        # Save uploaded file to a temp directory
        tmpdir = tempfile.mkdtemp(prefix="geoupload_")
        tmp_path = os.path.join(tmpdir, file.filename)
        with open(tmp_path, "wb") as f_out:
            content = await file.read()
            f_out.write(content)

        has_geometry = False
        file_format = ext

        if ext in ("geojson", "json"):
            gdf = gpd.read_file(tmp_path)
            has_geometry = True
            file_format = "GeoJSON"
        elif ext == "zip":
            # Shapefile in zip
            gdf = gpd.read_file(f"zip://{tmp_path}")
            has_geometry = True
            file_format = "Shapefile"
        elif ext == "csv":
            df = pd.read_csv(tmp_path)
            # Try to detect lat/lon columns
            lat_cols = [c for c in df.columns if c.lower() in ("lat", "latitude", "y")]
            lon_cols = [c for c in df.columns if c.lower() in ("lon", "lng", "longitude", "x")]
            if lat_cols and lon_cols:
                from shapely.geometry import Point
                geometry = [Point(xy) for xy in zip(df[lon_cols[0]], df[lat_cols[0]])]
                gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
                has_geometry = True
            else:
                gdf = gpd.GeoDataFrame(df)
            file_format = "CSV"
        else:
            raise HTTPException(status_code=400, detail="Unrecognised format")

        # Ensure CRS
        if has_geometry:
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=4326)
            elif str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs(epsg=4326)

        engine = get_db_engine()
        row_count = len(gdf)
        col_count = len(gdf.columns)

        # Write to PostGIS
        if has_geometry and "geometry" in gdf.columns:
            gdf.to_postgis(safe_name, engine, schema="vector", if_exists="replace", index=False)

            # Create spatial index on geometry column
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"""
                        CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom
                        ON vector."{safe_name}" USING GIST(geometry)
                    """))
                    conn.commit()
            except Exception as e:
                logger.warning(f"Could not create spatial index for {safe_name}: {e}")

            # Add projected geom_25833 column for fast spatial queries
            try:
                with engine.connect() as conn:
                    # 1. Add literal 25833 column
                    conn.execute(text(f"""
                        ALTER TABLE vector."{safe_name}"
                        ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
                    """))
                    # 2. Update via precise SRID transformation: Set source SRID explicitly then Transform
                    conn.execute(text(f"""
                        UPDATE vector."{safe_name}"
                        SET geom_25833 = ST_Transform(ST_SetSRID(geometry, 4326), 25833)
                        WHERE geometry IS NOT NULL
                    """))
                    # 3. Create index for performance
                    conn.execute(text(f"""
                        CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom25833
                        ON vector."{safe_name}" USING GIST(geom_25833)
                    """))
                    conn.commit()
            except Exception as e:
                logger.warning(f"Could not create geom_25833 for {safe_name}: {e}")
        else:
            gdf.to_sql(safe_name, engine, schema="vector", if_exists="replace", index=False)

        # Register in custom_datasets
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO metadata.custom_datasets
                    (table_name, original_filename, file_format, row_count, column_count, has_geometry, uploaded_by)
                VALUES (:tn, :fn, :ff, :rc, :cc, :hg, :ub)
                ON CONFLICT (table_name) DO UPDATE SET
                    original_filename = EXCLUDED.original_filename,
                    file_format       = EXCLUDED.file_format,
                    row_count         = EXCLUDED.row_count,
                    column_count      = EXCLUDED.column_count,
                    has_geometry      = EXCLUDED.has_geometry,
                    uploaded_at       = CURRENT_TIMESTAMP,
                    uploaded_by       = EXCLUDED.uploaded_by
            """), {
                "tn": safe_name, "fn": file.filename, "ff": file_format,
                "rc": row_count, "cc": col_count, "hg": has_geometry, "ub": uploaded_by,
            })
            conn.commit()

        # Upsert table_descriptions
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO metadata.table_descriptions
                    (table_name, description, category, source, row_count, updated_by)
                VALUES (:tn, :desc, 'User Upload', :src, :rc, :ub)
                ON CONFLICT (table_name) DO UPDATE SET
                    description = EXCLUDED.description,
                    row_count   = EXCLUDED.row_count,
                    source      = EXCLUDED.source,
                    updated_at  = CURRENT_TIMESTAMP
            """), {
                "tn": safe_name,
                "desc": f"User-uploaded dataset from {file.filename}",
                "src": file.filename,
                "rc": row_count,
                "ub": uploaded_by,
            })
            conn.commit()

        _log_change(engine, safe_name, "upload", {
            "filename": file.filename,
            "format": file_format,
            "rows": row_count,
            "columns": col_count,
            "has_geometry": has_geometry,
        }, performed_by=uploaded_by)

        return {
            "success": True,
            "table_name": safe_name,
            "row_count": row_count,
            "column_count": col_count,
            "has_geometry": has_geometry,
            "message": f"Uploaded {row_count:,} rows to vector.{safe_name}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# RENAME TABLE
# ---------------------------------------------------------------------------

@router.put("/tables/{table_name}/rename")
async def rename_table(table_name: str, new_name: str = Query(..., description="New table name")):
    """Rename a table in the vector schema and update all metadata references."""
    engine = get_db_engine()

    # Validate old name
    safe_old = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name.lower()).strip("_")
    if safe_old != table_name:
        raise HTTPException(status_code=400, detail="Invalid current table name")

    # Validate new name
    safe_new = "".join(c if c.isalnum() or c == "_" else "_" for c in new_name.lower()).strip("_")
    if safe_new != new_name or not new_name:
        raise HTTPException(status_code=400, detail="Invalid new table name. Use only lowercase letters, numbers and underscores.")
    if safe_new == safe_old:
        return {"success": True, "message": "Name unchanged"}

    # Check source table exists
    insp = inspect(engine)
    if not insp.has_table(table_name, schema="vector"):
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    # Check target name is free
    if insp.has_table(new_name, schema="vector"):
        raise HTTPException(status_code=409, detail=f"A table named '{new_name}' already exists")

    with engine.connect() as conn:
        try:
            # Rename the actual table
            conn.execute(text(f'ALTER TABLE vector."{table_name}" RENAME TO "{new_name}"'))

            # Update metadata references
            conn.execute(text("UPDATE metadata.table_descriptions SET table_name = :nn WHERE table_name = :on"), {"nn": new_name, "on": table_name})
            conn.execute(text("UPDATE metadata.column_descriptions SET table_name = :nn WHERE table_name = :on"), {"nn": new_name, "on": table_name})
            conn.execute(text("UPDATE metadata.custom_datasets SET table_name = :nn WHERE table_name = :on"), {"nn": new_name, "on": table_name})
            conn.commit()
        except Exception as e:
            logger.error(f"Error renaming table: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    _log_change(engine, new_name, "rename", {"old_name": table_name, "new_name": new_name})

    return {"success": True, "message": f"Table renamed from vector.{table_name} to vector.{new_name}"}


# ---------------------------------------------------------------------------
# DELETE TABLE
# ---------------------------------------------------------------------------

@router.delete("/tables/{table_name}")
async def delete_any_table(table_name: str):
    """Delete any dataset from the vector schema and clean up its metadata."""
    engine = get_db_engine()

    # Basic safety against SQL injection on the table name
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name.lower()).strip("_")
    if safe_name != table_name:
        raise HTTPException(status_code=400, detail="Invalid table name")

    with engine.connect() as conn:
        try:
            # We allow deletion of ANY table in the vector schema
            conn.execute(text(f'DROP TABLE IF EXISTS vector."{table_name}" CASCADE'))
            
            # Clean up all metadata references
            conn.execute(text("DELETE FROM metadata.custom_datasets WHERE table_name = :tn"), {"tn": table_name})
            conn.execute(text("DELETE FROM metadata.table_descriptions WHERE table_name = :tn"), {"tn": table_name})
            conn.execute(text("DELETE FROM metadata.column_descriptions WHERE table_name = :tn"), {"tn": table_name})
            conn.commit()
        except Exception as e:
            logger.error(f"Error deleting table: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    _log_change(engine, table_name, "delete", {"reason": "user_request"})

    return {"success": True, "message": f"Table vector.{table_name} deleted"}


# ---------------------------------------------------------------------------
# ROW PREVIEW
# ---------------------------------------------------------------------------

@router.get("/tables/{table_name}/preview")
async def preview_table(
    table_name: str,
    limit: int = Query(50, ge=1, le=500),
    filter_col: Optional[str] = None,
    filter_val: Optional[str] = None,
):
    """Return the first N rows of a table, with geometry converted to WKT.

    When filter_col and filter_val are provided, returns all rows (up to 500)
    where filter_col::text ILIKE '%filter_val%'.
    """
    engine = get_db_engine()

    # Validate table exists
    inspector = inspect(engine)
    if not inspector.has_table(table_name, schema="vector"):
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    try:
        with engine.connect() as conn:
            # Get column info to detect geometry columns
            cols = inspector.get_columns(table_name, schema="vector")
            col_names = [c["name"] for c in cols]

            # Validate filter_col against real column names to prevent SQL injection
            if filter_col and filter_col not in col_names:
                raise HTTPException(status_code=400, detail=f"Unknown column: {filter_col}")

            select_parts = []
            for col in cols:
                col_type = str(col["type"]).lower()
                if "geometry" in col_type:
                    select_parts.append(f'ST_AsText("{col["name"]}") AS "{col["name"]}"')
                else:
                    select_parts.append(f'"{col["name"]}"')

            select_sql = ", ".join(select_parts)

            # Build WHERE clause and params
            params: dict = {"lim": 500 if filter_col else limit}
            where_sql = ""
            if filter_col and filter_val is not None:
                where_sql = f'WHERE "{filter_col}"::text ILIKE :fval'
                params["fval"] = f"%{filter_val}%"

            query = f'SELECT {select_sql} FROM vector."{table_name}" {where_sql} LIMIT :lim'
            result = conn.execute(text(query), params)

            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # JSON-serialise datetimes etc.
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, (datetime,)):
                        row[k] = v.isoformat()
                    elif v is not None and not isinstance(v, (str, int, float, bool)):
                        row[k] = str(v)

        return {
            "success": True,
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "count": len(rows),
            "filtered": bool(filter_col),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# COLUMN STATS
# ---------------------------------------------------------------------------

@router.get("/tables/{table_name}/stats")
async def table_stats(table_name: str):
    """Return basic statistics for each column (count, distinct, nulls, min, max)."""
    engine = get_db_engine()

    inspector = inspect(engine)
    if not inspector.has_table(table_name, schema="vector"):
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    try:
        cols = inspector.get_columns(table_name, schema="vector")
        stats = []

        with engine.connect() as conn:
            total_result = conn.execute(text(f'SELECT COUNT(*) FROM vector."{table_name}"'))
            total_rows = total_result.scalar() or 0

            for col in cols:
                col_type = str(col["type"]).lower()
                if "geometry" in col_type:
                    stats.append({"column": col["name"], "type": col_type, "is_geometry": True})
                    continue

                try:
                    result = conn.execute(text(f"""
                        SELECT
                            COUNT("{col['name']}") AS non_null,
                            COUNT(DISTINCT "{col['name']}") AS distinct_count
                        FROM vector."{table_name}"
                    """))
                    r = result.fetchone()
                    stat = {
                        "column": col["name"],
                        "type": col_type,
                        "non_null": r[0],
                        "null_count": total_rows - r[0],
                        "distinct": r[1],
                    }

                    # Try min/max for numeric and text
                    if any(t in col_type for t in ("int", "float", "double", "numeric", "decimal", "real")):
                        mm = conn.execute(text(f"""
                            SELECT MIN("{col['name']}"), MAX("{col['name']}"), AVG("{col['name']}"::numeric)
                            FROM vector."{table_name}"
                        """)).fetchone()
                        stat["min"] = float(mm[0]) if mm[0] is not None else None
                        stat["max"] = float(mm[1]) if mm[1] is not None else None
                        stat["avg"] = round(float(mm[2]), 4) if mm[2] is not None else None
                    elif "char" in col_type or "text" in col_type:
                        sample = conn.execute(text(f"""
                            SELECT "{col['name']}" FROM vector."{table_name}"
                            WHERE "{col['name']}" IS NOT NULL LIMIT 3
                        """)).fetchall()
                        stat["samples"] = [str(s[0]) for s in sample]

                    stats.append(stat)
                except Exception:
                    stats.append({"column": col["name"], "type": col_type, "error": "Could not compute stats"})

        return {"success": True, "table_name": table_name, "total_rows": total_rows, "columns": stats}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Schema management endpoints
# ---------------------------------------------------------------------------

def _run_schema_refresh():
    """Background task: run full schema re-discovery and cache invalidation."""
    try:
        from app.utils.auto_discovery import AutoTableDiscovery
        from app.utils.schema_discovery import schema_discovery
        from app.utils.deepseek import invalidate_query_cache

        result = AutoTableDiscovery.auto_discover_and_update()
        schema_discovery.refresh_cache()
        invalidate_query_cache()
        logger.info(f"Schema refresh complete: {result}")
    except Exception as e:
        logger.error(f"Schema refresh error: {e}")


@router.post("/schema/refresh")
async def refresh_schema(background_tasks: BackgroundTasks, request: Request):
    """
    Manually trigger a full schema re-discovery and cache invalidation.

    Runs asynchronously in the background. Returns immediately.
    Optionally protected by X-Admin-Token header when SCHEMA_REFRESH_TOKEN env var is set.
    """
    # Optional token guard
    refresh_token = os.getenv("SCHEMA_REFRESH_TOKEN")
    if refresh_token:
        provided = request.headers.get("X-Admin-Token", "")
        if provided != refresh_token:
            raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Token header")

    background_tasks.add_task(_run_schema_refresh)
    return {"success": True, "message": "Schema refresh started in background"}


@router.get("/schema/status")
async def schema_status():
    """
    Return a summary of schema discovery status.

    Returns total_tables, described_tables, and undescribed_tables list.
    Useful for monitoring that all tables have LLM-generated descriptions.
    """
    try:
        engine = get_db_engine()

        # Get all tables in vector schema
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'vector' ORDER BY tablename")
            )
            all_tables = [row[0] for row in result]

        # Get tables that have descriptions in metadata
        described_tables = set()
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT table_name FROM metadata.table_descriptions")
                )
                described_tables = {row[0] for row in result}
        except Exception:
            # metadata schema/table may not exist yet
            pass

        undescribed = [t for t in all_tables if t not in described_tables]

        return {
            "success": True,
            "total_tables": len(all_tables),
            "described_tables": len(all_tables) - len(undescribed),
            "undescribed_tables": undescribed,
        }
    except Exception as e:
        logger.error(f"Schema status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# WFS IMPORT  –  Discover layers and ingest from any OGC WFS endpoint
# ---------------------------------------------------------------------------

class WfsCapabilitiesRequest(BaseModel):
    url: str

class WfsImportRequest(BaseModel):
    url: str
    layer_name: str
    table_name: Optional[str] = None
    max_features: int = 50000


@router.post("/wfs-capabilities")
async def wfs_capabilities(body: WfsCapabilitiesRequest):
    """Fetch GetCapabilities from a WFS URL and return available layers."""
    import httpx
    import xml.etree.ElementTree as ET
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    url = body.url.strip()

    # Build a clean GetCapabilities URL (strip existing SERVICE/REQUEST params if present)
    parsed = urlparse(url)
    base_url = urlunparse(parsed._replace(query=""))
    caps_url = f"{base_url}?SERVICE=WFS&REQUEST=GetCapabilities"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(caps_url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"WFS server error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach WFS server: {str(e)}")

    xml_text = resp.text
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise HTTPException(status_code=502, detail=f"Invalid XML from WFS server: {str(e)}")

    # Detect version from root element
    version = root.attrib.get("version", "")

    # Namespace map – WFS 1.x and 2.0 use different namespace URIs
    ns_candidates = [
        "http://www.opengis.net/wfs/2.0",
        "http://www.opengis.net/wfs",
        "",
    ]

    layers = []

    def _text(el, tag):
        child = el.find(tag)
        return child.text.strip() if child is not None and child.text else ""

    for ns in ns_candidates:
        prefix = f"{{{ns}}}" if ns else ""
        feature_type_list = root.find(f".//{prefix}FeatureTypeList")
        if feature_type_list is None:
            continue
        for ft in feature_type_list.findall(f"{prefix}FeatureType"):
            name = _text(ft, f"{prefix}Name")
            title = _text(ft, f"{prefix}Title")
            abstract = _text(ft, f"{prefix}Abstract")
            if name:
                layers.append({"name": name, "title": title or name, "abstract": abstract})
        if layers:
            break

    if not layers:
        raise HTTPException(status_code=422, detail="No FeatureType layers found in WFS GetCapabilities response.")

    return {"success": True, "layers": layers, "version": version, "total": len(layers)}


@router.post("/wfs-import")
async def wfs_import(body: WfsImportRequest):
    """Download a WFS layer and ingest it into PostGIS."""
    import httpx
    import geopandas as gpd
    import io
    from urllib.parse import urlparse, urlunparse

    url = body.url.strip()
    layer_name = body.layer_name.strip()
    max_features = min(body.max_features, 200_000)  # hard cap

    if not layer_name:
        raise HTTPException(status_code=400, detail="layer_name is required")

    # Derive safe table name
    if body.table_name:
        safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in body.table_name.lower()).strip("_")
    else:
        safe_name = "wfs_" + "".join(c if c.isalnum() else "_" for c in layer_name.lower()).strip("_")

    # Keep within PostgreSQL's 63-char identifier limit
    safe_name = safe_name[:59]
    if not safe_name:
        raise HTTPException(status_code=400, detail="Could not derive a valid table name")

    # Build base URL
    parsed = urlparse(url)
    base_url = urlunparse(parsed._replace(query=""))

    # Try WFS 2.0 (TYPENAMES) then fallback to WFS 1.x (TYPENAME)
    geojson_bytes = None
    last_error = None

    for type_param, version in [("TYPENAMES", "2.0.0"), ("TYPENAME", "1.1.0"), ("TYPENAME", "1.0.0")]:
        request_url = (
            f"{base_url}?SERVICE=WFS&VERSION={version}&REQUEST=GetFeature"
            f"&{type_param}={layer_name}&outputFormat=application%2Fjson"
            f"&srsName=EPSG%3A4326&count={max_features}"
        )
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                resp = await client.get(request_url)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                # Accept if content looks like JSON/GeoJSON
                if "json" in ct or resp.text.strip().startswith("{"):
                    geojson_bytes = resp.content
                    break
                last_error = f"Unexpected content-type: {ct}"
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}"
        except Exception as e:
            last_error = str(e)

    if geojson_bytes is None:
        # Try alternate outputFormat=json (some servers)
        request_url = (
            f"{base_url}?SERVICE=WFS&REQUEST=GetFeature"
            f"&TYPENAMES={layer_name}&outputFormat=json"
            f"&srsName=EPSG%3A4326&count={max_features}"
        )
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                resp = await client.get(request_url)
                resp.raise_for_status()
                if resp.text.strip().startswith("{"):
                    geojson_bytes = resp.content
        except Exception as e:
            last_error = str(e)

    if geojson_bytes is None:
        raise HTTPException(status_code=502, detail=f"Could not download WFS layer. Last error: {last_error}")

    # Parse with GeoPandas
    try:
        gdf = gpd.read_file(io.BytesIO(geojson_bytes))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse WFS response as GeoDataFrame: {str(e)}")

    if gdf.empty:
        raise HTTPException(status_code=422, detail="WFS layer returned no features.")

    # Normalise CRS to EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    elif str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)

    # Sanitise column names (lowercase, replace special chars)
    rename_map = {}
    seen = {}
    for col in gdf.columns:
        if col == "geometry":
            continue
        clean = "".join(c if c.isalnum() else "_" for c in col.lower()).strip("_") or "col"
        if clean in seen:
            seen[clean] += 1
            clean = f"{clean}_{seen[clean]}"
        else:
            seen[clean] = 0
        if clean != col:
            rename_map[col] = clean
    if rename_map:
        gdf = gdf.rename(columns=rename_map)

    has_geometry = "geometry" in gdf.columns
    row_count = len(gdf)
    col_count = len(gdf.columns)

    # Check if there are more features than retrieved
    warning = None
    try:
        geojson_dict = json.loads(geojson_bytes)
        total_matched = geojson_dict.get("numberMatched") or geojson_dict.get("totalFeatures")
        if total_matched and int(total_matched) > row_count:
            warning = f"Only {row_count:,} of {int(total_matched):,} total features retrieved (max_features cap applied)."
    except Exception:
        pass

    engine = get_db_engine()

    # Write to PostGIS
    if has_geometry:
        gdf.to_postgis(safe_name, engine, schema="vector", if_exists="replace", index=False)

        with engine.connect() as conn:
            try:
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom
                    ON vector."{safe_name}" USING GIST(geometry)
                """))
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not create spatial index for {safe_name}: {e}")

        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    ALTER TABLE vector."{safe_name}"
                    ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
                """))
                conn.execute(text(f"""
                    UPDATE vector."{safe_name}"
                    SET geom_25833 = ST_Transform(ST_SetSRID(geometry, 4326), 25833)
                    WHERE geometry IS NOT NULL
                """))
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{safe_name}_geom25833
                    ON vector."{safe_name}" USING GIST(geom_25833)
                """))
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not create geom_25833 for {safe_name}: {e}")
    else:
        gdf.to_sql(safe_name, engine, schema="vector", if_exists="replace", index=False)

    # Register in custom_datasets
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO metadata.custom_datasets
                (table_name, original_filename, file_format, row_count, column_count, has_geometry, uploaded_by)
            VALUES (:tn, :fn, :ff, :rc, :cc, :hg, :ub)
            ON CONFLICT (table_name) DO UPDATE SET
                original_filename = EXCLUDED.original_filename,
                file_format       = EXCLUDED.file_format,
                row_count         = EXCLUDED.row_count,
                column_count      = EXCLUDED.column_count,
                has_geometry      = EXCLUDED.has_geometry,
                uploaded_at       = CURRENT_TIMESTAMP,
                uploaded_by       = EXCLUDED.uploaded_by
        """), {
            "tn": safe_name, "fn": layer_name, "ff": "WFS",
            "rc": row_count, "cc": col_count, "hg": has_geometry, "ub": "wfs_import",
        })
        conn.commit()

    # Upsert table_descriptions
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO metadata.table_descriptions
                (table_name, description, category, source, row_count, updated_by)
            VALUES (:tn, :desc, 'WFS Import', :src, :rc, :ub)
            ON CONFLICT (table_name) DO UPDATE SET
                description = EXCLUDED.description,
                row_count   = EXCLUDED.row_count,
                source      = EXCLUDED.source,
                updated_at  = CURRENT_TIMESTAMP
        """), {
            "tn": safe_name,
            "desc": f"WFS layer '{layer_name}' imported from {url}",
            "src": url,
            "rc": row_count,
            "ub": "wfs_import",
        })
        conn.commit()

    _log_change(engine, safe_name, "wfs_import", {
        "layer_name": layer_name,
        "source_url": url,
        "rows": row_count,
        "columns": col_count,
        "has_geometry": has_geometry,
    }, performed_by="wfs_import")

    result = {
        "success": True,
        "table_name": safe_name,
        "row_count": row_count,
        "column_count": col_count,
        "has_geometry": has_geometry,
        "message": f"Imported {row_count:,} features as vector.{safe_name}",
    }
    if warning:
        result["warning"] = warning
    return result
