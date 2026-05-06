#!/usr/bin/env python3
"""
Comprehensive Berlin DEM Analysis Pipeline
Performs terrain, hydrological, and urban planning analyses
"""

import logging
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.dem_analysis import DEMAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyze_berlin_dem():
    """Run complete Berlin DEM analysis pipeline"""

    dem_path = Path("data/raster/dem/berlin_dem.tif")

    if not dem_path.exists():
        logger.error(f"DEM file not found: {dem_path}")
        logger.info("Please run: python scripts/download_berlin_dem.py")
        return False

    # Create output directory
    output_dir = Path("data/raster/dem/analysis_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("=" * 80)
        logger.info("BERLIN DEM COMPREHENSIVE ANALYSIS")
        logger.info("=" * 80)

        # Initialize analyzer
        logger.info("\n[1/7] Initializing DEM analyzer...")
        analyzer = DEMAnalyzer(dem_path)

        # Compute terrain statistics
        logger.info("\n[2/7] Computing terrain statistics...")
        stats = analyzer.compute_terrain_statistics()
        stats_path = output_dir / "terrain_statistics.json"
        with open(stats_path, 'w') as f:
            json.dump(stats, f, indent=2)
        logger.info(f"✓ Saved terrain statistics to {stats_path}")
        logger.info(f"  Elevation range: {stats['elevation']['min']:.0f}m - {stats['elevation']['max']:.0f}m")
        logger.info(f"  Average slope: {stats['slope']['mean']:.2f}°")

        # Compute slope
        logger.info("\n[3/7] Computing slope (terrain steepness)...")
        slope_path = output_dir / "berlin_slope.tif"
        analyzer.compute_slope(output_path=slope_path)
        logger.info(f"✓ Saved slope to {slope_path}")

        # Compute aspect
        logger.info("\n[4/7] Computing aspect (slope orientation)...")
        aspect_path = output_dir / "berlin_aspect.tif"
        analyzer.compute_aspect(output_path=aspect_path)
        logger.info(f"✓ Saved aspect to {aspect_path}")

        # Compute hillshade
        logger.info("\n[5/7] Computing hillshade (3D visualization)...")
        hillshade_path = output_dir / "berlin_hillshade.tif"
        analyzer.compute_hillshade(output_path=hillshade_path)
        logger.info(f"✓ Saved hillshade to {hillshade_path}")

        # Terrain classification
        logger.info("\n[6/7] Classifying terrain (flat/rolling/steep)...")
        terrain_class_path = output_dir / "berlin_terrain_classification.tif"
        analyzer.classify_terrain(output_path=terrain_class_path)
        logger.info(f"✓ Saved terrain classification to {terrain_class_path}")
        logger.info("  Classes: 1=Flat, 2=Rolling, 3=Steep, 4=Very Steep")

        # HYDROLOGICAL ANALYSIS
        logger.info("\n" + "=" * 80)
        logger.info("HYDROLOGICAL ANALYSIS")
        logger.info("=" * 80)

        # Flow direction
        logger.info("\n[7/10] Computing flow direction (D8 algorithm)...")
        flow_dir_path = output_dir / "berlin_flow_direction.tif"
        flow_dir = analyzer.compute_flow_direction(output_path=flow_dir_path)
        logger.info(f"✓ Saved flow direction to {flow_dir_path}")

        # Flow accumulation
        logger.info("\n[8/10] Computing flow accumulation...")
        flow_accum_path = output_dir / "berlin_flow_accumulation.tif"
        flow_accum = analyzer.compute_flow_accumulation(
            flow_direction=flow_dir,
            output_path=flow_accum_path
        )
        logger.info(f"✓ Saved flow accumulation to {flow_accum_path}")

        # Stream identification
        logger.info("\n[9/10] Identifying stream networks...")
        streams_path = output_dir / "berlin_streams.geojson"
        streams = analyzer.identify_streams(
            flow_accumulation=flow_accum,
            threshold=1000,
            output_path=streams_path
        )
        logger.info(f"✓ Saved streams to {streams_path}")
        logger.info(f"  Found {len(streams)} stream features")

        # Watersheds
        logger.info("\n[10/10] Delineating watersheds...")
        watersheds_path = output_dir / "berlin_watersheds.geojson"
        watersheds = analyzer.delineate_watersheds(
            flow_direction=flow_dir,
            output_path=watersheds_path
        )
        logger.info(f"✓ Saved watersheds to {watersheds_path}")
        logger.info(f"  Found {len(watersheds)} watershed areas")

        # URBAN PLANNING ANALYSIS
        logger.info("\n" + "=" * 80)
        logger.info("URBAN PLANNING ANALYSIS")
        logger.info("=" * 80)

        # Flood risk assessment
        logger.info("\n[11/12] Assessing flood risk...")
        flood_risk_path = output_dir / "berlin_flood_risk.geojson"
        flood_areas = analyzer.analyze_flood_risk(
            flow_accumulation=flow_accum,
            output_path=flood_risk_path
        )
        logger.info(f"✓ Saved flood risk areas to {flood_risk_path}")
        logger.info(f"  Found {len(flood_areas)} high-risk areas")

        # Development suitability
        logger.info("\n[12/12] Analyzing development suitability...")
        dev_suit_path = output_dir / "berlin_development_suitability.geojson"
        dev_areas = analyzer.analyze_development_suitability(
            max_slope=20.0,
            output_path=dev_suit_path
        )
        logger.info(f"✓ Saved development suitability to {dev_suit_path}")
        logger.info(f"  Found {len(dev_areas)} suitable areas (slope ≤ 20°)")

        # Summary report
        logger.info("\n" + "=" * 80)
        logger.info("ANALYSIS COMPLETE - SUMMARY")
        logger.info("=" * 80)
        logger.info(f"\nOutput directory: {output_dir}")
        logger.info("\nGenerated files:")
        logger.info("  Terrain Analysis:")
        logger.info(f"    - {slope_path.name}")
        logger.info(f"    - {aspect_path.name}")
        logger.info(f"    - {hillshade_path.name}")
        logger.info(f"    - {terrain_class_path.name}")
        logger.info("  Hydrological Analysis:")
        logger.info(f"    - {flow_dir_path.name}")
        logger.info(f"    - {flow_accum_path.name}")
        logger.info(f"    - {streams_path.name}")
        logger.info(f"    - {watersheds_path.name}")
        logger.info("  Urban Planning Analysis:")
        logger.info(f"    - {flood_risk_path.name}")
        logger.info(f"    - {dev_suit_path.name}")
        logger.info(f"    - {stats_path.name}")

        logger.info("\nNext steps:")
        logger.info("  1. Visualize results: python scripts/visualize_dem_analysis.py")
        logger.info("  2. Integrate with API: Add endpoints to query DEM results")

        return True

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = analyze_berlin_dem()
    sys.exit(0 if success else 1)
