"""
Quick test: Search for Sentinel-2 data without downloading
This verifies the API works before attempting full downloads
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pystac_client import Client
import planetary_computer as pc
from datetime import datetime, timedelta

print("=" * 60)
print("🔍 TESTING SENTINEL-2 SEARCH")
print("=" * 60)

# Small test area in Berlin (Tiergarten park)
BERLIN_SMALL = (13.35, 52.51, 13.37, 52.52)

print("\nTest Configuration:")
print(f"  Region: Small area in Berlin (Tiergarten)")
print(f"  BBox: {BERLIN_SMALL}")
print(f"  Date range: July 2024 (± 7 days)")
print(f"  Max cloud cover: 30%")

print("\n🔄 Connecting to Planetary Computer...")

try:
    # Connect to catalog
    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace
    )
    print("✅ Connected successfully")

    # Search for recent data (July 2024)
    print("\n🔍 Searching for Sentinel-2 scenes...")

    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=BERLIN_SMALL,
        datetime="2024-07-08/2024-07-22",  # July 15, 2024 ± 7 days
        query={"eo:cloud_cover": {"lt": 30}}
    )

    items = list(search.items())

    print(f"\n✅ Found {len(items)} scenes")

    if len(items) > 0:
        print("\n📊 Available scenes:")
        print("-" * 60)

        for i, item in enumerate(items[:5], 1):  # Show first 5
            scene_id = item.id
            date = item.properties.get('datetime', 'N/A')[:10]
            cloud = item.properties.get('eo:cloud_cover', 'N/A')

            print(f"\n{i}. Scene ID: {scene_id}")
            print(f"   Date: {date}")
            print(f"   Cloud cover: {cloud:.1f}%")

            # Check available bands
            if 'B04' in item.assets and 'B08' in item.assets:
                print(f"   ✅ Red (B04) and NIR (B08) bands available")

                # Show band info
                b04 = item.assets['B04']
                print(f"   B04 (Red): {b04.title}")

                b08 = item.assets['B08']
                print(f"   B08 (NIR): {b08.title}")
            else:
                print(f"   ⚠️  Missing required bands")

        print("\n" + "-" * 60)
        print("\n🎉 SUCCESS! Sentinel-2 API is working correctly.")
        print("\n✅ Ready to download real data!")
        print("\nNext step:")
        print("  python scripts/download_real_sentinel2.py")

    else:
        print("\n⚠️  No scenes found for this date range.")
        print("Suggestions:")
        print("  - Try a different date")
        print("  - Increase max cloud cover")
        print("  - Expand the search window")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
