#!/usr/bin/env python
"""
Download OSM landuse data for Berlin
Includes residential, commercial, industrial, agricultural, etc.
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


def main():
    """Download landuse data for Berlin"""

    print("=" * 80)
    print("DOWNLOADING OSM LANDUSE DATA FOR BERLIN")
    print("=" * 80)
    print(f"\nBerlin Bounding Box: {BERLIN_BBOX}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Initialize loader
    loader = OSMLoader(data_dir="data/vector/osm")

    filepath = loader.data_dir / "berlin_landuse.geojson"

    # Skip if already exists
    if filepath.exists():
        print(f"⏭️  Landuse data already exists at {filepath}")
        print(f"   To re-download, delete the file and run this script again\n")
        return True

    print(f"Downloading landuse data...\n")
    print(f"This may take a few minutes. Landuse areas can be large polygons.")
    print(f"Processing timeout: 180 seconds\n")

    try:
        start_time = time.time()

        # Download with extended timeout (landuse can be large)
        gdf = loader.query_overpass(
            bbox=BERLIN_BBOX,
            features=['landuse'],
            timeout=180
        )

        elapsed_download = time.time() - start_time

        if len(gdf) == 0:
            print(f"❌ No landuse features found in Berlin")
            return False

        print(f"\n✅ Downloaded {len(gdf):,} landuse areas in {elapsed_download:.1f}s")

        # Save to file
        print(f"\nSaving to {filepath}...", end="", flush=True)
        start_save = time.time()

        gdf.to_file(filepath, driver='GeoJSON')

        elapsed_save = time.time() - start_save
        print(f" ✅ ({elapsed_save:.1f}s)")

        # Print statistics
        print(f"\n" + "=" * 80)
        print("DOWNLOAD SUMMARY")
        print("=" * 80)

        print(f"\nData Statistics:")
        print(f"  Total features: {len(gdf):,}")
        print(f"  Geometry types: {gdf.geometry.type.unique().tolist()}")
        print(f"  CRS: {gdf.crs}")

        if 'landuse' in gdf.columns:
            landuse_types = gdf['landuse'].value_counts()
            print(f"\nLanduse types found:")
            for ltype, count in landuse_types.items():
                print(f"  - {ltype}: {count:,} areas")

        print(f"\nFile Information:")
        print(f"  Path: {filepath}")
        print(f"  Size: {filepath.stat().st_size / 1024 / 1024:.1f} MB")

        total_time = elapsed_download + elapsed_save
        print(f"\n{'-' * 80}")
        print(f"Total Time: {total_time:.1f} seconds")
        print(f"{'=' * 80}\n")

        print("✅ Next step: Load data into PostGIS")
        print(f"   python scripts/load_landuse.py\n")

        return True

    except Exception as e:
        print(f"❌ Error downloading landuse data: {str(e)}")
        logger.exception("Failed to download landuse data")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by user")
        sys.exit(1)
