#!/usr/bin/env python3
"""
Ingest Berlin street lights data from GeoJSON into PostGIS database.

This script:
1. Reads the Berlin street lights GeoJSON file from WFS service
2. Converts MultiPoint geometries to Point geometries
3. Ensures WGS84 coordinate system (EPSG:4326)
4. Loads into PostGIS vector.osm_street_lights table
5. Creates spatial index for efficient queries

Data Source: Berlin GDI WFS Service (https://gdi.berlin.de/services/wfs/beleuchtung)
"""

import sys
import os
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import geopandas as gpd
    from shapely.geometry import Point
    import pandas as pd
    from sqlalchemy import text
    from app.utils.database import DatabaseManager
except ImportError as e:
    logger.error(f"Failed to import required packages: {e}")
    logger.error("Install with: pip install geopandas shapely pandas sqlalchemy psycopg2-binary")
    sys.exit(1)


def convert_multipoint_to_point(geom):
    """Convert MultiPoint geometry to Point (use first coordinate)."""
    if geom.geom_type == 'MultiPoint':
        if len(geom.geoms) > 0:
            return Point(geom.geoms[0])
        return None
    return geom


def ingest_street_lights():
    """Main ingestion function."""

    # Paths
    geojson_path = project_root / "data" / "vector" / "wfs" / "berlin_street_lights.geojson"

    if not geojson_path.exists():
        logger.error(f"GeoJSON file not found: {geojson_path}")
        sys.exit(1)

    logger.info(f"Reading GeoJSON from: {geojson_path}")

    # Read GeoJSON
    try:
        gdf = gpd.read_file(geojson_path)
        logger.info(f"Loaded {len(gdf)} features from GeoJSON")
    except Exception as e:
        logger.error(f"Failed to read GeoJSON: {e}")
        sys.exit(1)

    # Verify CRS is WGS84
    # Note: The GeoJSON file has incorrect CRS metadata (EPSG:25833) but coordinates are already in WGS84
    if gdf.crs is None:
        logger.warning("CRS not specified, assuming EPSG:4326 (WGS84)")
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        # Check if coordinates look like WGS84 (decimal degrees between -180/180 and -90/90)
        bounds = gdf.total_bounds
        if -180 <= bounds[0] <= 180 and -90 <= bounds[1] <= 90:
            logger.info(f"CRS metadata says {gdf.crs}, but coordinates are already WGS84")
            logger.info("Setting CRS to EPSG:4326 (no conversion needed)")
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
        else:
            logger.info(f"Converting from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")

    # Convert MultiPoint to Point
    original_count = len(gdf)
    gdf['geometry'] = gdf['geometry'].apply(convert_multipoint_to_point)
    gdf = gdf.dropna(subset=['geometry'])
    logger.info(f"Converted geometries: {original_count} -> {len(gdf)} features")

    # Validate geometries
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        logger.warning(f"Found {invalid.sum()} invalid geometries, attempting to fix...")
        gdf.loc[invalid, 'geometry'] = gdf.loc[invalid, 'geometry'].buffer(0)
        still_invalid = ~gdf.geometry.is_valid
        if still_invalid.any():
            logger.warning(f"Removing {still_invalid.sum()} geometries that couldn't be fixed")
            gdf = gdf[~still_invalid]

    logger.info(f"Final dataset: {len(gdf)} valid features")

    # Display sample attributes
    logger.info("Dataset attributes:")
    for col in gdf.columns:
        if col != 'geometry':
            sample_val = gdf[col].iloc[0] if len(gdf) > 0 else None
            logger.info(f"  - {col}: {type(sample_val).__name__}")

    # Connect to database
    logger.info("Connecting to PostGIS database...")
    try:
        db_manager = DatabaseManager()
        db_manager.initialize()  # Initialize the engine
        engine = db_manager.engine
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        logger.error("Ensure PostgreSQL/PostGIS is running and .env credentials are correct")
        sys.exit(1)

    # Check if table exists
    table_name = 'osm_street_lights'
    schema = 'vector'

    try:
        # Load to database
        logger.info(f"Writing to {schema}.{table_name} (replacing existing table)...")
        gdf.to_postgis(
            table_name,
            engine,
            schema=schema,
            if_exists='replace',  # Replace existing table
            index=False,
            chunksize=5000  # Process in chunks for large datasets
        )
        logger.info(f"Successfully loaded {len(gdf)} features to {schema}.{table_name}")

        # Create spatial index
        logger.info("Creating GiST spatial index...")
        with engine.connect() as conn:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom "
                f"ON {schema}.{table_name} USING GIST(geometry)"
            ))
            conn.commit()
            logger.info("Spatial index created successfully")

        # Display summary
        logger.info("\n" + "="*60)
        logger.info("INGESTION COMPLETE")
        logger.info("="*60)
        logger.info(f"Table: {schema}.{table_name}")
        logger.info(f"Features: {len(gdf)}")
        logger.info(f"CRS: EPSG:{gdf.crs.to_epsg()}")
        logger.info(f"Geometry type: {gdf.geometry.geom_type.unique()}")
        logger.info(f"Bounds: {gdf.total_bounds}")
        logger.info("\nAttributes available:")
        for col in sorted(gdf.columns):
            if col != 'geometry':
                dtype = gdf[col].dtype
                non_null = gdf[col].notna().sum()
                logger.info(f"  {col}: {dtype} ({non_null}/{len(gdf)} non-null)")

        logger.info("\n✓ Data is ready for querying!")
        logger.info("✓ Auto-discovery will register this table on app startup")
        logger.info(f"✓ Try querying: 'Show all street lights' or 'Street lights near parks'")

    except Exception as e:
        logger.error(f"Failed to load data to database: {e}")
        logger.error("Verify PostGIS extension is enabled: CREATE EXTENSION postgis;")
        sys.exit(1)


if __name__ == "__main__":
    ingest_street_lights()
