"""
Test NDVI Implementation
Quick verification that Phase 1 components are working
"""

import sys
from pathlib import Path
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all new modules can be imported"""
    print("🧪 Testing imports...")

    try:
        from app.utils.raster_operations import RasterOperations
        print("  ✅ RasterOperations imported")
    except ImportError as e:
        print(f"  ❌ Failed to import RasterOperations: {e}")
        return False

    try:
        from app.utils.spatial_engine import SpatialEngine
        print("  ✅ SpatialEngine imported")
    except ImportError as e:
        print(f"  ❌ Failed to import SpatialEngine: {e}")
        return False

    try:
        from app.routes.raster import router
        print("  ✅ Raster router imported")
    except ImportError as e:
        print(f"  ❌ Failed to import raster router: {e}")
        return False

    return True


def test_raster_operations():
    """Test core raster operations"""
    print("\n🧪 Testing RasterOperations class...")

    from app.utils.raster_operations import RasterOperations

    ops = RasterOperations()
    print("  ✅ RasterOperations instance created")

    # Test NDVI computation with numpy arrays
    print("  📊 Testing NDVI computation...")
    red = np.array([[100, 150, 200], [120, 160, 210], [130, 170, 220]])
    nir = np.array([[200, 250, 300], [220, 260, 310], [230, 270, 320]])

    ndvi = ops.compute_ndvi(red, nir)

    if ndvi is not None and ndvi.shape == red.shape:
        print(f"  ✅ NDVI computed: shape={ndvi.shape}, range=[{ndvi.min():.3f}, {ndvi.max():.3f}]")
    else:
        print(f"  ❌ NDVI computation failed")
        return False

    # Test NDVI difference
    print("  📊 Testing NDVI difference...")
    ndvi_t2 = ndvi + 0.1  # Simulate vegetation gain
    diff = ops.ndvi_difference(ndvi, ndvi_t2)

    if diff is not None:
        print(f"  ✅ NDVI difference computed: mean={diff.mean():.3f}")
    else:
        print(f"  ❌ NDVI difference failed")
        return False

    return True


def test_spatial_engine_raster():
    """Test spatial engine raster capabilities"""
    print("\n🧪 Testing SpatialEngine raster operations...")

    from app.utils.spatial_engine import SpatialEngine

    engine = SpatialEngine(data_dir="./data")
    print("  ✅ SpatialEngine instance created")

    # Check if raster_ops property works
    try:
        _ = engine.raster_ops
        print("  ✅ Raster operations lazy-loaded successfully")
    except Exception as e:
        print(f"  ❌ Failed to load raster operations: {e}")
        return False

    return True


def test_api_routes():
    """Test API route configuration"""
    print("\n🧪 Testing API routes...")

    try:
        from app.main import app

        # Get all routes
        routes = [route.path for route in app.routes]

        # Check for raster endpoints
        raster_routes = [r for r in routes if '/raster' in r]

        if raster_routes:
            print(f"  ✅ Found {len(raster_routes)} raster endpoints:")
            for route in raster_routes[:5]:  # Show first 5
                print(f"     - {route}")
            if len(raster_routes) > 5:
                print(f"     ... and {len(raster_routes) - 5} more")
        else:
            print("  ❌ No raster routes found")
            return False

    except Exception as e:
        print(f"  ❌ Failed to check routes: {e}")
        return False

    return True


def test_dependencies():
    """Test that required dependencies are installed"""
    print("\n🧪 Testing dependencies...")

    dependencies = {
        'rasterio': 'Raster I/O',
        'geopandas': 'Geospatial DataFrames',
        'numpy': 'Numerical computing',
        'shapely': 'Geometric objects',
    }

    all_ok = True
    for package, description in dependencies.items():
        try:
            __import__(package)
            print(f"  ✅ {package} - {description}")
        except ImportError:
            print(f"  ❌ {package} - {description} (NOT INSTALLED)")
            all_ok = False

    # Check optional dependencies
    optional = ['rasterstats', 'xarray', 'scipy']
    print("\n  Optional dependencies:")
    for package in optional:
        try:
            __import__(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ⚠️  {package} (optional, not installed)")

    return all_ok


def test_file_structure():
    """Test that expected files exist"""
    print("\n🧪 Testing file structure...")

    expected_files = [
        "app/utils/raster_operations.py",
        "app/routes/raster.py",
        "examples/04_ndvi_change_detection.py",
        "IMPLEMENTATION_PLAN.md",
        "PHASE1_NDVI_COMPLETE.md",
        "NDVI_QUICK_START.md"
    ]

    all_exist = True
    for filepath in expected_files:
        path = Path(filepath)
        if path.exists():
            size = path.stat().st_size
            print(f"  ✅ {filepath} ({size:,} bytes)")
        else:
            print(f"  ❌ {filepath} (NOT FOUND)")
            all_exist = False

    return all_exist


def test_data_directory():
    """Test data directory structure"""
    print("\n🧪 Testing data directory structure...")

    expected_dirs = [
        "data/raster",
        "data/raster/ndvi_timeseries",
        "data/raster/sentinel2",
        "data/raster/dem",
        "data/vector/osm",
        "data/metadata"
    ]

    for dirpath in expected_dirs:
        path = Path(dirpath)
        if path.exists() and path.is_dir():
            print(f"  ✅ {dirpath}/")
        else:
            print(f"  ⚠️  {dirpath}/ (not created yet)")

    return True  # Non-critical


def main():
    """Run all tests"""
    print("=" * 60)
    print("NDVI IMPLEMENTATION VERIFICATION TEST")
    print("=" * 60)

    tests = [
        ("Dependencies", test_dependencies),
        ("Imports", test_imports),
        ("RasterOperations", test_raster_operations),
        ("SpatialEngine", test_spatial_engine_raster),
        ("API Routes", test_api_routes),
        ("File Structure", test_file_structure),
        ("Data Directory", test_data_directory)
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"\n  ❌ Test '{test_name}' crashed: {e}")
            results[test_name] = False

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Implementation is working correctly.")
        print("\n📚 Next steps:")
        print("  1. Run example: python examples/04_ndvi_change_detection.py")
        print("  2. Start API: python -m uvicorn app.main:app --reload")
        print("  3. Check docs: http://localhost:8000/docs")
    else:
        print("⚠️  Some tests failed. Review errors above.")
        print("\n🔧 Troubleshooting:")
        print("  1. Install missing dependencies: pip install -r requirements.txt")
        print("  2. Verify file paths are correct")
        print("  3. Check import paths in your IDE")

    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
