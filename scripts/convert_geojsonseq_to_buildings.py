#!/usr/bin/env python3
"""
Convert OSM GeoJSONSeq file to filtered GeoJSON (buildings only).

Takes the newline-delimited GeoJSON format and:
1. Filters to only building features
2. Converts to standard GeoJSON FeatureCollection
3. Saves to output file
"""

import json
from pathlib import Path
import sys

# Input file - the downloaded OSM extract
INPUT_FILE = Path("/Users/skfazlarabby/Downloads/planet_13.059,52.349_13.718,52.684.osm.geojsonseq")

# Output directory and file
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "vector" / "osm"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "osm_buildings_berlin.geojson"


def convert_geojsonseq_to_buildings():
    """
    Convert GeoJSONSeq file to filtered GeoJSON with buildings only.

    GeoJSONSeq format: each line is a complete GeoJSON feature
    We need to:
    1. Read each line
    2. Parse as JSON
    3. Filter for building features
    4. Collect into FeatureCollection
    """
    print(f"\n🔄 Converting GeoJSONSeq to Buildings GeoJSON...")
    print(f"   Input: {INPUT_FILE}")

    if not INPUT_FILE.exists():
        print(f"   ❌ Input file not found: {INPUT_FILE}")
        return False

    buildings = []
    skipped = 0
    total_lines = 0

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                total_lines += 1

                # Show progress every 10k lines
                if line_num % 10000 == 0:
                    print(f"   Processing line {line_num}... ({len(buildings)} buildings found so far)")

                # Strip whitespace
                line = line.strip()

                # Skip empty lines
                if not line:
                    skipped += 1
                    continue

                try:
                    feature = json.loads(line)

                    # Check if it's a building feature
                    # Buildings have "building" key in properties
                    properties = feature.get('properties', {})

                    # Check for building tag - if it exists, it's a building
                    if 'building' in properties:
                        buildings.append(feature)

                except json.JSONDecodeError as e:
                    if line_num <= 5:  # Only show first few errors
                        print(f"   ⚠️  Skipped invalid JSON at line {line_num}: {str(e)[:50]}")
                    skipped += 1
                    continue

        print(f"\n   ✓ Processed {total_lines} lines")
        print(f"   ✓ Found {len(buildings)} building features")
        print(f"   ✓ Skipped {skipped} non-building features")

        if len(buildings) == 0:
            print(f"   ❌ No buildings found! Check the input file format.")
            return False

        # Create GeoJSON FeatureCollection
        geojson = {
            "type": "FeatureCollection",
            "features": buildings
        }

        # Save to file
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2)

        file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
        print(f"\n✅ Saved {len(buildings)} buildings to GeoJSON")
        print(f"   File: {OUTPUT_FILE}")
        print(f"   Size: {file_size_mb:.2f} MB")

        return True

    except Exception as e:
        print(f"   ❌ Error reading input file: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n=== OSM GeoJSONSeq to Buildings Converter ===")

    success = convert_geojsonseq_to_buildings()

    if success:
        print("\n✅ Conversion complete!")
        print("   Next: Run the import script")
        print("   Command: python3 scripts/import_osm_buildings.py")
        return 0
    else:
        print("\n❌ Conversion failed!")
        return 1


if __name__ == "__main__":
    exit(main())
