#!/usr/bin/env python3
"""
Load Wasserschutzgebiete (Water Protection Areas) data into PostGIS
"""

import sys
import os
import logging
import geopandas as gpd
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_USER = os.getenv('POSTGRES_USER', 'geoassist')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
DB_HOST = os.getenv('POSTGRES_HOST', 'localhost')
DB_PORT = os.getenv('POSTGRES_PORT', '5433')
DB_NAME = os.getenv('POSTGRES_DB', 'geoassist')

# Database connection string
DB_CONNECTION_STRING = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Table configuration
SCHEMA = 'vector'
TABLE_NAME = 'wasserschutzgebiete'
FULL_TABLE_NAME = f'{SCHEMA}.{TABLE_NAME}'


def create_schema(engine):
    """Create the vector schema if it doesn't exist"""
    print(f"Creating schema '{SCHEMA}' if not exists...", end="", flush=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        print(" ✅")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error creating schema: {e}")
        return False


def load_geojson(filepath):
    """Load GeoJSON file using geopandas"""
    print(f"Loading GeoJSON from {filepath}...", end="", flush=True)
    try:
        gdf = gpd.read_file(filepath)
        print(f" ✅")
        print(f"  Records: {len(gdf):,}")
        print(f"  CRS: {gdf.crs}")
        print(f"  Geometry types: {gdf.geometry.type.unique().tolist()}")
        return gdf
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error loading GeoJSON: {e}")
        return None


def upload_to_postgis(gdf, engine):
    """Upload GeoDataFrame to PostGIS"""
    print(f"Uploading to {FULL_TABLE_NAME}...", end="", flush=True)
    try:
        # Ensure CRS is EPSG:4326
        if gdf.crs is None:
            gdf.crs = 'EPSG:4326'
        elif gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')

        # Write to database
        gdf.to_postgis(
            TABLE_NAME,
            engine,
            schema=SCHEMA,
            if_exists='replace',  # Replace if exists
            index=False,
            chunksize=1000
        )
        print(f" ✅")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error uploading to PostGIS: {e}")
        return False


def create_spatial_index(engine):
    """Create spatial index on geometry column"""
    print(f"Creating spatial index...", end="", flush=True)
    try:
        with engine.begin() as conn:
            # Create GiST spatial index
            conn.execute(text(f"CREATE INDEX idx_{TABLE_NAME}_geom ON {FULL_TABLE_NAME} USING GIST(geometry)"))
        print(f" ✅")
        return True
    except Exception as e:
        print(f" ⚠️  (may already exist)")
        logger.debug(f"Spatial index creation: {e}")
        return True


def verify_data(engine):
    """Verify data was loaded correctly"""
    print(f"\nVerifying data...", end="", flush=True)
    try:
        gdf = gpd.read_postgis(
            f"SELECT * FROM {FULL_TABLE_NAME} LIMIT 5",
            engine
        )
        print(f" ✅")
        print(f"\n{'=' * 80}")
        print("SAMPLE DATA")
        print(f"{'=' * 80}")
        print(f"\nColumns: {list(gdf.columns)}")
        print(f"Shape: {gdf.shape}")
        print(f"CRS: {gdf.crs}")
        print(f"\nFirst record:")
        for col in gdf.columns:
            val = gdf.iloc[0][col]
            if col != 'geometry':
                print(f"  {col}: {val}")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error verifying data: {e}")
        return False


def get_table_statistics(engine):
    """Get statistics about the loaded table"""
    print(f"\nGetting table statistics...", end="", flush=True)
    try:
        with engine.connect() as conn:
            # Get feature count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {FULL_TABLE_NAME}"))
            count = result.scalar()

            # Get bounds
            result = conn.execute(text(f"""
                SELECT
                    ST_XMin(geom_bound) as min_lon,
                    ST_YMin(geom_bound) as min_lat,
                    ST_XMax(geom_bound) as max_lon,
                    ST_YMax(geom_bound) as max_lat
                FROM (
                    SELECT ST_Extent(geometry) as geom_bound FROM {FULL_TABLE_NAME}
                ) bounds
            """))
            bounds = result.fetchone()

        print(f" ✅")
        print(f"\n{'=' * 80}")
        print("TABLE STATISTICS")
        print(f"{'=' * 80}")
        print(f"\nTotal features: {count:,}")
        if bounds:
            print(f"Geographic bounds:")
            print(f"  Longitude: {bounds[0]:.4f} to {bounds[2]:.4f}")
            print(f"  Latitude: {bounds[1]:.4f} to {bounds[3]:.4f}")
        return True
    except Exception as e:
        print(f" ⚠️")
        logger.debug(f"Error getting statistics: {e}")
        return True


def main():
    """Main function"""
    print("=" * 80)
    print("LOADING WASSERSCHUTZGEBIETE DATA INTO POSTGIS")
    print("=" * 80)
    print(f"\nDatabase: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"Schema: {SCHEMA}")
    print(f"Table: {TABLE_NAME}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Find input file
    project_root = Path(__file__).parent.parent
    input_file = project_root / "data/vector/wfs/berlin_wasserschutzgebiete.geojson"

    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        print(f"\nFirst run: python scripts/download_wasserschutzgebiete.py")
        return False

    # Load GeoJSON
    gdf = load_geojson(input_file)
    if gdf is None:
        return False

    # Connect to database
    print(f"\nConnecting to database...", end="", flush=True)
    try:
        engine = create_engine(DB_CONNECTION_STRING)
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
        print(f" ✅")
        print(f"  {version[:50]}...")
    except Exception as e:
        print(f" ❌")
        logger.error(f"Database connection failed: {e}")
        return False

    # Create schema
    if not create_schema(engine):
        return False

    # Upload to PostGIS
    if not upload_to_postgis(gdf, engine):
        return False

    # Create spatial index
    if not create_spatial_index(engine):
        return False

    # Verify data
    if not verify_data(engine):
        logger.warning("Data verification had issues but upload may have succeeded")

    # Get statistics
    if not get_table_statistics(engine):
        logger.warning("Could not retrieve statistics")

    print(f"\n{'=' * 80}")
    print("✅ WASSERSCHUTZGEBIETE DATA SUCCESSFULLY LOADED")
    print(f"{'=' * 80}")
    print(f"\nYou can now query this table in your application:")
    print(f"  - Table: {FULL_TABLE_NAME}")
    print(f"  - API endpoint: /api/query")
    print(f"  - Example query: 'Show water protection areas near Mitte'")
    print()

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Loading interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
