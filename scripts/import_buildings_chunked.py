#!/usr/bin/env python3
"""
Import OSM buildings in chunks to PostGIS, then merge into final table.

Strategy:
1. Split GeoJSON into 100 chunks
2. Import each chunk as a temporary table
3. Merge all chunks into final osm_buildings table
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import geopandas as gpd
from sqlalchemy import create_engine, text
import numpy as np

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
NUM_CHUNKS = 100


def import_chunked():
    """Import buildings in chunks and merge."""

    print("\n🏗️  Importing OSM Buildings in Chunks\n")

    # Read GeoJSON
    print(f"📂 Reading GeoJSON file...")
    gdf = gpd.read_file(INPUT_FILE)
    print(f"✓ Loaded {len(gdf):,} features")

    # Ensure correct CRS
    if gdf.crs != "EPSG:4326":
        print(f"Converting CRS to EPSG:4326...")
        gdf = gdf.to_crs("EPSG:4326")

    # Split into chunks
    print(f"\n📊 Splitting into {NUM_CHUNKS} chunks...")
    chunk_size = len(gdf) // NUM_CHUNKS
    chunks = [gdf.iloc[i*chunk_size:(i+1)*chunk_size] if i < NUM_CHUNKS-1 else gdf.iloc[i*chunk_size:]
              for i in range(NUM_CHUNKS)]

    print(f"✓ Chunk size: {chunk_size:,} features per chunk")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1:3d}: {len(chunk):,} features")

    # Drop existing final table if it exists
    print(f"\n🗑️  Cleaning up old tables...")
    with engine.connect() as conn:
        try:
            conn.execute(text("DROP TABLE IF EXISTS vector.osm_buildings CASCADE"))
            conn.commit()
            print(f"✓ Dropped existing osm_buildings table")
        except Exception as e:
            print(f"⚠️  {e}")
            conn.rollback()

    # Import chunks
    print(f"\n📥 Importing {NUM_CHUNKS} chunks to PostGIS...")
    successful_chunks = 0
    failed_chunks = []

    for i, chunk in enumerate(chunks, 1):
        chunk_table = f"osm_buildings_chunk_{i:03d}"
        try:
            print(f"  [{i:3d}/{NUM_CHUNKS}] Importing {len(chunk):,} features to {chunk_table}...", end=" ", flush=True)

            chunk.to_postgis(
                chunk_table,
                engine,
                schema="vector",
                if_exists="replace",
                index=False
            )
            print(f"✓")
            successful_chunks += 1

        except Exception as e:
            print(f"❌ {str(e)[:50]}")
            failed_chunks.append((i, str(e)))

    print(f"\n✅ Imported {successful_chunks}/{NUM_CHUNKS} chunks successfully")

    if failed_chunks:
        print(f"❌ Failed chunks: {failed_chunks}")
        return False

    # Merge all chunks into final table
    print(f"\n🔗 Merging {NUM_CHUNKS} chunks into final osm_buildings table...")

    try:
        chunk_tables = [f"osm_buildings_chunk_{i:03d}" for i in range(1, NUM_CHUNKS + 1)]

        # Build UNION ALL query
        union_query = " UNION ALL ".join([
            f"SELECT * FROM vector.{table}"
            for table in chunk_tables
        ])

        merge_sql = f"""
        CREATE TABLE vector.osm_buildings AS
        {union_query}
        """

        with engine.connect() as conn:
            conn.execute(text(merge_sql))
            conn.commit()

        print(f"✓ Merged all chunks into vector.osm_buildings")

    except Exception as e:
        print(f"❌ Merge failed: {e}")
        return False

    # Create spatial index
    print(f"\n🔍 Creating spatial index...")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX idx_osm_buildings_geom
                ON vector.osm_buildings USING GIST(geometry)
            """))
            conn.commit()
        print(f"✓ Spatial index created")
    except Exception as e:
        print(f"⚠️  Index creation warning: {e}")

    # Verify final table
    print(f"\n✅ Verifying final table...")
    try:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM vector.osm_buildings")).scalar()
            print(f"✓ Final table has {count:,} features")
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

    # Clean up chunk tables
    print(f"\n🧹 Cleaning up temporary chunk tables...")
    try:
        with engine.connect() as conn:
            for table in chunk_tables:
                conn.execute(text(f"DROP TABLE IF EXISTS vector.{table} CASCADE"))
            conn.commit()
        print(f"✓ Removed {NUM_CHUNKS} temporary tables")
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")

    return True


def main():
    success = import_chunked()

    if success:
        print(f"\n✅ All done! OSM buildings imported successfully.")
        print(f"   Table: vector.osm_buildings")
        print(f"   Ready for queries!")
        return 0
    else:
        print(f"\n❌ Import failed!")
        return 1


if __name__ == "__main__":
    exit(main())
