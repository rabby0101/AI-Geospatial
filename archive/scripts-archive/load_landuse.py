#!/usr/bin/env python3
"""
Load OSM landuse GeoJSON into PostGIS
"""

import sys
import geopandas as gpd
from pathlib import Path
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
project_root = Path(__file__).parent.parent
env_path = project_root / '.env'
load_dotenv(str(env_path))


def load_landuse_to_postgis():
    """Load landuse GeoJSON into PostGIS"""

    print("=" * 80)
    print("LOADING LANDUSE DATA INTO POSTGIS")
    print("=" * 80 + "\n")

    # Database connection
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')

    connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'

    print(f"Database Connection:")
    print(f"  Host: {db_host}:{db_port}")
    print(f"  Database: {db_name}")
    print(f"  User: {db_user}\n")

    try:
        print("Creating engine...", end="", flush=True)
        engine = create_engine(connection_string)
        print(" ✅\n")

        # Read GeoJSON
        geojson_path = project_root / 'data/vector/osm/berlin_landuse.geojson'

        if not geojson_path.exists():
            print(f"❌ File not found: {geojson_path}")
            print(f"   Please run: python scripts/download_landuse.py\n")
            return False

        print(f"Reading GeoJSON: {geojson_path}")
        gdf = gpd.read_file(str(geojson_path))
        print(f"  ✅ Loaded {len(gdf):,} landuse areas\n")

        # Ensure CRS is correct
        print(f"CRS Check:")
        if gdf.crs is None:
            print(f"  ⚠️  No CRS set, assuming EPSG:4326")
            gdf.crs = 'EPSG:4326'
        elif gdf.crs != 'EPSG:4326':
            print(f"  Converting from {gdf.crs} to EPSG:4326...", end="", flush=True)
            gdf = gdf.to_crs('EPSG:4326')
            print(" ✅")

        print(f"  CRS: {gdf.crs}\n")

        # Display column information
        print(f"Data Schema:")
        print(f"  Columns: {list(gdf.columns)}")
        print(f"  Geometry type: {gdf.geometry.type.unique().tolist()}\n")

        if 'landuse' in gdf.columns:
            landuse_types = gdf['landuse'].value_counts()
            print(f"Landuse Types Distribution:")
            for ltype, count in landuse_types.items():
                print(f"  - {ltype}: {count:,}")
            print()

        # Create table in PostGIS
        table_name = 'osm_landuse'
        schema = 'vector'

        print(f"Creating/Replacing PostGIS table: {schema}.{table_name}...", end="", flush=True)

        # Write to PostGIS
        gdf.to_postgis(
            name=table_name,
            con=engine,
            schema=schema,
            if_exists='replace',
            index=False
        )
        print(" ✅\n")

        print(f"Creating spatial index...", end="", flush=True)
        # Create spatial index
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(f"CREATE INDEX idx_{table_name}_geom ON {schema}.{table_name} USING GIST (geometry)")
                )
            print(" ✅\n")
        except Exception as e:
            print(f" ⚠️  (may already exist)\n")
            logger.debug(f"Spatial index: {e}")

        # Verify the data
        print(f"Verifying data in database...")
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.{table_name}")
            ).fetchone()
            count = result[0]
            print(f"  ✅ {count:,} records in {schema}.{table_name}\n")

        # Show sample of data in database
        print(f"Sample Data in Database:")
        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT "hilucsLandUse", COUNT(*) as count
                    FROM {schema}.{table_name}
                    WHERE "hilucsLandUse" IS NOT NULL
                    GROUP BY "hilucsLandUse"
                    ORDER BY count DESC
                    LIMIT 10
                """)
            )
            for row in result:
                print(f"  - {row[0]}: {row[1]:,}")

        print(f"\n" + "=" * 80)
        print(f"✅ SUCCESS: Landuse data loaded into PostGIS")
        print(f"=" * 80 + "\n")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.exception("Failed to load landuse data")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = load_landuse_to_postgis()
    sys.exit(0 if success else 1)
