#!/usr/bin/env python3
"""
DEM Analysis Examples - Quick reference for common tasks
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.dem_analysis import DEMAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def example_1_basic_terrain_analysis():
    """Example 1: Basic terrain analysis"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 1: Basic Terrain Analysis")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"

    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        logger.info("Please run: python scripts/download_berlin_dem.py")
        return

    # Initialize analyzer
    analyzer = DEMAnalyzer(dem_path)

    # Get terrain statistics
    stats = analyzer.compute_terrain_statistics()
    logger.info(f"\nTerrain Statistics:")
    logger.info(f"  Elevation: {stats['elevation']['min']:.1f}m - {stats['elevation']['max']:.1f}m")
    logger.info(f"  Average slope: {stats['slope']['mean']:.2f}°")
    logger.info(f"  Slope range: {stats['slope']['min']:.2f}° - {stats['slope']['max']:.2f}°")
    logger.info(f"  Total relief: {stats['relief']:.1f}m")


def example_2_single_analysis():
    """Example 2: Compute single terrain derivative"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 2: Compute Single Analysis")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)

    # Compute slope and save
    slope = analyzer.compute_slope(
        output_path=Path("data/raster/dem/example_slope.tif")
    )
    logger.info(f"Slope computed and saved!")


def example_3_hydrological_analysis():
    """Example 3: Hydrological analysis"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 3: Hydrological Analysis")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)

    # Compute flow direction
    logger.info("Computing flow direction...")
    flow_dir = analyzer.compute_flow_direction()

    # Compute flow accumulation
    logger.info("Computing flow accumulation...")
    flow_accum = analyzer.compute_flow_accumulation(flow_direction=flow_dir)

    # Identify streams
    logger.info("Identifying streams...")
    streams = analyzer.identify_streams(
        flow_accumulation=flow_accum,
        threshold=1000
    )
    logger.info(f"Found {len(streams)} stream features")


def example_4_urban_planning():
    """Example 4: Urban planning analysis"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 4: Urban Planning Analysis")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)

    # Development suitability (gentle slopes)
    logger.info("Finding development-suitable areas (slope ≤ 20°)...")
    suitable = analyzer.analyze_development_suitability(max_slope=20.0)
    logger.info(f"Found {len(suitable)} suitable areas")
    logger.info(f"Total area: {suitable.geometry.area.sum() / 1000000:.1f} km²")


def example_5_flood_risk():
    """Example 5: Flood risk assessment"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 5: Flood Risk Assessment")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)

    # Compute flow accumulation (required for flood risk)
    logger.info("Computing flow accumulation...")
    flow_accum = analyzer.compute_flow_accumulation()

    # Assess flood risk
    logger.info("Assessing flood risk...")
    flood_areas = analyzer.analyze_flood_risk(flow_accumulation=flow_accum)
    logger.info(f"Found {len(flood_areas)} flood-risk areas")
    logger.info(f"Total flood-risk area: {flood_areas.geometry.area.sum() / 1000000:.1f} km²")


def example_6_custom_parameters():
    """Example 6: Custom analysis with different parameters"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 6: Custom Parameters")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)

    # Terrain classification with custom thresholds
    logger.info("Classifying terrain...")
    terrain = analyzer.classify_terrain()
    logger.info("Terrain classes: 1=Flat, 2=Rolling, 3=Steep, 4=Very Steep")

    # Flow accumulation for stream detection
    flow_accum = analyzer.compute_flow_accumulation()

    # Identify streams with custom threshold
    logger.info("\nIdentifying streams with different thresholds:")
    for threshold in [500, 1000, 2000]:
        streams = analyzer.identify_streams(
            flow_accumulation=flow_accum,
            threshold=threshold
        )
        logger.info(f"  Threshold {threshold}: {len(streams)} streams")


def example_7_batch_processing():
    """Example 7: Batch processing multiple outputs"""
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 7: Batch Processing")
    logger.info("=" * 60)

    dem_path = "data/raster/dem/berlin_dem.tif"
    if not Path(dem_path).exists():
        logger.warning(f"DEM not found at {dem_path}")
        return

    analyzer = DEMAnalyzer(dem_path)
    output_dir = Path("data/raster/dem/batch_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute all terrain derivatives
    analyses = [
        ("slope", lambda: analyzer.compute_slope()),
        ("aspect", lambda: analyzer.compute_aspect()),
        ("hillshade", lambda: analyzer.compute_hillshade()),
        ("terrain_classification", lambda: analyzer.classify_terrain()),
    ]

    for name, func in analyses:
        logger.info(f"Computing {name}...")
        try:
            result = func()
            logger.info(f"  ✓ {name}")
        except Exception as e:
            logger.error(f"  ✗ {name}: {e}")


if __name__ == "__main__":
    logger.info("DEM Analysis Examples")
    logger.info("=" * 60)
    logger.info("\nAvailable examples:")
    logger.info("  1. Basic terrain analysis")
    logger.info("  2. Compute single analysis")
    logger.info("  3. Hydrological analysis")
    logger.info("  4. Urban planning analysis")
    logger.info("  5. Flood risk assessment")
    logger.info("  6. Custom parameters")
    logger.info("  7. Batch processing")

    # Run all examples
    try:
        example_1_basic_terrain_analysis()
        example_2_single_analysis()
        example_3_hydrological_analysis()
        example_4_urban_planning()
        example_5_flood_risk()
        example_6_custom_parameters()
        example_7_batch_processing()

        logger.info("\n" + "=" * 60)
        logger.info("All examples completed!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()
