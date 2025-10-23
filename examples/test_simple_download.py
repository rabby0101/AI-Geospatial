"""
Simple test: Download OSM data for a small area
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders import OSMLoader, GADMLoader
import logging

logging.basicConfig(level=logging.INFO)


def main():
    """Download data for small test area"""

    print("=" * 60)
    print("Test 1: Download hospitals in central Berlin (small area)")
    print("=" * 60)

    loader = OSMLoader(data_dir="data/vector/osm")

    # Very small bbox - central Berlin (Brandenburg Gate area)
    central_bbox = (13.36, 52.51, 13.40, 52.53)

    try:
        print("\nDownloading hospitals...")
        hospitals = loader.query_overpass(central_bbox, ['hospital'])
        print(f"✓ Found {len(hospitals)} hospitals")

        if len(hospitals) > 0:
            hospitals.to_file('data/vector/osm/test_hospitals.geojson', driver='GeoJSON')
            print(f"✓ Saved to: data/vector/osm/test_hospitals.geojson")
            print(f"\nSample data:")
            print(hospitals[['name', 'amenity']].head())
        else:
            print("No hospitals in this small area, trying schools...")

    except Exception as e:
        print(f"✗ Error: {e}")

    # Try GADM instead (doesn't use rate-limited API)
    print("\n" + "=" * 60)
    print("Test 2: Download Germany administrative boundaries")
    print("=" * 60)

    gadm = GADMLoader(data_dir="data/vector/gadm")

    try:
        print("\nDownloading Germany boundaries...")
        germany = gadm.load_boundaries('DEU', admin_level=1)
        print(f"✓ Downloaded {len(germany)} German states")

        print(f"\nGerman states:")
        for idx, row in germany.head(10).iterrows():
            name = row.get('NAME_1', 'Unknown')
            print(f"  - {name}")

        print(f"\n✓ Data saved to: data/vector/gadm/gadm41_DEU.gpkg")

    except Exception as e:
        print(f"✗ Error: {e}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
