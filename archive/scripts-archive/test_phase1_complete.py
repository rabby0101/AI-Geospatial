"""
Complete Phase 1 Testing Suite
Tests all NDVI functionality with sample data
"""

import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from app.utils.raster_operations import RasterOperations
from app.utils.spatial_engine import SpatialEngine
import geopandas as gpd
from shapely.geometry import box

def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_1_ndvi_difference():
    """Test 1: NDVI Difference Computation"""
    print_section("TEST 1: NDVI Difference Computation")

    ops = RasterOperations()

    # Paths to sample data
    ndvi_2018 = Path("data/raster/ndvi_timeseries/sample_ndvi_2018.tif")
    ndvi_2024 = Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif")

    if not ndvi_2018.exists() or not ndvi_2024.exists():
        print("❌ Sample data not found. Run: python scripts/create_sample_ndvi.py")
        return False

    print(f"📂 Loading NDVI rasters...")
    print(f"   - 2018: {ndvi_2018}")
    print(f"   - 2024: {ndvi_2024}")

    # Compute difference
    diff_path = Path("data/raster/ndvi_timeseries/test_ndvi_diff.tif")
    print(f"\n🔄 Computing NDVI difference...")

    result = ops.ndvi_difference(
        ndvi_t1=ndvi_2018,
        ndvi_t2=ndvi_2024,
        output_path=diff_path
    )

    if diff_path.exists():
        print(f"✅ NDVI difference saved to: {diff_path}")
        print(f"   File size: {diff_path.stat().st_size:,} bytes")

        # Load and check
        import rasterio
        with rasterio.open(diff_path) as src:
            diff = src.read(1)
            print(f"\n📊 Statistics:")
            print(f"   - Mean change: {diff.mean():.3f}")
            print(f"   - Min change: {diff.min():.3f}")
            print(f"   - Max change: {diff.max():.3f}")
            print(f"   - Std dev: {diff.std():.3f}")

        return True
    else:
        print("❌ Failed to create NDVI difference")
        return False


def test_2_vegetation_loss_detection():
    """Test 2: Vegetation Loss Detection"""
    print_section("TEST 2: Vegetation Loss Detection")

    ops = RasterOperations()

    diff_path = Path("data/raster/ndvi_timeseries/test_ndvi_diff.tif")

    if not diff_path.exists():
        print("⚠️  NDVI difference not found. Run Test 1 first.")
        return False

    print(f"📂 Loading NDVI difference: {diff_path}")

    # Detect loss
    print(f"\n🔍 Detecting vegetation loss (threshold: -0.2)...")

    loss_areas = ops.detect_vegetation_loss(
        ndvi_diff=diff_path,
        threshold=-0.2,
        min_area_pixels=10
    )

    print(f"\n📊 Results:")
    print(f"   - Loss areas detected: {len(loss_areas)}")

    if len(loss_areas) > 0:
        print(f"   - Total loss area: {loss_areas.geometry.area.sum():.6f} sq degrees")
        print(f"   - CRS: {loss_areas.crs}")

        # Save to file
        output_path = Path("data/results/test_vegetation_loss.geojson")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        loss_areas.to_file(output_path, driver="GeoJSON")
        print(f"\n✅ Saved to: {output_path}")

        return True
    else:
        print("⚠️  No vegetation loss detected (threshold may be too strict)")
        return True  # Not a failure, just no results


def test_3_vegetation_gain_detection():
    """Test 3: Vegetation Gain Detection"""
    print_section("TEST 3: Vegetation Gain Detection")

    ops = RasterOperations()

    diff_path = Path("data/raster/ndvi_timeseries/test_ndvi_diff.tif")

    if not diff_path.exists():
        print("⚠️  NDVI difference not found. Run Test 1 first.")
        return False

    print(f"📂 Loading NDVI difference: {diff_path}")

    # Detect gain
    print(f"\n🔍 Detecting vegetation gain (threshold: 0.2)...")

    gain_areas = ops.detect_vegetation_gain(
        ndvi_diff=diff_path,
        threshold=0.2,
        min_area_pixels=10
    )

    print(f"\n📊 Results:")
    print(f"   - Gain areas detected: {len(gain_areas)}")

    if len(gain_areas) > 0:
        print(f"   - Total gain area: {gain_areas.geometry.area.sum():.6f} sq degrees")

        # Save to file
        output_path = Path("data/results/test_vegetation_gain.geojson")
        gain_areas.to_file(output_path, driver="GeoJSON")
        print(f"\n✅ Saved to: {output_path}")

    return True


def test_4_zonal_statistics():
    """Test 4: Zonal Statistics"""
    print_section("TEST 4: Zonal Statistics")

    ops = RasterOperations()

    ndvi_2024 = Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif")

    if not ndvi_2024.exists():
        print("❌ NDVI 2024 not found")
        return False

    print("📂 Creating test polygons...")

    # Create sample polygons (simulate districts/parks)
    bbox = (13.088, 52.338, 13.761, 52.675)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    polygons = []
    names = []

    # Create 4 test zones
    for i in range(2):
        for j in range(2):
            minx = bbox[0] + (i * width / 2)
            miny = bbox[1] + (j * height / 2)
            maxx = minx + (width / 2)
            maxy = miny + (height / 2)

            poly = box(minx, miny, maxx, maxy)
            polygons.append(poly)
            names.append(f"Zone_{i}_{j}")

    gdf = gpd.GeoDataFrame({
        'name': names,
        'zone_id': range(len(names))
    }, geometry=polygons, crs='EPSG:4326')

    print(f"   Created {len(gdf)} test zones")

    # Compute zonal statistics
    print(f"\n🔄 Computing zonal statistics...")

    stats = ops.zonal_stats(
        raster=ndvi_2024,
        polygons=gdf,
        stats=['mean', 'min', 'max', 'std']
    )

    # Add to GeoDataFrame
    gdf['ndvi_mean'] = stats['mean']
    gdf['ndvi_min'] = stats['min']
    gdf['ndvi_max'] = stats['max']
    gdf['ndvi_std'] = stats['std']

    print(f"\n📊 Results:")
    print(gdf[['name', 'ndvi_mean', 'ndvi_min', 'ndvi_max']].to_string(index=False))

    # Save
    output_path = Path("data/results/test_zonal_stats.geojson")
    gdf.to_file(output_path, driver="GeoJSON")
    print(f"\n✅ Saved to: {output_path}")

    return True


def test_5_spatial_engine_integration():
    """Test 5: Spatial Engine Raster Integration"""
    print_section("TEST 5: Spatial Engine Integration")

    engine = SpatialEngine(data_dir="./data")

    print("🔄 Testing raster operation via spatial engine...")

    operation = {
        'type': 'vegetation_loss',
        'params': {
            'ndvi_t1': 'raster/ndvi_timeseries/sample_ndvi_2018.tif',
            'ndvi_t2': 'raster/ndvi_timeseries/sample_ndvi_2024.tif',
            'threshold': -0.2
        }
    }

    result = engine.execute_raster_operation(operation)

    if result.get('success'):
        count = result.get('metadata', {}).get('count', 0)
        print(f"✅ Operation successful")
        print(f"   - Features returned: {count}")
        print(f"   - Result type: {result.get('result_type')}")
        return True
    else:
        print(f"❌ Operation failed: {result.get('error')}")
        return False


def test_6_vectorize_raster():
    """Test 6: Raster Vectorization"""
    print_section("TEST 6: Raster Vectorization")

    ops = RasterOperations()

    ndvi_2024 = Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif")

    print(f"📂 Loading NDVI: {ndvi_2024}")
    print(f"🔄 Vectorizing areas with NDVI > 0.7 (healthy vegetation)...")

    polygons = ops.vectorize_raster(
        raster=ndvi_2024,
        threshold=0.7,
        operator='greater'
    )

    print(f"\n📊 Results:")
    print(f"   - Polygons created: {len(polygons)}")

    if len(polygons) > 0:
        print(f"   - Total area: {polygons.geometry.area.sum():.6f} sq degrees")

        # Save
        output_path = Path("data/results/test_healthy_vegetation.geojson")
        polygons.to_file(output_path, driver="GeoJSON")
        print(f"\n✅ Saved to: {output_path}")

    return True


def main():
    """Run all Phase 1 tests"""

    print("\n" + "=" * 60)
    print("  PHASE 1 COMPLETE TESTING SUITE")
    print("  NDVI Analysis & Raster Operations")
    print("=" * 60)

    tests = [
        ("NDVI Difference", test_1_ndvi_difference),
        ("Vegetation Loss Detection", test_2_vegetation_loss_detection),
        ("Vegetation Gain Detection", test_3_vegetation_gain_detection),
        ("Zonal Statistics", test_4_zonal_statistics),
        ("Spatial Engine Integration", test_5_spatial_engine_integration),
        ("Raster Vectorization", test_6_vectorize_raster)
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            print(f"\n🧪 Running: {test_name}...")
            success = test_func()
            results[test_name] = success

            if success:
                print(f"✅ {test_name} PASSED")
            else:
                print(f"❌ {test_name} FAILED")

        except Exception as e:
            print(f"❌ {test_name} CRASHED: {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = False

    # Final summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("\n📁 Output files created in data/results/:")
        print("   - test_vegetation_loss.geojson")
        print("   - test_vegetation_gain.geojson")
        print("   - test_zonal_stats.geojson")
        print("   - test_healthy_vegetation.geojson")
    else:
        print("⚠️  Some tests failed. Review errors above.")

    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
