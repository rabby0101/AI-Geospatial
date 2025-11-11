#!/usr/bin/env python3
"""
Test import: Import 50k buildings to verify the process works.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import geopandas as gpd
from sqlalchemy import create_engine, text

load_dotenv()

INPUT_FILE = Path("data/vector/osm/osm_buildings_berlin.geojson")
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)

print("\n🧪 Testing OSM Buildings Import\n")

# Read GeoJSON
print(f"📂 Reading GeoJSON...")
gdf = gpd.read_file(INPUT_FILE)
print(f"✓ Loaded {len(gdf):,} total features")

# Take only first 50k for testing
TEST_SIZE = 50000
gdf_test = gdf.iloc[:TEST_SIZE].copy()
print(f"✓ Selected first {TEST_SIZE:,} features for test")

# Ensure correct CRS
if gdf_test.crs != "EPSG:4326":
    print(f"Converting CRS to EPSG:4326...")
    gdf_test = gdf_test.to_crs("EPSG:4326")

# Drop test table if exists
print(f"\n🗑️  Cleaning up old test tables...")
with engine.connect() as conn:
    try:
        conn.execute(text("DROP TABLE IF EXISTS vector.osm_buildings_test CASCADE"))
        conn.commit()
        print(f"✓ Cleaned up")
    except Exception as e:
        print(f"⚠️  {e}")
        conn.rollback()

# Import test data
print(f"\n📥 Importing {TEST_SIZE:,} buildings to osm_buildings_test...")
try:
    gdf_test.to_postgis(
        "osm_buildings_test",
        engine,
        schema="vector",
        if_exists="replace",
        index=False
    )
    print(f"✓ Import successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Create spatial index
print(f"🔍 Creating spatial index...")
try:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE INDEX idx_osm_buildings_test_geom
            ON vector.osm_buildings_test USING GIST(geometry)
        """))
        conn.commit()
    print(f"✓ Index created")
except Exception as e:
    print(f"⚠️  {e}")

# Verify
print(f"\n✅ Verifying test table...")
try:
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM vector.osm_buildings_test")).scalar()
        print(f"✓ Test table has {count:,} features")

        # Check geometry types
        result = conn.execute(text("""
            SELECT ST_GeometryType(geometry), COUNT(*)
            FROM vector.osm_buildings_test
            GROUP BY ST_GeometryType(geometry)
        """)).fetchall()

        print(f"✓ Geometry types:")
        for geom_type, cnt in result:
            print(f"  - {geom_type}: {cnt:,}")

        # Sample a row
        sample = conn.execute(text("""
            SELECT osm_id, building, name, ST_AsText(geometry)
            FROM vector.osm_buildings_test
            LIMIT 1
        """)).fetchone()

        if sample:
            print(f"\n✓ Sample row:")
            print(f"  osm_id: {sample[0]}")
            print(f"  building: {sample[1]}")
            print(f"  name: {sample[2]}")
            print(f"  geometry: {sample[3]}")

except Exception as e:
    print(f"❌ Verification failed: {e}")
    exit(1)

print(f"\n✅ TEST PASSED! Ready to import full dataset.")
print(f"\nNext: Run full import with all 1.4M buildings")
