"""
Load downloaded geospatial data into PostGIS database
"""

import geopandas as gpd
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection
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
print("Loading Geospatial Data into PostGIS")
print("=" * 70)

from sqlalchemy import text

# Create vector schema if it doesn't exist
try:
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS vector"))
        conn.commit()
    print("✅ Vector schema ready")
except Exception as e:
    print(f"⚠️  Schema creation: {e}")

# Define OSM datasets to load (23 total: 10 original + 13 new)
osm_datasets = [
    # Original 10 datasets
    ('hospitals', 'data/vector/osm/berlin_hospitals.geojson', 'osm_hospitals'),
    ('toilets', 'data/vector/osm/berlin_toilets.geojson', 'osm_toilets'),
    ('pharmacies', 'data/vector/osm/berlin_pharmacies.geojson', 'osm_pharmacies'),
    ('fire_stations', 'data/vector/osm/berlin_fire_stations.geojson', 'osm_fire_stations'),
    ('police_stations', 'data/vector/osm/berlin_police_stations.geojson', 'osm_police_stations'),
    ('parks', 'data/vector/osm/berlin_parks.geojson', 'osm_parks'),
    ('schools', 'data/vector/osm/berlin_schools.geojson', 'osm_schools'),
    ('restaurants', 'data/vector/osm/berlin_restaurants.geojson', 'osm_restaurants'),
    ('transport_stops', 'data/vector/osm/berlin_transport_stops.geojson', 'osm_transport_stops'),
    ('parking', 'data/vector/osm/berlin_parking.geojson', 'osm_parking'),
    # New Medical/Health (4)
    ('doctors', 'data/vector/osm/berlin_doctors.geojson', 'osm_doctors'),
    ('dentists', 'data/vector/osm/berlin_dentists.geojson', 'osm_dentists'),
    ('clinics', 'data/vector/osm/berlin_clinics.geojson', 'osm_clinics'),
    ('veterinary', 'data/vector/osm/berlin_veterinary.geojson', 'osm_veterinary'),
    # New Education (2)
    ('universities', 'data/vector/osm/berlin_universities.geojson', 'osm_universities'),
    ('libraries', 'data/vector/osm/berlin_libraries.geojson', 'osm_libraries'),
    # New Commerce & Services (4)
    ('supermarkets', 'data/vector/osm/berlin_supermarkets.geojson', 'osm_supermarkets'),
    ('banks', 'data/vector/osm/berlin_banks.geojson', 'osm_banks'),
    ('atm', 'data/vector/osm/berlin_atm.geojson', 'osm_atm'),
    ('post_offices', 'data/vector/osm/berlin_post_offices.geojson', 'osm_post_offices'),
    # New Recreation (3)
    ('museums', 'data/vector/osm/berlin_museums.geojson', 'osm_museums'),
    ('theatres', 'data/vector/osm/berlin_theatres.geojson', 'osm_theatres'),
    ('gyms', 'data/vector/osm/berlin_gyms.geojson', 'osm_gyms'),
    # New Land Use (2)
    ('forests', 'data/vector/osm/berlin_forests.geojson', 'osm_forests'),
    ('water_bodies', 'data/vector/osm/berlin_water_bodies.geojson', 'osm_water_bodies'),
    # New Administrative (1)
    ('districts', 'data/vector/osm/berlin_districts.geojson', 'osm_districts'),
]

loaded_datasets = []
failed_datasets = []

# Load each OSM dataset
for idx, (name, filepath, table_name) in enumerate(osm_datasets, 1):
    print(f"\n{idx}. Loading {name}...")
    try:
        if not os.path.exists(filepath):
            print(f"   ⚠️  File not found: {filepath}")
            print(f"   Skipping {name}")
            failed_datasets.append(name)
            continue

        gdf = gpd.read_file(filepath)
        print(f"   Found {len(gdf)} features in file")

        if len(gdf) == 0:
            print(f"   ⚠️  Empty dataset, skipping")
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

        print(f"   ✅ Loaded {len(gdf)} {name} into vector.{table_name}")
        print(f"   ✅ Created spatial index")

        # Show sample data
        if 'name' in gdf.columns:
            sample_names = gdf['name'].dropna().head(3).tolist()
            if sample_names:
                print(f"   Sample: {', '.join(sample_names)}")

        loaded_datasets.append((name, table_name, len(gdf)))

    except Exception as e:
        print(f"   ❌ Error: {e}")
        failed_datasets.append(name)

# Load GADM Administrative Boundaries (if available)
print(f"\n{len(osm_datasets) + 1}. Loading GADM Administrative Boundaries...")
try:
    import fiona
    gadm_file = "data/vector/gadm/gadm41_DEU.gpkg"

    if os.path.exists(gadm_file):
        layers = fiona.listlayers(gadm_file)
        print(f"   Available layers: {layers}")

        # Load admin level 1 (German states)
        admin = gpd.read_file(gadm_file, layer="ADM_ADM_1")
        print(f"   Found {len(admin)} admin units in file")

        # Prepare data
        admin['country_code'] = 'DEU'
        admin['admin_level'] = 1
        admin['name'] = admin['NAME_1']

        # Select relevant columns
        admin_clean = admin[['country_code', 'admin_level', 'name', 'geometry']].copy()

        admin_clean.to_postgis(
            "admin_boundaries",
            engine,
            schema="vector",
            if_exists="replace",
            index=False
        )

        # Create spatial index
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS admin_boundaries_geom_idx
                ON vector.admin_boundaries USING GIST (geometry)
            """))
            conn.commit()

        print(f"   ✅ Loaded {len(admin_clean)} admin boundaries into vector.admin_boundaries")
        print(f"   ✅ Created spatial index")
        loaded_datasets.append(('admin_boundaries', 'admin_boundaries', len(admin_clean)))
    else:
        print(f"   ⚠️  GADM file not found, skipping")
        failed_datasets.append('admin_boundaries')

except Exception as e:
    print(f"   ❌ Error: {e}")
    failed_datasets.append('admin_boundaries')

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
            print(f"  ✅ vector.{table_name:25s}: {db_count:6,} records")
        except Exception as e:
            print(f"  ❌ vector.{table_name:25s}: Error - {e}")

    # Show statistics
    print("\n" + "-" * 70)
    print("Statistics:")
    total_features = sum(count for _, _, count in loaded_datasets)
    print(f"  Total datasets loaded: {len(loaded_datasets)}")
    print(f"  Total features loaded: {total_features:,}")
    if failed_datasets:
        print(f"  Failed datasets: {len(failed_datasets)} - {', '.join(failed_datasets)}")

print("\n" + "=" * 70)
if failed_datasets:
    print(f"⚠️  Completed with {len(failed_datasets)} failures")
else:
    print("✅ All data loading completed successfully!")
print("=" * 70)
