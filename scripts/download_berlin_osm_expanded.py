#!/usr/bin/env python
"""
Download all OSM datasets for Berlin (23 feature types)
Includes original 10 + new 13 datasets
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders.osm_loader import OSMLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Berlin bounding box: (min_lon, min_lat, max_lon, max_lat)
BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)

# All 23 OSM feature types organized by category
OSM_FEATURES = {
    'Original Amenities (10)': [
        'hospitals',
        'toilets',
        'pharmacies',
        'fire_stations',
        'police_stations',
        'parks',
        'restaurants',
        'transport_stops',
        'schools',
        'parking'
    ],
    'Medical/Health (4)': [
        'doctors',
        'dentists',
        'clinics',
        'veterinary'
    ],
    'Education (2)': [
        'universities',
        'libraries'
    ],
    'Commerce & Services (4)': [
        'supermarkets',
        'banks',
        'atm',
        'post_offices'
    ],
    'Recreation (3)': [
        'museums',
        'theatres',
        'gyms'
    ],
    'Land Use (2)': [
        'forests',
        'water_bodies'
    ],
    'Administrative (1)': [
        'districts'
    ]
}

def main():
    """Download all OSM datasets for Berlin"""

    print("=" * 80)
    print("DOWNLOADING OSM DATA FOR BERLIN - ALL 23 FEATURE TYPES")
    print("=" * 80)
    print(f"\nBerlin Bounding Box: {BERLIN_BBOX}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Initialize loader
    loader = OSMLoader(data_dir="data/vector/osm")

    # Statistics tracking
    total_features = 0
    successful = []
    failed = []

    # Download datasets by category
    all_feature_names = []
    for category, features in OSM_FEATURES.items():
        all_feature_names.extend(features)

    # Display plan
    print("Download Plan:")
    for category, features in OSM_FEATURES.items():
        print(f"\n  {category}:")
        for feature in features:
            print(f"    - {feature}")

    print(f"\n{'=' * 80}")
    print("Starting downloads...")
    print(f"{'=' * 80}\n")

    # Download each feature type
    for idx, feature in enumerate(all_feature_names, 1):
        print(f"[{idx}/{len(all_feature_names)}] Downloading {feature}...", end=" ")

        try:
            # Get feature name in singular form for query
            feature_key = feature.rstrip('s') if feature.endswith('s') else feature

            # Query Overpass API
            gdf = loader.query_overpass(
                bbox=BERLIN_BBOX,
                features=[feature_key],
                timeout=180
            )

            if len(gdf) == 0:
                print(f"⚠️  No features found (0 records)")
                failed.append((feature, "Empty result"))
                continue

            # Save to file
            output_file = loader.data_dir / f"berlin_{feature}.geojson"
            gdf.to_file(output_file, driver='GeoJSON')

            total_features += len(gdf)
            successful.append((feature, len(gdf)))

            print(f"✅ {len(gdf):,} features")

        except Exception as e:
            print(f"❌ Error: {str(e)[:50]}")
            failed.append((feature, str(e)[:100]))

    # Print summary
    print(f"\n{'=' * 80}")
    print("DOWNLOAD SUMMARY")
    print(f"{'=' * 80}\n")

    print("Successfully Downloaded:")
    for feature, count in successful:
        print(f"  ✅ {feature:20s}: {count:7,} features")

    if failed:
        print(f"\nFailed Downloads ({len(failed)}):")
        for feature, reason in failed:
            print(f"  ❌ {feature:20s}: {reason[:50]}")

    print(f"\n{'-' * 80}")
    print(f"Total Datasets: {len(successful)}/{len(all_feature_names)}")
    print(f"Total Features: {total_features:,}")
    print(f"Success Rate: {len(successful)/len(all_feature_names)*100:.1f}%")
    print(f"Data Directory: {loader.data_dir}")
    print(f"{'=' * 80}\n")

    return len(failed) == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
