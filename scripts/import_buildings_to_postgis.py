#!/usr/bin/env python3
"""
Import buildings from GeoJSON to PostGIS.
Replaces the current osm_buildings table with OverpassAPI data.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import geopandas as gpd
from sqlalchemy import create_engine, text
import time

load_dotenv()

# Configuration
INPUT_FILE = Path("data/buildings_overpass_raw.geojson")
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")
SCHEMA = "vector"
TABLE = "osm_buildings"

if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)


def verify_input_file():
    """Verify input GeoJSON file exists and is valid."""
    print("\n📂 Verifying input file...")
    if not INPUT_FILE.exists():
        print(f"❌ File not found: {INPUT_FILE}")
        print(f"   Run: python scripts/download_buildings_overpass_grid.py")
        return False

    print(f"   ✅ File exists: {INPUT_FILE}")

    try:
        gdf = gpd.read_file(INPUT_FILE)
        print(f"   ✅ Loaded {len(gdf):,} features")
        print(f"   ✅ Geometry types: {gdf.geometry.type.unique().tolist()}")
        return True
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return False


def truncate_current_table():
    """Drop current osm_buildings table if it exists."""
    print("\n🗑️  Truncating current table...")
    with engine.connect() as conn:
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.{TABLE} CASCADE"))
            conn.commit()
            print(f"   ✅ Dropped {SCHEMA}.{TABLE}")
        except Exception as e:
            print(f"❌ Error: {e}")
            conn.rollback()
            return False

    return True


def load_and_prepare_data():
    """Load GeoJSON and prepare for import."""
    print("\n📥 Loading GeoJSON...")
    try:
        gdf = gpd.read_file(INPUT_FILE)
        print(f"   ✅ Loaded {len(gdf):,} features")

        # Ensure EPSG:4326
        if gdf.crs != "EPSG:4326":
            print(f"   🔄 Converting CRS to EPSG:4326...")
            gdf = gdf.to_crs("EPSG:4326")

        # Remove rows with invalid or None geometry
        print(f"   🔍 Cleaning invalid geometries...")
        gdf = gdf[gdf.geometry.notna()]
        gdf = gdf[gdf.geometry.is_valid]
        print(f"   ✅ After cleanup: {len(gdf):,} features")

        # Standardize columns
        gdf = gdf.rename(columns=lambda x: x.lower())

        return gdf

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def import_to_postgis(gdf):
    """Import GeoDataFrame to PostGIS."""
    print(f"\n📤 Importing to PostGIS ({SCHEMA}.{TABLE})...")

    try:
        start = time.time()

        # Use to_postgis with optimized parameters
        gdf.to_postgis(
            TABLE,
            engine,
            schema=SCHEMA,
            if_exists="replace",
            index=False,
            chunksize=500,  # Process in batches
            method="multi"  # Use multi-row insert
        )

        import_time = time.time() - start
        print(f"   ✅ Import successful in {import_time:.2f}s")
        print(f"   📊 Rate: {len(gdf)/import_time:.0f} features/second")

        return True

    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_spatial_index():
    """Create GiST spatial index on geometry column."""
    print("\n🔍 Creating spatial index...")
    with engine.connect() as conn:
        try:
            conn.execute(text(f"""
                CREATE INDEX idx_{TABLE}_geom
                ON {SCHEMA}.{TABLE} USING GIST(geometry)
            """))
            conn.commit()
            print(f"   ✅ Index created: idx_{TABLE}_geom")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            conn.rollback()
            return False


def verify_import():
    """Verify the import was successful."""
    print("\n✅ VERIFYING IMPORT")
    print("="*80)

    with engine.connect() as conn:
        try:
            # Count features
            count = conn.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{TABLE}")).scalar()
            print(f"✅ Total features: {count:,}")

            # Show geometry types
            result = conn.execute(text(f"""
                SELECT ST_GeometryType(geometry) as geom_type, COUNT(*) as count
                FROM {SCHEMA}.{TABLE}
                GROUP BY ST_GeometryType(geometry)
                ORDER BY count DESC
            """))
            print(f"\n✅ Geometry types:")
            for geom_type, geom_count in result:
                print(f"   {geom_type}: {geom_count:,}")

            # Show sample buildings
            result = conn.execute(text(f"""
                SELECT * FROM {SCHEMA}.{TABLE}
                WHERE building IS NOT NULL
                LIMIT 5
            """))
            rows = result.fetchall()
            print(f"\n✅ Sample buildings:")
            for row in rows:
                print(f"   {dict(row)}")

            # Check schema
            result = conn.execute(text(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='{SCHEMA}' AND table_name='{TABLE}'
                ORDER BY ordinal_position
                LIMIT 10
            """))
            print(f"\n✅ Table schema (first 10 columns):")
            for col_name, data_type in result:
                print(f"   {col_name}: {data_type}")

            return True

        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False


def main():
    """Main execution flow."""
    print("\n" + "="*80)
    print("IMPORT BUILDINGS TO POSTGIS")
    print("="*80)

    # Step 1: Verify input
    if not verify_input_file():
        return False

    # Step 2: Load and prepare data
    gdf = load_and_prepare_data()
    if gdf is None:
        return False

    # Step 3: Truncate current table
    if not truncate_current_table():
        return False

    # Step 4: Import to PostGIS
    if not import_to_postgis(gdf):
        return False

    # Step 5: Create spatial index
    if not create_spatial_index():
        return False

    # Step 6: Verify import
    if not verify_import():
        return False

    print("\n" + "="*80)
    print("✅ IMPORT COMPLETE!")
    print("="*80)
    print(f"\n📍 Table: {SCHEMA}.{TABLE}")
    print(f"📊 Features: {len(gdf):,}")
    print(f"🔍 Index: idx_{TABLE}_geom")
    print(f"\nNext step: Restart FastAPI server and test queries!")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
