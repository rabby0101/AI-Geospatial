"""
Download Berlin NDVI data for specific years
Production script for downloading real Sentinel-2 NDVI
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.download_real_sentinel2 import RealSentinel2Loader
import argparse

def main():
    parser = argparse.ArgumentParser(description='Download Berlin NDVI from Sentinel-2')
    parser.add_argument('--year', type=int, default=2024, help='Year to download (e.g., 2018, 2024)')
    parser.add_argument('--month', type=int, default=7, help='Month (1-12, default: 7 for July)')
    parser.add_argument('--day', type=int, default=15, help='Day (1-31, default: 15)')
    parser.add_argument('--cloud', type=float, default=30.0, help='Max cloud cover %')

    args = parser.parse_args()

    # Full Berlin bounding box
    BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)

    date = f"{args.year}-{args.month:02d}-{args.day:02d}"

    print("=" * 60)
    print("🛰️  BERLIN NDVI DOWNLOAD")
    print("=" * 60)
    print(f"Date: {date}")
    print(f"Max cloud cover: {args.cloud}%")
    print(f"Area: Full Berlin ({BERLIN_BBOX})")
    print(f"Expected size: 5-20 MB")
    print("=" * 60)

    loader = RealSentinel2Loader()

    # Download
    ndvi_path = loader.download_and_compute_ndvi(
        region_name="berlin",
        bbox=BERLIN_BBOX,
        date=date,
        max_cloud=args.cloud
    )

    if ndvi_path:
        print("\n✅ Download successful!")
        print(f"📁 {ndvi_path}")

        # Show file info
        size_mb = ndvi_path.stat().st_size / (1024 * 1024)
        print(f"📊 Size: {size_mb:.1f} MB")

        return 0
    else:
        print("\n❌ Download failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
