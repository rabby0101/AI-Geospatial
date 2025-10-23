"""
Load newly downloaded OSM datasets into PostGIS
This script only loads the 13-15 new datasets (not the original 10)
"""

import geopandas as gpd
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")

if DB_PASSWORD:
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    DATABASE_URL = f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)

print("=" * 70)
print("Loading NEW OSM Datasets into PostGIS")
print("=" * 70)

# NEW datasets only (15 total - all except the original 10)
new_datasets = [
    # Medical/Health (4)
    ('doctors', 'data/vector/osm/berlin_doctors.geojson', 'osm_doctors'),
    ('dentists', 'data/vector/osm/berlin_dentists.geojson', 'osm_dentists'),
    ('clinics', 'data/vector/osm/berlin_clinics.geojson', 'osm_clinics'),
    ('veterinary', 'data/vector/osm/berlin_veterinary.geojson', 'osm_veterinary'),
    # Education (2)
    ('universities', 'data/vector/osm/berlin_universities.geojson', 'osm_universities'),
    ('libraries', 'data/vector/osm/berlin_libraries.geojson', 'osm_libraries'),
    # Commerce (4)
    ('supermarkets', 'data/vector/osm/berlin_supermarkets.geojson', 'osm_supermarkets'),
    ('banks', 'data/vector/osm/berlin_banks.geojson', 'osm_banks'),
    ('atm', 'data/vector/osm/berlin_atm.geojson', 'osm_atm'),
    ('post_offices', 'data/vector/osm/berlin_post_offices.geojson', 'osm_post_offices'),
    # Recreation (3 - note: gyms not downloaded due to API limits)
    ('museums', 'data/vector/osm/berlin_museums.geojson', 'osm_museums'),
    ('theatres', 'data/vector/osm/berlin_theatres.geojson', 'osm_theatres'),
    # Land Use (2)
    ('forests', 'data/vector/osm/berlin_forests.geojson', 'osm_forests'),
    ('water_bodies', 'data/vector/osm/berlin_water_bodies.geojson', 'osm_water_bodies'),
    # Administrative (1)
    ('districts', 'data/vector/osm/berlin_districts.geojson', 'osm_districts'),
]

loaded_datasets = []
failed_datasets = []

for idx, (name, filepath, table_name) in enumerate(new_datasets, 1):
    print(f"\n{idx}. Loading {name}...", end=" ", flush=True)

    try:
        if not os.path.exists(filepath):
            print(f"❌ File not found: {filepath}")
            failed_datasets.append(name)
            continue

        gdf = gpd.read_file(filepath)
        print(f"({len(gdf)} features) ", end="", flush=True)

        if len(gdf) == 0:
            print(f"⚠️  Empty dataset, skipping")
            failed_datasets.append(name)
            continue

        # Load to PostGIS
        gdf.to_postgis(
            table_name,
            engine,
            schema="vector",
            if_exists="replace",
            index=False
        )

        # Create spatial index
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS {table_name}_geom_idx
                ON vector.{table_name} USING GIST (geometry)
            """))
            conn.commit()

        print(f"✅ Loaded")
        loaded_datasets.append((name, table_name, len(gdf)))

    except Exception as e:
        print(f"❌ Error: {str(e)[:50]}")
        failed_datasets.append(name)

# Verification
print("\n" + "=" * 70)
print("Verification")
print("=" * 70)

with engine.connect() as conn:
    print("\nLoaded Tables:")
    for name, table_name, count in loaded_datasets:
        try:
            result = conn.execute(text(f"SELECT COUNT(*) FROM vector.{table_name}"))
            db_count = result.scalar()
            print(f"  ✅ {table_name:25s}: {db_count:6,} records")
        except Exception as e:
            print(f"  ❌ {table_name:25s}: Error - {e}")

    print(f"\n{'-' * 70}")
    print("Statistics:")
    total_features = sum(count for _, _, count in loaded_datasets)
    print(f"  Successfully loaded: {len(loaded_datasets)} datasets")
    print(f"  Total new features: {total_features:,}")
    if failed_datasets:
        print(f"  Failed: {len(failed_datasets)} - {', '.join(failed_datasets)}")

print("\n" + "=" * 70)
if failed_datasets:
    print(f"⚠️  Completed with {len(failed_datasets)} failures")
else:
    print("✅ All new datasets loaded successfully!")
print("=" * 70)
