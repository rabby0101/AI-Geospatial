"""
Example 4: NDVI Change Detection Workflow
Demonstrates vegetation change analysis using Sentinel-2 NDVI data

Use Case: Detect vegetation loss in residential areas of Berlin (2018-2024)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.raster_operations import RasterOperations, quick_ndvi_change
from app.utils.data_loaders.sentinel_loader import SentinelLoader
import geopandas as gpd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """
    Complete NDVI change detection workflow
    """

    # Configuration
    REGION = "berlin"
    BBOX = (13.088, 52.338, 13.761, 52.675)  # Berlin bounding box
    DATE_2018 = "2018-07-15"
    DATE_2024 = "2024-07-15"
    LOSS_THRESHOLD = -0.2  # NDVI decrease > 0.2 is significant

    logger.info("=" * 60)
    logger.info("NDVI Change Detection Workflow - Berlin 2018-2024")
    logger.info("=" * 60)

    # Initialize
    sentinel_loader = SentinelLoader(data_dir="data/raster/sentinel2")
    raster_ops = RasterOperations()

    # ==================== STEP 1: Download Sentinel-2 Data ====================
    logger.info("\n[STEP 1] Downloading Sentinel-2 data...")

    try:
        # Download 2018 scene
        logger.info(f"Searching for scene near {DATE_2018}...")
        scene_2018 = sentinel_loader.download_for_region(
            region_name=f"{REGION}_2018",
            bbox=BBOX,
            date=DATE_2018,
            max_cloud=15.0
        )

        if scene_2018 is None:
            logger.warning("Could not download 2018 scene. Using simulated data...")
            scene_2018 = Path("data/raster/ndvi_timeseries/sample_ndvi_2018.tif")

        # Download 2024 scene
        logger.info(f"Searching for scene near {DATE_2024}...")
        scene_2024 = sentinel_loader.download_for_region(
            region_name=f"{REGION}_2024",
            bbox=BBOX,
            date=DATE_2024,
            max_cloud=15.0
        )

        if scene_2024 is None:
            logger.warning("Could not download 2024 scene. Using simulated data...")
            scene_2024 = Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif")

    except Exception as e:
        logger.error(f"Error downloading Sentinel-2 data: {e}")
        logger.info("Proceeding with simulated sample data...")
        scene_2018 = Path("data/raster/ndvi_timeseries/sample_ndvi_2018.tif")
        scene_2024 = Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif")

    # ==================== STEP 2: Compute NDVI ====================
    logger.info("\n[STEP 2] Computing NDVI...")

    # NDVI paths
    ndvi_2018_path = Path(f"data/raster/ndvi_timeseries/{REGION}_ndvi_2018.tif")
    ndvi_2024_path = Path(f"data/raster/ndvi_timeseries/{REGION}_ndvi_2024.tif")

    # Check if already computed
    if not ndvi_2018_path.exists():
        logger.info("Computing NDVI for 2018...")
        # Note: If scene_2018 has multiple bands, we'd extract red/NIR first
        # For now, assume it's already NDVI or use sample data
        logger.info(f"Using scene: {scene_2018}")
        ndvi_2018_path = scene_2018

    if not ndvi_2024_path.exists():
        logger.info("Computing NDVI for 2024...")
        logger.info(f"Using scene: {scene_2024}")
        ndvi_2024_path = scene_2024

    logger.info(f"NDVI 2018: {ndvi_2018_path}")
    logger.info(f"NDVI 2024: {ndvi_2024_path}")

    # ==================== STEP 3: Change Detection ====================
    logger.info("\n[STEP 3] Detecting NDVI change...")

    # Compute difference
    diff_path = Path(f"data/raster/ndvi_timeseries/{REGION}_ndvi_diff_2018_2024.tif")

    if not diff_path.exists():
        ndvi_diff = raster_ops.ndvi_difference(
            ndvi_t1=ndvi_2018_path,
            ndvi_t2=ndvi_2024_path,
            output_path=diff_path
        )
        logger.info(f"Saved NDVI difference to: {diff_path}")
    else:
        logger.info(f"Using existing NDVI difference: {diff_path}")

    # Detect vegetation loss
    logger.info(f"Detecting areas with NDVI decrease > {abs(LOSS_THRESHOLD)}...")
    loss_areas = raster_ops.detect_vegetation_loss(
        ndvi_diff=diff_path,
        threshold=LOSS_THRESHOLD,
        min_area_pixels=50  # Filter small polygons
    )

    logger.info(f"Found {len(loss_areas)} vegetation loss areas")

    # Detect vegetation gain
    logger.info(f"Detecting areas with NDVI increase > 0.2...")
    gain_areas = raster_ops.detect_vegetation_gain(
        ndvi_diff=diff_path,
        threshold=0.2,
        min_area_pixels=50
    )

    logger.info(f"Found {len(gain_areas)} vegetation gain areas")

    # ==================== STEP 4: Filter by Land Use (Optional) ====================
    logger.info("\n[STEP 4] Filtering by residential areas...")

    # Try to load residential areas
    residential_paths = [
        "data/vector/osm/berlin_residential.geojson",
        "data/vector/urban_areas_berlin.geojson"
    ]

    residential = None
    for path in residential_paths:
        if Path(path).exists():
            logger.info(f"Loading residential areas from: {path}")
            residential = gpd.read_file(path)
            break

    if residential is not None and len(loss_areas) > 0:
        # Ensure same CRS
        if residential.crs != loss_areas.crs:
            residential = residential.to_crs(loss_areas.crs)

        # Spatial intersection: loss areas within residential zones
        loss_in_residential = gpd.overlay(
            loss_areas,
            residential,
            how='intersection'
        )

        logger.info(f"Vegetation loss in residential areas: {len(loss_in_residential)} polygons")

        # Save result
        output_path = Path(f"data/results/{REGION}_residential_vegetation_loss.geojson")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        loss_in_residential.to_file(output_path, driver="GeoJSON")
        logger.info(f"Saved to: {output_path}")

    else:
        logger.info("No residential data available, skipping filter...")
        loss_in_residential = loss_areas

    # ==================== STEP 5: Zonal Statistics ====================
    logger.info("\n[STEP 5] Computing zonal statistics...")

    # If we have polygons, compute stats
    if residential is not None and len(residential) > 0:
        try:
            stats = raster_ops.zonal_stats(
                raster=diff_path,
                polygons=residential.head(10),  # First 10 for demo
                stats=['mean', 'min', 'max', 'std']
            )

            # Add to GeoDataFrame
            residential_sample = residential.head(10).copy()
            residential_sample['ndvi_change_mean'] = stats['mean']
            residential_sample['ndvi_change_min'] = stats['min']
            residential_sample['ndvi_change_max'] = stats['max']
            residential_sample['ndvi_change_std'] = stats['std']

            logger.info("\nZonal statistics (first 10 residential areas):")
            logger.info(residential_sample[['ndvi_change_mean', 'ndvi_change_min', 'ndvi_change_max']])

            # Find areas with significant loss
            significant_loss = residential_sample[residential_sample['ndvi_change_mean'] < LOSS_THRESHOLD]
            logger.info(f"\nResidential areas with significant loss: {len(significant_loss)}")

        except Exception as e:
            logger.error(f"Error computing zonal statistics: {e}")

    # ==================== STEP 6: Summary Report ====================
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY REPORT")
    logger.info("=" * 60)
    logger.info(f"Region: {REGION.upper()}")
    logger.info(f"Time Period: {DATE_2018} to {DATE_2024}")
    logger.info(f"Loss Threshold: NDVI < {LOSS_THRESHOLD}")
    logger.info(f"\nResults:")
    logger.info(f"  - Total vegetation loss areas: {len(loss_areas)}")
    logger.info(f"  - Total vegetation gain areas: {len(gain_areas)}")

    if residential is not None:
        logger.info(f"  - Loss in residential zones: {len(loss_in_residential)}")

    logger.info("\nOutput files:")
    logger.info(f"  - NDVI difference raster: {diff_path}")
    if residential is not None and len(loss_in_residential) > 0:
        logger.info(f"  - Residential loss vector: data/results/{REGION}_residential_vegetation_loss.geojson")

    logger.info("\n" + "=" * 60)
    logger.info("Analysis complete!")
    logger.info("=" * 60)

    return {
        'loss_areas': loss_areas,
        'gain_areas': gain_areas,
        'loss_in_residential': loss_in_residential if residential is not None else None
    }


def quick_analysis_example():
    """
    Quick analysis using convenience function
    """
    logger.info("\n\n" + "=" * 60)
    logger.info("QUICK ANALYSIS EXAMPLE")
    logger.info("=" * 60)

    # Use the quick_ndvi_change function
    loss = quick_ndvi_change(
        region="berlin",
        ndvi_2018_path=Path("data/raster/ndvi_timeseries/sample_ndvi_2018.tif"),
        ndvi_2024_path=Path("data/raster/ndvi_timeseries/sample_ndvi_2024.tif"),
        threshold=-0.2
    )

    logger.info(f"Quick analysis found {len(loss)} loss areas")


if __name__ == "__main__":
    # Run main workflow
    try:
        results = main()

        # Optionally run quick example
        # quick_analysis_example()

    except Exception as e:
        logger.error(f"Error in workflow: {e}", exc_info=True)
        sys.exit(1)
