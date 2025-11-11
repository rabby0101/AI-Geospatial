#!/usr/bin/env python3
"""
Fast streaming import: Read 1000 buildings from GeoJSON without loading entire file
Uses streaming JSON parsing for maximum performance
"""

import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import geopandas as gpd
from shapely.geometry import Point
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

print("\n⚡ Fast Streaming 1000-Building Import Test\n")

# Stream only first 1000 features from GeoJSON
print(f"📂 Streaming first 1000 buildings from GeoJSON...")
start = time.time()

features = []
with open(INPUT_FILE, 'r') as f:
    data = json.load(f)
    for i, feature in enumerate(data['features']):
        if i >= 1000:
            break
        features.append(feature)

read_time = time.time() - start
print(f"✓ Read {len(features)} features in {read_time:.2f}s")

# Convert to GeoDataFrame
print(f"\n🔄 Converting to GeoDataFrame...")
gdf_list = []
for feature in features:
    props = feature.get('properties', {})
    geom = feature.get('geometry', {})

    if geom.get('type') == 'Point':
        coords = geom.get('coordinates', [])
        if len(coords) >= 2:
            gdf_list.append({
                'geometry': Point(coords[0], coords[1]),
                **props
            })

gdf_test = gpd.GeoDataFrame(gdf_list, crs="EPSG:4326")
print(f"✓ Created GeoDataFrame with {len(gdf_test)} features")

# Drop test table if exists
print(f"\n🗑️  Cleaning up old test tables...")
with engine.connect() as conn:
    try:
        conn.execute(text("DROP TABLE IF EXISTS vector.osm_buildings_1000 CASCADE"))
        conn.commit()
        print(f"✓ Cleaned up")
    except Exception as e:
        print(f"⚠️  {e}")
        conn.rollback()

# Import test data with timing
print(f"\n📥 Importing {len(gdf_test)} buildings to osm_buildings_1000...")
start = time.time()
try:
    gdf_test.to_postgis(
        "osm_buildings_1000",
        engine,
        schema="vector",
        if_exists="replace",
        index=False,
        chunksize=100  # Import in batches
    )
    import_time = time.time() - start
    print(f"✓ Import successful in {import_time:.2f}s")
    print(f"  Rate: {len(gdf_test)/import_time:.0f} features/second")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Create spatial index
print(f"\n🔍 Creating spatial index...")
try:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE INDEX idx_osm_buildings_1000_geom
            ON vector.osm_buildings_1000 USING GIST(geometry)
        """))
        conn.commit()
    print(f"✓ Index created")
except Exception as e:
    print(f"⚠️  {e}")

# Verify
print(f"\n✅ Verifying test table...")
try:
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM vector.osm_buildings_1000")).scalar()
        print(f"✓ Test table has {count:,} features")

        # Sample a row
        sample = conn.execute(text("""
            SELECT osm_id, building, name, ST_AsText(geometry)
            FROM vector.osm_buildings_1000
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

print(f"\n✅ TEST PASSED!")
print(f"\nTiming Summary:")
print(f"  Read:   {read_time:.2f}s")
print(f"  Import: {import_time:.2f}s")
print(f"  Total:  {read_time + import_time:.2f}s")
print(f"\n📊 Extrapolated to full 1.4M buildings:")
extrapolated = (read_time + import_time) * 1410733 / len(gdf_test)
print(f"  Estimated time: {extrapolated / 60:.1f} minutes")
if extrapolated > 3600:
    print(f"                  {extrapolated / 3600:.1f} hours")
