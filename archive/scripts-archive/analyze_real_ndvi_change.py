"""
NDVI Change Detection with Real Sentinel-2 Data
Analyzes Berlin vegetation change from 2018 to 2024
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.raster_operations import RasterOperations
import geopandas as gpd
import rasterio
import numpy as np

print("=" * 60)
print("🌿 REAL NDVI CHANGE DETECTION - BERLIN")
print("   2018-07-16 → 2024-07-21")
print("=" * 60)

# Paths to real NDVI data
ndvi_2018 = Path("data/raster/ndvi_timeseries/berlin_ndvi_20180716.tif")
ndvi_2024 = Path("data/raster/ndvi_timeseries/berlin_ndvi_20240721.tif")

# Check files exist
if not ndvi_2018.exists():
    print(f"❌ 2018 NDVI not found: {ndvi_2018}")
    print("Run: python scripts/download_berlin_ndvi.py --year 2018")
    sys.exit(1)

if not ndvi_2024.exists():
    print(f"❌ 2024 NDVI not found: {ndvi_2024}")
    print("Run: python scripts/download_berlin_ndvi.py --year 2024")
    sys.exit(1)

print(f"\n✅ Found 2018 NDVI: {ndvi_2018}")
print(f"✅ Found 2024 NDVI: {ndvi_2024}")

# Load file info
print("\n📊 Dataset Information:")
print("-" * 60)

with rasterio.open(ndvi_2018) as src:
    print(f"2018 NDVI:")
    print(f"  Size: {src.width} x {src.height} pixels")
    print(f"  Resolution: ~{src.res[0] * 111000:.0f}m")
    print(f"  CRS: {src.crs}")
    ndvi_2018_data = src.read(1)
    valid_2018 = ndvi_2018_data[ndvi_2018_data != -9999]
    print(f"  NDVI range: [{valid_2018.min():.3f}, {valid_2018.max():.3f}]")
    print(f"  Mean NDVI: {valid_2018.mean():.3f}")

with rasterio.open(ndvi_2024) as src:
    print(f"\n2024 NDVI:")
    print(f"  Size: {src.width} x {src.height} pixels")
    print(f"  Resolution: ~{src.res[0] * 111000:.0f}m")
    print(f"  CRS: {src.crs}")
    ndvi_2024_data = src.read(1)
    valid_2024 = ndvi_2024_data[ndvi_2024_data != -9999]
    print(f"  NDVI range: [{valid_2024.min():.3f}, {valid_2024.max():.3f}]")
    print(f"  Mean NDVI: {valid_2024.mean():.3f}")

print("-" * 60)

# Initialize raster operations
ops = RasterOperations()

# Compute NDVI difference
print("\n🔄 Computing NDVI difference...")

diff_path = Path("data/raster/ndvi_timeseries/berlin_ndvi_diff_2018_2024_real.tif")

try:
    diff = ops.ndvi_difference(
        ndvi_t1=ndvi_2018,
        ndvi_t2=ndvi_2024,
        output_path=diff_path
    )
    print(f"✅ NDVI difference saved: {diff_path}")

    # Load and analyze difference
    with rasterio.open(diff_path) as src:
        diff_data = src.read(1)
        valid_diff = diff_data[diff_data != -9999]

        print(f"\n📊 Change Statistics:")
        print(f"  Mean change: {valid_diff.mean():.3f}")
        print(f"  Std dev: {valid_diff.std():.3f}")
        print(f"  Min change: {valid_diff.min():.3f}")
        print(f"  Max change: {valid_diff.max():.3f}")

        # Count pixels by change category
        loss_severe = (valid_diff < -0.3).sum()
        loss_moderate = ((valid_diff >= -0.3) & (valid_diff < -0.1)).sum()
        stable = ((valid_diff >= -0.1) & (valid_diff <= 0.1)).sum()
        gain_moderate = ((valid_diff > 0.1) & (valid_diff <= 0.3)).sum()
        gain_high = (valid_diff > 0.3).sum()

        total = len(valid_diff)

        print(f"\n📈 Change Distribution:")
        print(f"  Severe loss (< -0.3):    {loss_severe:8,} pixels ({loss_severe/total*100:5.2f}%)")
        print(f"  Moderate loss (-0.3 to -0.1): {loss_moderate:8,} pixels ({loss_moderate/total*100:5.2f}%)")
        print(f"  Stable (-0.1 to 0.1):    {stable:8,} pixels ({stable/total*100:5.2f}%)")
        print(f"  Moderate gain (0.1 to 0.3):  {gain_moderate:8,} pixels ({gain_moderate/total*100:5.2f}%)")
        print(f"  High gain (> 0.3):       {gain_high:8,} pixels ({gain_high/total*100:5.2f}%)")

except Exception as e:
    print(f"❌ Error computing difference: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Detect vegetation loss
print("\n🔍 Detecting vegetation loss areas...")

try:
    loss_areas = ops.detect_vegetation_loss(
        ndvi_diff=diff_path,
        threshold=-0.2,
        min_area_pixels=100
    )

    print(f"✅ Detected {len(loss_areas)} loss polygons")

    if len(loss_areas) > 0:
        # Save loss areas
        output_path = Path("data/results/berlin_vegetation_loss_real_2018_2024.geojson")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        loss_areas.to_file(output_path, driver="GeoJSON")
        print(f"💾 Saved loss areas: {output_path}")

        # Calculate total area (convert to projected CRS for accurate area)
        loss_areas_proj = loss_areas.to_crs("EPSG:3857")  # Web Mercator for area calculation
        total_area_m2 = loss_areas_proj.geometry.area.sum()
        total_area_km2 = total_area_m2 / 1_000_000

        print(f"\n📊 Vegetation Loss Summary:")
        print(f"  Total loss polygons: {len(loss_areas):,}")
        print(f"  Total loss area: {total_area_km2:.2f} km²")
        print(f"  Average polygon size: {total_area_m2/len(loss_areas):.0f} m²")

except Exception as e:
    print(f"❌ Error detecting loss: {e}")
    import traceback
    traceback.print_exc()

# Detect vegetation gain
print("\n🔍 Detecting vegetation gain areas...")

try:
    gain_areas = ops.detect_vegetation_gain(
        ndvi_diff=diff_path,
        threshold=0.2,
        min_area_pixels=100
    )

    print(f"✅ Detected {len(gain_areas)} gain polygons")

    if len(gain_areas) > 0:
        # Save gain areas
        output_path = Path("data/results/berlin_vegetation_gain_real_2018_2024.geojson")
        gain_areas.to_file(output_path, driver="GeoJSON")
        print(f"💾 Saved gain areas: {output_path}")

        # Calculate total area
        gain_areas_proj = gain_areas.to_crs("EPSG:3857")
        total_area_m2 = gain_areas_proj.geometry.area.sum()
        total_area_km2 = total_area_m2 / 1_000_000

        print(f"\n📊 Vegetation Gain Summary:")
        print(f"  Total gain polygons: {len(gain_areas):,}")
        print(f"  Total gain area: {total_area_km2:.2f} km²")

except Exception as e:
    print(f"❌ Error detecting gain: {e}")

# Final summary
print("\n" + "=" * 60)
print("✅ REAL DATA ANALYSIS COMPLETE")
print("=" * 60)
print("\n📁 Output Files:")
print(f"  1. NDVI Difference: {diff_path}")
print(f"  2. Loss Areas: data/results/berlin_vegetation_loss_real_2018_2024.geojson")
print(f"  3. Gain Areas: data/results/berlin_vegetation_gain_real_2018_2024.geojson")
print("\n🗺️  Visualization:")
print("  - Open in QGIS or view at http://geojson.io")
print("  - Or use: python -m uvicorn app.main:app --reload")
print("=" * 60)
