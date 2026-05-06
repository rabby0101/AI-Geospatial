"""
Verify Berlin OSM data loaded in PostGIS and test spatial queries
"""

from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

# Database connection
DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

print("=" * 80)
print("Berlin OSM Data Verification & Spatial Query Tests")
print("=" * 80)

# Test 1: Count all datasets
print("\n📊 Dataset Summary")
print("-" * 80)

datasets = [
    'osm_hospitals',
    'osm_toilets',
    'osm_pharmacies',
    'osm_fire_stations',
    'osm_police_stations',
    'osm_parks',
    'osm_schools',
    'osm_restaurants',
    'osm_transport_stops'
]

with engine.connect() as conn:
    for dataset in datasets:
        result = conn.execute(text(f"SELECT COUNT(*) FROM vector.{dataset}"))
        count = result.scalar()
        print(f"  {dataset:25s}: {count:7,} features")

# Test 2: Find toilets within 100m of transport stops
print("\n🚏 Test Query 1: Public toilets near transport stops (within 100m)")
print("-" * 80)

with engine.connect() as conn:
    query = text("""
        SELECT
            t.name as toilet_name,
            ts.name as stop_name,
            ROUND(ST_Distance(t.geometry::geography, ts.geometry::geography)::numeric, 1) as distance_m
        FROM vector.osm_toilets t
        JOIN vector.osm_transport_stops ts
            ON ST_DWithin(t.geometry::geography, ts.geometry::geography, 100)
        WHERE t.name IS NOT NULL
          AND ts.name IS NOT NULL
        ORDER BY distance_m
        LIMIT 10
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    if rows:
        print(f"  Found {len(rows)} toilets near transport stops:")
        for row in rows[:5]:
            print(f"    • {row[0]} near {row[1]} ({row[2]}m)")
    else:
        print("  No results found")

# Test 3: Find pharmacies within 500m of hospitals
print("\n🏥 Test Query 2: Pharmacies near hospitals (within 500m)")
print("-" * 80)

with engine.connect() as conn:
    query = text("""
        SELECT
            h.name as hospital_name,
            COUNT(p.osm_id) as pharmacy_count
        FROM vector.osm_hospitals h
        LEFT JOIN vector.osm_pharmacies p
            ON ST_DWithin(h.geometry::geography, p.geometry::geography, 500)
        WHERE h.name IS NOT NULL
        GROUP BY h.name
        HAVING COUNT(p.osm_id) > 0
        ORDER BY pharmacy_count DESC
        LIMIT 10
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    if rows:
        print(f"  Top hospitals by nearby pharmacies:")
        for row in rows[:5]:
            print(f"    • {row[0]}: {row[1]} pharmacies within 500m")
    else:
        print("  No results found")

# Test 4: Find nearest fire station to each school
print("\n🚒 Test Query 3: Fire stations near schools")
print("-" * 80)

with engine.connect() as conn:
    query = text("""
        SELECT DISTINCT ON (s.osm_id)
            s.name as school_name,
            f.name as fire_station_name,
            ROUND(ST_Distance(s.geometry::geography, f.geometry::geography)::numeric, 0) as distance_m
        FROM vector.osm_schools s
        CROSS JOIN vector.osm_fire_stations f
        WHERE s.name IS NOT NULL
          AND f.name IS NOT NULL
        ORDER BY s.osm_id, ST_Distance(s.geometry::geography, f.geometry::geography)
        LIMIT 10
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    if rows:
        print(f"  Sample schools and their nearest fire station:")
        for row in rows[:5]:
            print(f"    • {row[0]}")
            print(f"      → Nearest: {row[1]} ({row[2]}m)")
    else:
        print("  No results found")

# Test 5: Parks accessibility - how many parks within 1km of city center
print("\n🌳 Test Query 4: Parks near city center (Brandenburger Tor)")
print("-" * 80)

with engine.connect() as conn:
    # Brandenburger Tor coordinates: 13.377704, 52.516275
    query = text("""
        SELECT
            name,
            ROUND(ST_Distance(
                geometry::geography,
                ST_SetSRID(ST_MakePoint(13.377704, 52.516275), 4326)::geography
            )::numeric, 0) as distance_m
        FROM vector.osm_parks
        WHERE ST_DWithin(
            geometry::geography,
            ST_SetSRID(ST_MakePoint(13.377704, 52.516275), 4326)::geography,
            1000
        )
        AND name IS NOT NULL
        ORDER BY distance_m
        LIMIT 10
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    if rows:
        print(f"  Found {len(rows)} parks within 1km of Brandenburger Tor:")
        for row in rows[:5]:
            print(f"    • {row[0]} ({row[1]}m)")
    else:
        print("  No results found")

# Test 6: Restaurant density near transport stops
print("\n🍽️  Test Query 5: Restaurants near transport hubs")
print("-" * 80)

with engine.connect() as conn:
    query = text("""
        SELECT
            ts.name as stop_name,
            COUNT(r.osm_id) as restaurant_count
        FROM vector.osm_transport_stops ts
        LEFT JOIN vector.osm_restaurants r
            ON ST_DWithin(ts.geometry::geography, r.geometry::geography, 200)
        WHERE ts.name IS NOT NULL
        GROUP BY ts.name
        HAVING COUNT(r.osm_id) > 10
        ORDER BY restaurant_count DESC
        LIMIT 10
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    if rows:
        print(f"  Transport stops with most nearby restaurants (within 200m):")
        for row in rows[:5]:
            print(f"    • {row[0]}: {row[1]} restaurants")
    else:
        print("  No results found")

# Test 7: Spatial coverage - bounding box verification
print("\n🗺️  Test Query 6: Spatial Coverage Verification")
print("-" * 80)

with engine.connect() as conn:
    query = text("""
        SELECT
            'osm_hospitals' as dataset,
            ST_XMin(ST_Extent(geometry)) as min_lon,
            ST_YMin(ST_Extent(geometry)) as min_lat,
            ST_XMax(ST_Extent(geometry)) as max_lon,
            ST_YMax(ST_Extent(geometry)) as max_lat
        FROM vector.osm_hospitals
        UNION ALL
        SELECT
            'osm_toilets',
            ST_XMin(ST_Extent(geometry)),
            ST_YMin(ST_Extent(geometry)),
            ST_XMax(ST_Extent(geometry)),
            ST_YMax(ST_Extent(geometry))
        FROM vector.osm_toilets
        UNION ALL
        SELECT
            'osm_parks',
            ST_XMin(ST_Extent(geometry)),
            ST_YMin(ST_Extent(geometry)),
            ST_XMax(ST_Extent(geometry)),
            ST_YMax(ST_Extent(geometry))
        FROM vector.osm_parks
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    print(f"  Dataset bounding boxes (should match Berlin bbox):")
    print(f"  Expected: 13.088, 52.338, 13.761, 52.675")
    print()
    for row in rows:
        print(f"    • {row[0]:20s}: ({row[1]:.3f}, {row[2]:.3f}, {row[3]:.3f}, {row[4]:.3f})")

print("\n" + "=" * 80)
print("✅ Verification Complete!")
print("=" * 80)
print("\n💡 Your data is ready for natural language queries via the API!")
print("\nExample queries you can now support:")
print("  • 'Find all hospitals within 1km of Alexanderplatz'")
print("  • 'Show me toilets near the main train station'")
print("  • 'Which parks are within walking distance of restaurants?'")
print("  • 'Find pharmacies near schools'")
print("  • 'Where are fire stations located in Berlin?'")
print()
