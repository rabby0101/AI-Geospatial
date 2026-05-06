#!/usr/bin/env python3
"""
Import ALKIS ELU (Existing Land Use) GML file into PostGIS database.

This script:
1. Reads the GML file using GeoPandas
2. Transforms coordinates from EPSG:25833 (UTM 33N) to EPSG:4326 (WGS84)
3. Validates and cleans geometries
4. Loads into vector.elu_alkis PostGIS table
5. Creates spatial indexes
6. Updates schema metadata
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from shapely.validation import make_valid
import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.utils.database import DatabaseManager

# Configuration
GML_FILE = project_root / "data/ELU_ALKIS/ELU_ALKIS_2025_04_06.gml"
TABLE_SCHEMA = "vector"
TABLE_NAME = "elu_alkis"
FULL_TABLE_NAME = f"{TABLE_SCHEMA}.{TABLE_NAME}"

# Database configuration from environment or defaults
DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")


def get_db_engine():
    """Create SQLAlchemy engine for database connection."""
    connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(connection_string)


def load_gml_file(gml_path):
    """Load GML file using GeoPandas."""
    logger.info(f"Loading GML file: {gml_path}")

    if not gml_path.exists():
        raise FileNotFoundError(f"GML file not found: {gml_path}")

    try:
        # GeoPandas can read GML files directly
        gdf = gpd.read_file(str(gml_path))
        logger.info(f"✓ Loaded {len(gdf)} features from GML")
        logger.info(f"  CRS: {gdf.crs}")
        logger.info(f"  Columns: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        logger.error(f"Failed to load GML file: {e}")
        raise


def validate_geometries(gdf):
    """Validate and fix invalid geometries."""
    logger.info("Validating geometries...")

    # Check for null geometries
    null_geoms = gdf.geometry.isna().sum()
    if null_geoms > 0:
        logger.warning(f"Found {null_geoms} null geometries, removing them")
        gdf = gdf[gdf.geometry.notna()].copy()

    # Fix invalid geometries
    invalid_mask = ~gdf.geometry.is_valid
    if invalid_mask.sum() > 0:
        logger.warning(f"Found {invalid_mask.sum()} invalid geometries, attempting to fix...")
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

    logger.info(f"✓ Geometry validation complete. Valid features: {len(gdf)}")
    return gdf


def transform_to_wgs84(gdf):
    """Transform from EPSG:25833 (UTM 33N) to EPSG:4326 (WGS84)."""
    logger.info(f"Current CRS: {gdf.crs}")

    if gdf.crs is None:
        logger.warning("No CRS detected in GML file, assuming EPSG:25833 (UTM Zone 33N)")
        gdf = gdf.set_crs("EPSG:25833")

    if gdf.crs != "EPSG:4326":
        logger.info("Transforming to EPSG:4326 (WGS84)...")
        gdf = gdf.to_crs("EPSG:4326")
        logger.info(f"✓ Transformed to {gdf.crs}")

    return gdf


def prepare_data_for_postgis(gdf):
    """Prepare GeoDataFrame for PostGIS import."""
    logger.info("Preparing data for PostGIS...")

    # Create a copy to avoid modifying original
    gdf = gdf.copy()

    # Simplify column names (lowercase, replace special characters)
    gdf.columns = [
        col.lower().replace(':', '_').replace('-', '_').replace(' ', '_')
        for col in gdf.columns
    ]

    logger.info(f"Column names after normalization: {list(gdf.columns)}")

    # Handle large text fields that might cause issues
    for col in gdf.columns:
        if gdf[col].dtype == 'object':
            # Truncate very long strings to 1000 chars
            gdf[col] = gdf[col].astype(str).str[:1000]

    logger.info(f"✓ Data prepared: {len(gdf)} features")
    return gdf


def drop_existing_table(engine):
    """Drop existing table if it exists."""
    try:
        with engine.connect() as conn:
            # Check if table exists
            inspector = inspect(engine)
            tables = inspector.get_table_names(schema=TABLE_SCHEMA)

            if TABLE_NAME in tables:
                logger.info(f"Dropping existing table {FULL_TABLE_NAME}...")
                conn.execute(text(f"DROP TABLE IF EXISTS {FULL_TABLE_NAME} CASCADE"))
                conn.commit()
                logger.info("✓ Existing table dropped")
    except Exception as e:
        logger.error(f"Error dropping table: {e}")
        raise


def load_to_postgis(gdf, engine):
    """Load GeoDataFrame into PostGIS."""
    logger.info(f"Loading data into {FULL_TABLE_NAME}...")

    try:
        # GeoPandas to_postgis with create option
        gdf.to_postgis(
            name=TABLE_NAME,
            con=engine,
            schema=TABLE_SCHEMA,
            if_exists='append',  # append since we dropped the table
            index=False,
            chunksize=1000  # Process in chunks for large files
        )
        logger.info("✓ Data loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise


def create_spatial_indexes(engine):
    """Create spatial indexes on the geometry column."""
    logger.info("Creating spatial indexes...")

    try:
        with engine.connect() as conn:
            # Create GiST spatial index for performance
            index_name = f"{TABLE_NAME}_geometry_idx"
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {FULL_TABLE_NAME}
                USING GIST (geometry)
            """))

            # Create index on HILUCS code if it exists
            if 'hilucs' in [col.lower() for col in conn.execute(
                text(f"SELECT column_name FROM information_schema.columns WHERE table_schema='{TABLE_SCHEMA}' AND table_name='{TABLE_NAME}'")
            ).scalars()]:
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS {TABLE_NAME}_hilucs_idx
                    ON {FULL_TABLE_NAME} (hilucs)
                """))

            conn.commit()
            logger.info("✓ Spatial indexes created")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")


def get_table_summary(engine):
    """Get summary statistics about the loaded table."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT
                    COUNT(*) as feature_count,
                    ST_AsText(ST_Envelope(ST_Union(geometry))) as bounds,
                    ST_Area(ST_Union(geometry)) as total_area_sq_degrees
                FROM {FULL_TABLE_NAME}
            """)).first()

            if result:
                feature_count, bounds, area = result
                return {
                    'feature_count': feature_count,
                    'bounds': bounds,
                    'total_area': area
                }
    except Exception as e:
        logger.warning(f"Could not get summary: {e}")

    return {}


def update_schema_metadata(gdf):
    """Update schema metadata files."""
    logger.info("Updating schema metadata...")

    metadata_dir = project_root / "data/metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Get column info
    columns_info = {}
    for col in gdf.columns:
        if col != 'geometry':
            columns_info[col] = {
                'type': str(gdf[col].dtype),
                'description': col.replace('_', ' ').title()
            }

    # Update schema cache
    schema_cache_file = metadata_dir / "schema_cache.json"
    schema_cache = {}

    if schema_cache_file.exists():
        with open(schema_cache_file) as f:
            schema_cache = json.load(f)

    schema_cache[FULL_TABLE_NAME] = {
        'columns': columns_info,
        'geometry_type': 'Polygon',
        'crs': 'EPSG:4326',
        'feature_count': len(gdf),
        'last_updated': datetime.now().isoformat()
    }

    with open(schema_cache_file, 'w') as f:
        json.dump(schema_cache, f, indent=2)

    # Update table descriptions
    descriptions_file = metadata_dir / "table_descriptions.json"
    descriptions = {}

    if descriptions_file.exists():
        with open(descriptions_file) as f:
            descriptions = json.load(f)

    descriptions[FULL_TABLE_NAME] = {
        'name': 'Berlin Land Use Areas (ALKIS INSPIRE)',
        'description': 'Existing Land Use (ELU) data from German ALKIS cadastral system for Berlin. Contains polygon boundaries of land use zones with HILUCS classifications (hierarchical INSPIRE land cover/use classification system).',
        'source': 'GDI-DE (German Spatial Data Infrastructure) / ALKIS',
        'date': '2025-04-06',
        'geometry_type': 'Polygon',
        'crs': 'EPSG:4326'
    }

    with open(descriptions_file, 'w') as f:
        json.dump(descriptions, f, indent=2)

    logger.info("✓ Schema metadata updated")


def main():
    """Main import workflow."""
    try:
        logger.info("=" * 70)
        logger.info("ALKIS ELU GML Import to PostGIS")
        logger.info("=" * 70)

        # Load GML file
        gdf = load_gml_file(GML_FILE)

        # Transform coordinates
        gdf = transform_to_wgs84(gdf)

        # Validate geometries
        gdf = validate_geometries(gdf)

        # Prepare data
        gdf = prepare_data_for_postgis(gdf)

        # Create database engine
        engine = get_db_engine()
        logger.info("✓ Database connection established")

        # Drop existing table if it exists
        drop_existing_table(engine)

        # Load to PostGIS
        load_to_postgis(gdf, engine)

        # Create indexes
        create_spatial_indexes(engine)

        # Get summary
        summary = get_table_summary(engine)

        # Update metadata
        update_schema_metadata(gdf)

        logger.info("=" * 70)
        logger.info("✓ Import completed successfully!")
        logger.info("=" * 70)
        logger.info(f"Table: {FULL_TABLE_NAME}")
        logger.info(f"Features: {summary.get('feature_count', len(gdf))}")
        logger.info(f"CRS: EPSG:4326 (WGS84)")
        logger.info(f"Data is ready for spatial queries")
        logger.info("=" * 70)

        return 0

    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
