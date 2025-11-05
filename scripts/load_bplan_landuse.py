#!/usr/bin/env python3
"""
Load Bauleitplanung (Building Plans/Land Use) data into PostGIS
"""

import sys
import os
import logging
import geopandas as gpd
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, text
import glob

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
TABLE_MAPPINGS = {
    'berlin_bplan_spatialplan': 'bplan_spatial_plan',
    'berlin_bplan_officialdocumentation': 'bplan_official_docs'
}


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
    print(f"Loading GeoJSON from {filepath.name}...", end="", flush=True)
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


def upload_to_postgis(gdf, engine, table_name):
    """Upload GeoDataFrame to PostGIS"""
    full_table_name = f"{SCHEMA}.{table_name}"
    print(f"Uploading to {full_table_name}...", end="", flush=True)
    try:
        # Ensure CRS is EPSG:4326
        if gdf.crs is None:
            gdf.crs = 'EPSG:4326'
        elif gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')

        # Write to database
        gdf.to_postgis(
            table_name,
            engine,
            schema=SCHEMA,
            if_exists='replace',  # Replace if exists
            index=False,
            chunksize=500
        )
        print(f" ✅")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error uploading to PostGIS: {e}")
        return False


def create_spatial_index(engine, table_name):
    """Create spatial index on geometry column"""
    full_table_name = f"{SCHEMA}.{table_name}"
    index_name = f"idx_{table_name}_geom"
    print(f"Creating spatial index...", end="", flush=True)
    try:
        with engine.begin() as conn:
            # Create GiST spatial index
            conn.execute(text(f"CREATE INDEX {index_name} ON {full_table_name} USING GIST(geometry)"))
        print(f" ✅")
        return True
    except Exception as e:
        print(f" ⚠️  (may already exist)")
        logger.debug(f"Spatial index creation: {e}")
        return True


def get_table_statistics(engine, table_name):
    """Get statistics about the loaded table"""
    full_table_name = f"{SCHEMA}.{table_name}"
    try:
        with engine.connect() as conn:
            # Get feature count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table_name}"))
            count = result.scalar()

            # Get bounds
            result = conn.execute(text(f"""
                SELECT
                    ST_XMin(geom_bound) as min_lon,
                    ST_YMin(geom_bound) as min_lat,
                    ST_XMax(geom_bound) as max_lon,
                    ST_YMax(geom_bound) as max_lat
                FROM (
                    SELECT ST_Extent(geometry) as geom_bound FROM {full_table_name}
                ) bounds
            """))
            bounds = result.fetchone()

        print(f"  Total features: {count:,}")
        if bounds:
            print(f"  Geographic bounds:")
            print(f"    Longitude: {bounds[0]:.4f} to {bounds[2]:.4f}")
            print(f"    Latitude: {bounds[1]:.4f} to {bounds[3]:.4f}")
        return True
    except Exception as e:
        logger.debug(f"Error getting statistics: {e}")
        return True


def main():
    """Main function"""
    print("=" * 80)
    print("LOADING BAULEITPLANUNG (BUILDING PLANS) DATA INTO POSTGIS")
    print("=" * 80)
    print(f"\nDatabase: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"Schema: {SCHEMA}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Find input files
    project_root = Path(__file__).parent.parent
    input_dir = project_root / "data/vector/wfs"

    # Find all bplan GeoJSON files
    input_files = glob.glob(str(input_dir / "berlin_bplan_*.geojson"))

    if not input_files:
        print(f"❌ No input files found in {input_dir}")
        print(f"\nFirst run: python scripts/download_bplan_landuse.py")
        return False

    print(f"Found {len(input_files)} files to load\n")

    # Connect to database
    print(f"Connecting to database...", end="", flush=True)
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

    print()

    # Load all files
    total_features = 0
    loaded_tables = []

    for input_file in sorted(input_files):
        filepath = Path(input_file)
        filename = filepath.stem

        # Get table name from mapping
        table_name = TABLE_MAPPINGS.get(filename, filename.replace('berlin_bplan_', 'bplan_'))

        print(f"\n{'='*80}")
        print(f"Processing: {filename}")
        print(f"{'='*80}")

        # Load GeoJSON
        gdf = load_geojson(filepath)
        if gdf is None:
            print(f"  ⚠️  Skipping {filename}")
            continue

        # Show columns
        print(f"  Columns: {len(gdf.columns)}")

        # Upload to PostGIS
        if not upload_to_postgis(gdf, engine, table_name):
            continue

        # Create spatial index
        if not create_spatial_index(engine, table_name):
            continue

        # Get statistics
        get_table_statistics(engine, table_name)

        total_features += len(gdf)
        loaded_tables.append(f"{SCHEMA}.{table_name}")

    print(f"\n{'=' * 80}")
    print("✅ BAULEITPLANUNG DATA SUCCESSFULLY LOADED")
    print(f"{'=' * 80}")
    print(f"\nLoaded {len(loaded_tables)} tables:")
    for table in loaded_tables:
        print(f"  - {table}")

    print(f"\nTotal features: {total_features:,}")

    print(f"\nYou can now query these tables in your application:")
    print(f"  - API endpoint: /api/query")
    print(f"  - Example queries:")
    print(f"    'Show building plans in Mitte'")
    print(f"    'Display spatial plans for residential areas'")
    print(f"    'Which zoning plans are near hospitals?'")
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
