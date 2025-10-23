#!/usr/bin/env python3
"""
Direct query test - bypasses DeepSeek API
"""
import geopandas as gpd
from sqlalchemy import create_engine, text
import json

# Database connection
DB_URL = 'postgresql://geoassist:geoassist_password@localhost:5433/geoassist'

# SQL query - restaurants without parking nearby
sql = """
SELECT
    r.name,
    r.osm_id,
    ST_AsGeoJSON(r.geometry) as geometry
FROM vector.osm_restaurants r
WHERE NOT EXISTS (
    SELECT 1 FROM vector.osm_parking p
    WHERE ST_DWithin(r.geometry::geography, p.geometry::geography, 200)
)
ORDER BY r.name
LIMIT 50;
"""

print("🔍 Querying database...")
engine = create_engine(DB_URL)

with engine.connect() as conn:
    result = conn.execute(text(sql))
    rows = result.fetchall()

    features = []
    for row in rows:
        geom = json.loads(row[2])
        feature = {
            "type": "Feature",
            "properties": {
                "name": row[0],
                "osm_id": row[1]
            },
            "geometry": geom
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    print(f"\n✓ Found {len(features)} restaurants without nearby parking\n")
    print("="*60)
    print("Top 10 Restaurants:")
    print("="*60)
    for i, feature in enumerate(features[:10], 1):
        name = feature['properties']['name'] or 'Unnamed'
        coords = feature['geometry']['coordinates']
        print(f"{i:2d}. {name:<35} ({coords[1]:.4f}°N, {coords[0]:.4f}°E)")

    # Save to file
    with open('restaurants_no_parking.geojson', 'w') as f:
        json.dump(geojson, f, indent=2)

    print("\n" + "="*60)
    print(f"✓ Saved {len(features)} restaurants to: restaurants_no_parking.geojson")
    print("="*60)
