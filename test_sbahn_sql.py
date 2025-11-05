#!/usr/bin/env python3
"""Test S-Bahn query with direct SQL"""
import psycopg2
from psycopg2.extras import RealDictCursor
import json

try:
    # Connect to PostGIS
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        user="geoassist",
        password="geoassist_password",
        database="geoassist"
    )

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Test 1: Count S-Bahn stations
    print("=" * 60)
    print("Test 1: Count S-Bahn stations in transport_stops")
    print("=" * 60)

    query1 = """
    SELECT COUNT(*) as count
    FROM vector.osm_transport_stops
    WHERE name ILIKE '%S-Bahn%' OR ref ILIKE '%S%'
    """

    cursor.execute(query1)
    result = cursor.fetchone()
    print(f"S-Bahn stations with 'S-Bahn' in name: {result['count']}")

    # Test 2: List first few S-Bahn stations
    print("\n" + "=" * 60)
    print("Test 2: Sample S-Bahn stations")
    print("=" * 60)

    query2 = """
    SELECT osm_id, name, type
    FROM vector.osm_transport_stops
    WHERE name ILIKE '%S-Bahn%' OR ref ILIKE '%S%'
    LIMIT 5
    """

    cursor.execute(query2)
    results = cursor.fetchall()
    for row in results:
        print(f"  {row['name']} ({row['type']}, osm_id={row['osm_id']})")

    # Test 3: Count hospitals within 3km of first S-Bahn station
    print("\n" + "=" * 60)
    print("Test 3: Hospitals within 3km of S-Bahn stations")
    print("=" * 60)

    query3 = """
    SELECT t.name as station_name, COUNT(h.osm_id) as hospital_count
    FROM vector.osm_transport_stops t
    LEFT JOIN vector.osm_hospitals h
      ON ST_DWithin(ST_Transform(t.geometry, 3857), ST_Transform(h.geometry, 3857), 3000)
    WHERE t.name ILIKE '%S-Bahn%' OR t.ref ILIKE '%S%'
    GROUP BY t.osm_id, t.name
    LIMIT 10
    """

    cursor.execute(query3)
    results = cursor.fetchall()
    print(f"\nFound {len(results)} S-Bahn stations\n")
    for row in results:
        print(f"  {row['station_name']}: {row['hospital_count']} hospitals nearby")

    # Test 4: S-Bahn stations WITHOUT hospitals within 3km
    print("\n" + "=" * 60)
    print("Test 4: S-Bahn stations WITHOUT hospitals within 3km")
    print("=" * 60)

    query4 = """
    SELECT t.osm_id, t.name, t.geometry
    FROM vector.osm_transport_stops t
    WHERE (t.name ILIKE '%S-Bahn%' OR t.ref ILIKE '%S%')
    AND NOT EXISTS (
      SELECT 1 FROM vector.osm_hospitals h
      WHERE ST_DWithin(ST_Transform(t.geometry, 3857), ST_Transform(h.geometry, 3857), 3000)
    )
    """

    cursor.execute(query4)
    results = cursor.fetchall()
    print(f"\nFound {len(results)} S-Bahn stations WITHOUT hospitals nearby:\n")
    for i, row in enumerate(results[:10], 1):
        print(f"  {i}. {row['name']} (osm_id={row['osm_id']})")

    if len(results) > 10:
        print(f"  ... and {len(results) - 10} more")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
