"""
Test download: Small area, single date
Quick test before downloading full Berlin datasets
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.download_real_sentinel2 import RealSentinel2Loader

print("=" * 60)
print("🧪 TEST DOWNLOAD - Small Area")
print("=" * 60)

# Very small area for quick test (0.02 x 0.01 degrees ~ 2x1 km)
BERLIN_TINY = (13.35, 52.51, 13.37, 52.52)

print("\nTest Configuration:")
print(f"  Area: ~2x1 km in Berlin (Tiergarten)")
print(f"  BBox: {BERLIN_TINY}")
print(f"  Date: July 2024")
print(f"  Expected download size: < 5 MB")
print(f"  Expected time: < 30 seconds")

input("\nPress Enter to start test download...")

loader = RealSentinel2Loader()

# Download single NDVI
print("\n🔄 Downloading test NDVI...")

ndvi_path = loader.download_and_compute_ndvi(
    region_name="berlin_test",
    bbox=BERLIN_TINY,
    date="2024-07-15",
    max_cloud=30.0
)

if ndvi_path and ndvi_path.exists():
    size_mb = ndvi_path.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 60)
    print("✅ TEST DOWNLOAD SUCCESSFUL!")
    print("=" * 60)
    print(f"📁 File: {ndvi_path}")
    print(f"📊 Size: {size_mb:.2f} MB")
    print(f"🌍 Resolution: 10m Sentinel-2")

    # Verify we can read it
    import rasterio
    with rasterio.open(ndvi_path) as src:
        ndvi = src.read(1)
        print(f"🔢 Dimensions: {ndvi.shape}")
        print(f"📈 NDVI range: [{ndvi[ndvi != -9999].min():.3f}, {ndvi[ndvi != -9999].max():.3f}]")

    print("\n✅ Ready for full downloads!")
    print("\nNext step:")
    print("  python scripts/download_real_sentinel2.py")

else:
    print("\n❌ Test download failed")
    print("Check the error messages above")

print("=" * 60)
