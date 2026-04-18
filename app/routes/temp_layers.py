"""
Temporary layer management endpoints.
Creates/drops PostGIS temp tables from user-selected map features
so the agent can spatially query them via execute_sql.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from typing import List, Dict, Any, Optional
import os
import re
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["temp-layers"])


def _get_engine():
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')
    return create_engine(f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}')


def _safe_session_id(session_id: str) -> str:
    """Strip anything that isn't alphanumeric or underscore to prevent SQL injection."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', session_id)[:64]


class CreateTempLayerRequest(BaseModel):
    geometries: List[Dict[str, Any]]
    session_id: str


class DropTempLayerRequest(BaseModel):
    session_id: str


@router.post("/create-temp-layer")
def create_temp_layer(req: CreateTempLayerRequest):
    """
    Insert selected feature geometries into a PostGIS temp table so the
    agent can reference them as temp.temp_selected_{session_id}.
    """
    if not req.geometries:
        raise HTTPException(status_code=400, detail="No geometries provided")

    safe_id = _safe_session_id(req.session_id)
    table_name = f"temp_selected_{safe_id}"

    engine = _get_engine()
    try:
        with engine.begin() as conn:
            # Ensure temp schema exists
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS temp"))

            # Drop and recreate so selections are always fresh
            conn.execute(text(f'DROP TABLE IF EXISTS temp."{table_name}"'))
            conn.execute(text(f"""
                CREATE TABLE temp."{table_name}" (
                    id SERIAL PRIMARY KEY,
                    geom_25833 geometry(Geometry, 25833)
                )
            """))

            inserted = 0
            for geom in req.geometries:
                geom_type = geom.get("type", "")
                if geom_type not in (
                    "Point", "MultiPoint", "LineString", "MultiLineString",
                    "Polygon", "MultiPolygon", "GeometryCollection"
                ):
                    continue
                import json as _json
                geom_json = _json.dumps(geom)
                conn.execute(text(f"""
                    INSERT INTO temp."{table_name}" (geom_25833)
                    SELECT ST_Transform(
                        ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326),
                        25833
                    )
                """), {"geom": geom_json})
                inserted += 1

        logger.info("Created temp layer %s with %d geometries", table_name, inserted)
        return {"schema": "temp", "table_name": table_name, "feature_count": inserted}

    except Exception as e:
        logger.error("create_temp_layer error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drop-temp-layer")
def drop_temp_layer(req: DropTempLayerRequest):
    """Drop the temp PostGIS table for a session."""
    safe_id = _safe_session_id(req.session_id)
    table_name = f"temp_selected_{safe_id}"

    engine = _get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS temp."{table_name}"'))
        logger.info("Dropped temp layer %s", table_name)
        return {"dropped": table_name}
    except Exception as e:
        logger.error("drop_temp_layer error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
