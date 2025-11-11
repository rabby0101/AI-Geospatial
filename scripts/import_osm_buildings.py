#!/usr/bin/env python3
"""
Import OSM buildings from GeoJSON to PostGIS database.

Imports the converted osm_buildings_berlin.geojson file into PostGIS
as the osm_buildings table in the vector schema.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import geopandas as gpd

load_dotenv()

# Input file
INPUT_FILE = Path(__file__).parent.parent / "data" / "vector" / "osm" / "osm_buildings_berlin.geojson"

# Database configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Create SQLAlchemy engine
from sqlalchemy import create_engine, text

engine = create_engine(DATABASE_URL)


def import_osm_buildings():
    """
    Load OSM buildings GeoJSON and import to PostGIS.
    """
    print("\n🏗️  Importing OSM Buildings to PostGIS\n")

    # Check file exists
    if not INPUT_FILE.exists():
        print(f"❌ Input file not found: {INPUT_FILE}")
        return False

    file_size_mb = INPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"📂 Loading GeoJSON file...")
    print(f"   File: {INPUT_FILE}")
    print(f"   Size: {file_size_mb:.2f} MB")

    try:
        # Load GeoJSON file
        print(f"   Reading GeoJSON...")
        gdf = gpd.read_file(INPUT_FILE)

        print(f"✓ Loaded {len(gdf)} features")
        print(f"✓ Columns: {list(gdf.columns)[:8]}...")
        print(f"✓ CRS: {gdf.crs}")

        # Ensure correct CRS
        if gdf.crs != "EPSG:4326":
            print(f"⚠️  Converting CRS from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")

        # Verify spatial extent
        bounds = gdf.total_bounds
        print(f"✓ Spatial extent:")
        print(f"  Lon: {bounds[0]:.4f} to {bounds[2]:.4f}")
        print(f"  Lat: {bounds[1]:.4f} to {bounds[3]:.4f}")

        # Drop existing table if it exists
        print(f"\n📊 Preparing database...")
        with engine.connect() as conn:
            try:
                conn.execute(text("DROP TABLE IF EXISTS vector.osm_buildings CASCADE"))
                conn.commit()
                print(f"✓ Dropped existing osm_buildings table")
            except Exception as e:
                print(f"⚠️  Could not drop existing table: {e}")
                conn.rollback()

        # Import to PostGIS
        print(f"\n📥 Importing to PostGIS...")
        gdf.to_postgis(
            "osm_buildings",
            engine,
            schema="vector",
            if_exists="replace",
            index=False
        )

        print(f"✓ Imported to vector.osm_buildings")

        # Create spatial index
        print(f"✓ Creating spatial index...")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_osm_buildings_geom
                ON vector.osm_buildings USING GIST(geometry)
            """))
            conn.commit()

        # Verify import
        print(f"\n✅ Verifying import...")
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM vector.osm_buildings")).scalar()
            print(f"✓ Table has {count:,} features")

        print(f"\n✅ Successfully imported OSM buildings!")
        print(f"   Table: vector.osm_buildings")
        print(f"   Features: {count:,}")
        print(f"\n   Next steps:")
        print(f"   1. Update system prompts in deepseek.py and prompts.py")
        print(f"   2. Update metadata in table_descriptions.json")
        print(f"   3. Clear query cache")
        print(f"   4. Restart the server")

        return True

    except Exception as e:
        print(f"❌ Error during import: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    success = import_osm_buildings()
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
