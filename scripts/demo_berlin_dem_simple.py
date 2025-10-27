#!/usr/bin/env python3
"""
Simple Berlin DEM Demo - Quick visualization and analysis
No heavy flow accumulation algorithms
"""

import logging
import sys
import json
from pathlib import Path
import rasterio
import numpy as np
import geopandas as gpd
from shapely.geometry import box

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.dem_analysis import DEMAnalyzer

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def demo_berlin_dem():
    """Simple demo of Berlin DEM analysis"""

    dem_path = Path("data/raster/dem/berlin_dem.tif")

    if not dem_path.exists():
        logger.error(f"✗ DEM file not found: {dem_path}")
        logger.info("Please run: python scripts/download_berlin_dem.py")
        return False

    output_dir = Path("data/raster/dem/demo_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("=" * 70)
        logger.info("BERLIN DEM - SIMPLE DEMO")
        logger.info("=" * 70)

        # Load and inspect DEM
        logger.info("\n[1] Loading DEM...")
        with rasterio.open(dem_path) as src:
            dem = src.read(1)
            profile = src.profile
            transform = src.transform
            crs = src.crs

        logger.info(f"✓ DEM loaded successfully")
        logger.info(f"  Dimensions: {dem.shape[0]} × {dem.shape[1]} pixels")
        logger.info(f"  Resolution: {transform.a:.1f}m per pixel")
        logger.info(f"  Projection: {crs}")

        # Initialize analyzer
        logger.info("\n[2] Initializing analyzer...")
        analyzer = DEMAnalyzer(dem_path)

        # Compute terrain statistics
        logger.info("\n[3] Computing terrain statistics...")
        stats = analyzer.compute_terrain_statistics()

        logger.info(f"✓ Terrain Statistics:")
        logger.info(f"  Elevation range: {stats['elevation']['min']:.1f}m - {stats['elevation']['max']:.1f}m")
        logger.info(f"  Average elevation: {stats['elevation']['mean']:.1f}m")
        logger.info(f"  Relief (max-min): {stats['relief']:.1f}m")
        logger.info(f"  Slope range: {stats['slope']['min']:.2f}° - {stats['slope']['max']:.2f}°")
        logger.info(f"  Average slope: {stats['slope']['mean']:.2f}°")

        # Save stats
        stats_path = output_dir / "terrain_statistics.json"
        with open(stats_path, 'w') as f:
            json.dump(stats, f, indent=2)
        logger.info(f"  Saved to: {stats_path}")

        # Compute slope
        logger.info("\n[4] Computing slope map...")
        slope_path = output_dir / "berlin_slope.tif"
        slope = analyzer.compute_slope(output_path=slope_path)
        logger.info(f"✓ Saved slope map: {slope_path}")

        # Compute aspect
        logger.info("\n[5] Computing aspect map...")
        aspect_path = output_dir / "berlin_aspect.tif"
        aspect = analyzer.compute_aspect(output_path=aspect_path)
        logger.info(f"✓ Saved aspect map: {aspect_path}")

        # Compute hillshade
        logger.info("\n[6] Computing hillshade (3D visualization)...")
        hillshade_path = output_dir / "berlin_hillshade.tif"
        hillshade = analyzer.compute_hillshade(output_path=hillshade_path)
        logger.info(f"✓ Saved hillshade: {hillshade_path}")

        # Terrain classification
        logger.info("\n[7] Classifying terrain...")
        terrain_class_path = output_dir / "berlin_terrain_classification.tif"
        terrain = analyzer.classify_terrain(output_path=terrain_class_path)
        logger.info(f"✓ Saved terrain classification: {terrain_class_path}")
        logger.info(f"  Classes: 1=Flat, 2=Rolling, 3=Steep, 4=Very Steep")

        # Development suitability (fast - no flow algorithms)
        logger.info("\n[8] Finding development-suitable areas...")
        dev_suit_path = output_dir / "berlin_development_suitability.geojson"
        dev_result = analyzer.analyze_development_suitability(
            max_slope=20.0,
            output_path=dev_suit_path
        )
        # Load the saved GeoDataFrame to get statistics
        dev_areas = gpd.read_file(dev_suit_path)
        logger.info(f"✓ Found {len(dev_areas)} suitable areas")
        if len(dev_areas) > 0:
            total_area_km2 = dev_areas.geometry.area.sum() / 1_000_000
            logger.info(f"  Total suitable area: {total_area_km2:.1f} km²")

        # Summary report
        logger.info("\n" + "=" * 70)
        logger.info("DEMO COMPLETE - SUMMARY")
        logger.info("=" * 70)

        logger.info(f"\nGenerated files in {output_dir}:")
        logger.info("  Terrain Analysis:")
        logger.info(f"    ✓ {slope_path.name}")
        logger.info(f"    ✓ {aspect_path.name}")
        logger.info(f"    ✓ {hillshade_path.name}")
        logger.info(f"    ✓ {terrain_class_path.name}")
        logger.info(f"    ✓ {stats_path.name}")
        logger.info("  Urban Planning:")
        logger.info(f"    ✓ {dev_suit_path.name}")

        logger.info("\nNext steps:")
        logger.info("  1. View files: ls -lh " + str(output_dir))
        logger.info("  2. Create visualizations: python scripts/visualize_dem_analysis.py")
        logger.info("  3. Run full analysis (with hydrological): python scripts/analyze_berlin_dem.py")
        logger.info("     (Note: Full analysis takes ~10-15 minutes)")

        logger.info("\nPython API Example:")
        logger.info("  from app.utils.dem_analysis import DEMAnalyzer")
        logger.info("  analyzer = DEMAnalyzer('data/raster/dem/berlin_dem.tif')")
        logger.info("  stats = analyzer.compute_terrain_statistics()")
        logger.info("  suitable = analyzer.analyze_development_suitability(max_slope=15)")

        return True

    except Exception as e:
        logger.error(f"✗ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = demo_berlin_dem()
    sys.exit(0 if success else 1)
