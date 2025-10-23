"""
Example 1: Download OpenStreetMap data for a city

This example shows how to download real OSM data using the free Overpass API
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders import OSMLoader
import logging

logging.basicConfig(level=logging.INFO)


def main():
    """Download OSM data for Berlin"""

    # Initialize loader
    loader = OSMLoader(data_dir="data/vector/osm")

    # Define Berlin bounding box (min_lon, min_lat, max_lon, max_lat)
    berlin_bbox = (13.088, 52.338, 13.761, 52.675)

    print("=" * 60)
    print("Downloading OpenStreetMap data for Berlin")
    print("=" * 60)

    # 1. Download hospitals
    print("\n1. Downloading hospitals...")
    hospitals = loader.query_overpass(berlin_bbox, ['hospital'])
    print(f"Found {len(hospitals)} hospitals")

    # Save to file
    hospitals.to_file(
        'data/vector/osm/berlin_hospitals.geojson',
        driver='GeoJSON'
    )
    print("Saved to: data/vector/osm/berlin_hospitals.geojson")

    # Show sample data
    print("\nSample hospitals:")
    print(hospitals[['name', 'amenity']].head())

    # 2. Download schools
    print("\n2. Downloading schools...")
    schools = loader.query_overpass(berlin_bbox, ['school'])
    print(f"Found {len(schools)} schools")

    schools.to_file(
        'data/vector/osm/berlin_schools.geojson',
        driver='GeoJSON'
    )
    print("Saved to: data/vector/osm/berlin_schools.geojson")

    # 3. Download roads (smaller area to avoid timeout)
    print("\n3. Downloading roads (central Berlin only)...")
    central_berlin_bbox = (13.3, 52.5, 13.5, 52.55)

    roads = loader.query_overpass(central_berlin_bbox, ['road'])
    print(f"Found {len(roads)} road segments")

    roads.to_file(
        'data/vector/osm/berlin_roads_central.geojson',
        driver='GeoJSON'
    )
    print("Saved to: data/vector/osm/berlin_roads_central.geojson")

    # 4. Download rivers
    print("\n4. Downloading rivers...")
    rivers = loader.query_overpass(berlin_bbox, ['river'])
    print(f"Found {len(rivers)} river segments")

    rivers.to_file(
        'data/vector/osm/berlin_rivers.geojson',
        driver='GeoJSON'
    )
    print("Saved to: data/vector/osm/berlin_rivers.geojson")

    print("\n" + "=" * 60)
    print("Download completed!")
    print("=" * 60)

    # Statistics
    print("\nStatistics:")
    print(f"  Hospitals: {len(hospitals)}")
    print(f"  Schools: {len(schools)}")
    print(f"  Roads: {len(roads)}")
    print(f"  Rivers: {len(rivers)}")

    print("\nYou can now:")
    print("  1. View these files in QGIS")
    print("  2. Load them into PostGIS")
    print("  3. Use them for spatial analysis")


if __name__ == "__main__":
    main()
