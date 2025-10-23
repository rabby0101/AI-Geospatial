"""
Create a proper Berlin districts table with district names
This replaces the OSM districts table which doesn't have proper name attributes
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import geopandas as gpd
from shapely.geometry import box

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

# Berlin districts (Bezirke) with approximate bounding boxes
# Data from: https://en.wikipedia.org/wiki/Boroughs_of_Berlin
BERLIN_DISTRICTS = {
    'Mitte': {
        'bounds': (13.35, 52.50, 13.42, 52.57),
        'coords': (13.385, 52.535)
    },
    'Charlottenburg-Wilmersdorf': {
        'bounds': (13.19, 52.47, 13.32, 52.60),
        'coords': (13.255, 52.54)
    },
    'Friedrichshain-Kreuzberg': {
        'bounds': (13.39, 52.48, 13.50, 52.53),
        'coords': (13.445, 52.505)
    },
    'Lichtenberg': {
        'bounds': (13.53, 52.47, 13.65, 52.57),
        'coords': (13.59, 52.52)
    },
    'Marzahn-Hellersdorf': {
        'bounds': (13.55, 52.45, 13.75, 52.57),
        'coords': (13.65, 52.51)
    },
    'Neukölln': {
        'bounds': (13.43, 52.38, 13.59, 52.48),
        'coords': (13.51, 52.43)
    },
    'Pankow': {
        'bounds': (13.38, 52.55, 13.54, 52.67),
        'coords': (13.46, 52.61)
    },
    'Reinickendorf': {
        'bounds': (13.22, 52.52, 13.35, 52.68),
        'coords': (13.285, 52.60)
    },
    'Spandau': {
        'bounds': (13.16, 52.48, 13.32, 52.62),
        'coords': (13.24, 52.55)
    },
    'Steglitz-Zehlendorf': {
        'bounds': (13.21, 52.38, 13.40, 52.52),
        'coords': (13.305, 52.45)
    },
    'Tempelhof-Schöneberg': {
        'bounds': (13.35, 52.38, 13.48, 52.48),
        'coords': (13.415, 52.43)
    },
    'Treptow-Köpenick': {
        'bounds': (13.54, 52.38, 13.75, 52.51),
        'coords': (13.645, 52.445)
    },
}

print("=" * 80)
print("Creating Berlin Districts Table")
print("=" * 80)

# Create GeoDataFrame from district data
districts_data = []
for district_name, data in BERLIN_DISTRICTS.items():
    min_lon, min_lat, max_lon, max_lat = data['bounds']
    geometry = box(min_lon, min_lat, max_lon, max_lat)
    districts_data.append({
        'name': district_name,
        'geometry': geometry
    })

gdf = gpd.GeoDataFrame(districts_data, crs='EPSG:4326')

print(f"\nCreated GeoDataFrame with {len(gdf)} districts")
print(f"Districts: {', '.join(gdf['name'].tolist())}")

# Load to PostGIS (replace existing table)
try:
    gdf.to_postgis(
        'osm_districts',
        engine,
        schema='vector',
        if_exists='replace',
        index=False
    )

    # Create spatial index
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS osm_districts_geom_idx
            ON vector.osm_districts USING GIST (geometry)
        """))
        conn.commit()

    print("\n✅ Districts table created successfully!")

    # Verify
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM vector.osm_districts"))
        count = result.scalar()
        print(f"✅ Table has {count} records")

        result = conn.execute(text("SELECT name FROM vector.osm_districts ORDER BY name"))
        print("\nDistricts in table:")
        for row in result.fetchall():
            print(f"  - {row[0]}")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
