#!/usr/bin/env python
"""
Download missing OSM datasets for Berlin
Focus on the 13 new datasets needed for Phase 1 expansion
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders.osm_loader import OSMLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Berlin bounding box
BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)

# 13 NEW datasets to download
NEW_DATASETS = {
    'Medical/Health (4)': {
        'doctors': 'doctor',
        'dentists': 'dentist',
        'clinics': 'clinic',
        'veterinary': 'veterinary',
    },
    'Education (2)': {
        'universities': 'university',
        'libraries': 'library',
    },
    'Commerce (4)': {
        'supermarkets': 'supermarket',
        'banks': 'bank',
        'atm': 'atm',
        'post_offices': 'post_office',
    },
    'Recreation (3)': {
        'museums': 'museum',
        'theatres': 'theatre',
        'gyms': 'gym',
    },
    'Land Use (2)': {
        'forests': 'forest',
        'water_bodies': 'water_body',
    },
    'Administrative (1)': {
        'districts': 'district',
    }
}

def main():
    """Download all missing OSM datasets"""

    print("=" * 80)
    print("DOWNLOADING MISSING OSM DATASETS FOR BERLIN")
    print("=" * 80)
    print(f"\nBerlin Bounding Box: {BERLIN_BBOX}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Initialize loader
    loader = OSMLoader(data_dir="data/vector/osm")

    # Flatten dataset list
    all_datasets = {}
    for category, datasets in NEW_DATASETS.items():
        all_datasets.update(datasets)

    total = len(all_datasets)
    successful = []
    failed = []

    print(f"Total datasets to download: {total}\n")
    print("=" * 80)
    print("Starting downloads...")
    print("=" * 80 + "\n")

    start_time = time.time()

    # Download each dataset
    for idx, (filename, feature_key) in enumerate(all_datasets.items(), 1):
        filepath = loader.data_dir / f"berlin_{filename}.geojson"

        # Skip if already exists
        if filepath.exists():
            print(f"[{idx}/{total}] {filename:20s} - ⏭️  ALREADY EXISTS (skipping)")
            successful.append((filename, "already_exists"))
            continue

        print(f"[{idx}/{total}] {filename:20s} - ", end="", flush=True)

        try:
            # Download with timeout
            gdf = loader.query_overpass(
                bbox=BERLIN_BBOX,
                features=[feature_key],
                timeout=180
            )

            if len(gdf) == 0:
                print(f"⚠️  No features found")
                failed.append((filename, "empty_result"))
                continue

            # Save to file
            gdf.to_file(filepath, driver='GeoJSON')

            print(f"✅ {len(gdf):,} features")
            successful.append((filename, len(gdf)))

            # Small delay to avoid rate limiting
            time.sleep(2)

        except Exception as e:
            print(f"❌ {str(e)[:60]}")
            failed.append((filename, str(e)[:100]))
            time.sleep(5)  # Longer delay after error

    elapsed = time.time() - start_time

    # Print summary
    print("\n" + "=" * 80)
    print("DOWNLOAD SUMMARY")
    print("=" * 80 + "\n")

    print("Successfully Downloaded/Found:")
    for filename, status in successful:
        if status == "already_exists":
            print(f"  ⏭️  {filename:25s}: Already downloaded")
        else:
            print(f"  ✅ {filename:25s}: {status:,} features")

    if failed:
        print(f"\nFailed Downloads ({len(failed)}):")
        for filename, reason in failed:
            print(f"  ❌ {filename:25s}: {reason[:50]}")

    print(f"\n{'-' * 80}")
    print(f"Total Successful: {len(successful)}/{total}")
    print(f"Total Failed: {len(failed)}/{total}")
    print(f"Success Rate: {len(successful)/total*100:.1f}%")
    print(f"Time Elapsed: {elapsed:.1f} seconds")
    print(f"Data Directory: {loader.data_dir}")
    print(f"{'=' * 80}\n")

    # Next steps
    if len(successful) > 0:
        print("✅ Next step: Load data into PostGIS")
        print(f"   python load_data_to_postgis.py\n")

    return len(failed) == 0

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by user")
        sys.exit(1)
