#!/usr/bin/env python3
"""
Extract buildings from OSM PBF file and import to PostGIS.
Uses ogr2ogr CLI for efficient PBF processing.
"""

import os
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import geopandas as gpd

load_dotenv()

# Configuration
PBF_FILE = Path("data/berlin-latest.osm.pbf")
GEOJSON_FILE = Path("data/berlin_buildings.geojson")
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


def check_pbf_file():
    """Check if PBF file exists and is valid."""
    print("\n📂 Checking PBF file...")

    if not PBF_FILE.exists():
        print(f"❌ PBF file not found: {PBF_FILE}")
        print(f"   Waiting for download to complete...")
        return False

    size_mb = PBF_FILE.stat().st_size / (1024 * 1024)
    print(f"   ✅ Found {PBF_FILE}")
    print(f"   📊 Size: {size_mb:.1f} MB")

    if size_mb < 50:
        print(f"   ⚠️  File seems small (< 50MB), may still be downloading")
        return False

    return True


def extract_buildings_with_ogr2ogr():
    """Extract buildings from PBF using ogr2ogr."""
    print("\n🔨 Extracting buildings from PBF using ogr2ogr...")

    # ogr2ogr command to extract buildings from PBF
    # Key flags:
    # -f GeoJSON: output format
    # -where: SQL WHERE clause to filter for buildings
    # -t_srs EPSG:4326: target CRS
    # buildings: layer name in OSM PBF

    cmd = [
        "ogr2ogr",
        "-f", "GeoJSON",
        "-t_srs", "EPSG:4326",
        "-where", "building IS NOT NULL",
        str(GEOJSON_FILE),
        str(PBF_FILE),
        "buildings"
    ]

    print(f"   Running: {' '.join(cmd)}")

    try:
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = time.time() - start

        if result.returncode == 0:
            print(f"   ✅ Extraction successful in {elapsed:.1f}s")

            if GEOJSON_FILE.exists():
                size_mb = GEOJSON_FILE.stat().st_size / (1024 * 1024)
                print(f"   📊 Output size: {size_mb:.1f} MB")

            return True
        else:
            print(f"   ❌ ogr2ogr failed with code {result.returncode}")
            print(f"   STDERR: {result.stderr[:500]}")
            return False

    except subprocess.TimeoutExpired:
        print(f"   ❌ Extraction timeout (> 10 minutes)")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def load_and_import_buildings():
    """Load GeoJSON and import to PostGIS."""
    print("\n📥 Loading and importing buildings to PostGIS...")

    if not GEOJSON_FILE.exists():
        print(f"   ❌ GeoJSON file not found: {GEOJSON_FILE}")
        return False

    try:
        # Load GeoJSON
        print(f"   📂 Loading {GEOJSON_FILE}...")
        gdf = gpd.read_file(GEOJSON_FILE)
        print(f"   ✅ Loaded {len(gdf):,} features")

        # Ensure EPSG:4326
        if gdf.crs != "EPSG:4326":
            print(f"   🔄 Converting CRS to EPSG:4326...")
            gdf = gdf.to_crs("EPSG:4326")

        # Clean geometries
        print(f"   🔍 Cleaning invalid geometries...")
        gdf = gdf[gdf.geometry.notna()]
        gdf = gdf[gdf.geometry.is_valid]
        print(f"   ✅ After cleanup: {len(gdf):,} features")

        # Standardize columns
        gdf = gdf.rename(columns=lambda x: x.lower())

        # Drop current table
        print(f"   🗑️  Dropping existing table...")
        with engine.connect() as conn:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.{TABLE} CASCADE"))
                conn.commit()
                print(f"   ✅ Dropped {SCHEMA}.{TABLE}")
            except Exception as e:
                print(f"   ⚠️  {e}")

        # Import to PostGIS
        print(f"   📤 Importing {len(gdf):,} features to PostGIS...")
        start = time.time()

        gdf.to_postgis(
            TABLE,
            engine,
            schema=SCHEMA,
            if_exists="replace",
            index=False,
            chunksize=1000,
            method="multi"
        )

        elapsed = time.time() - start
        rate = len(gdf) / elapsed if elapsed > 0 else 0
        print(f"   ✅ Import successful in {elapsed:.1f}s ({rate:.0f} features/sec)")

        # Create spatial index
        print(f"   🔍 Creating spatial index...")
        with engine.connect() as conn:
            try:
                conn.execute(text(f"""
                    CREATE INDEX idx_{TABLE}_geom
                    ON {SCHEMA}.{TABLE} USING GIST(geometry)
                """))
                conn.commit()
                print(f"   ✅ Index created: idx_{TABLE}_geom")
            except Exception as e:
                print(f"   ⚠️  {e}")

        return True

    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_import():
    """Verify the import was successful."""
    print("\n✅ VERIFYING IMPORT")
    print("="*80)

    with engine.connect() as conn:
        try:
            # Count features
            result = conn.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{TABLE}"))
            count = result.scalar()
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

            # Top building types
            result = conn.execute(text(f"""
                SELECT building, COUNT(*) as count
                FROM {SCHEMA}.{TABLE}
                WHERE building IS NOT NULL
                GROUP BY building
                ORDER BY count DESC
                LIMIT 5
            """))
            print(f"\n✅ Top 5 building types:")
            for building_type, cnt in result:
                print(f"   {building_type}: {cnt:,}")

            return True

        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False


def main():
    """Main execution flow."""
    print("\n" + "="*80)
    print("EXTRACT BUILDINGS FROM OSM PBF")
    print("="*80)

    # Check if PBF file exists and is complete
    if not check_pbf_file():
        print("\n⏳ Waiting for PBF download to complete...")
        print("   Please run this script again in a few minutes.")
        return False

    # Extract buildings using ogr2ogr
    if not extract_buildings_with_ogr2ogr():
        print("\n❌ Building extraction failed")
        return False

    # Load and import to PostGIS
    if not load_and_import_buildings():
        print("\n❌ Import to PostGIS failed")
        return False

    # Verify
    if not verify_import():
        print("\n⚠️  Import completed but verification had issues")
        return False

    print("\n" + "="*80)
    print("✅ COMPLETE! Buildings successfully imported from OSM PBF")
    print("="*80)
    print(f"📍 Table: {SCHEMA}.{TABLE}")
    print(f"📊 Source: Geofabrik Berlin OSM Extract")
    print(f"\nNext: Restart FastAPI and test spatial queries!")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
