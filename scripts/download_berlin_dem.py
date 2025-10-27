#!/usr/bin/env python3
"""
Download Berlin DEM from Copernicus via Planetary Computer
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders.dem_loader import DEMLoader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_berlin_dem():
    """Download Berlin DEM from Copernicus NASADEM via Planetary Computer"""

    # Berlin bounding box (lon_min, lat_min, lon_max, lat_max)
    berlin_bbox = (13.088, 52.338, 13.761, 52.675)

    loader = DEMLoader(data_dir="data/raster/dem")

    try:
        logger.info("=" * 60)
        logger.info("Downloading Berlin DEM from Copernicus NASADEM")
        logger.info(f"Bounding box: {berlin_bbox}")
        logger.info("=" * 60)

        dem_path = loader.load_from_planetary_computer(
            bbox=berlin_bbox,
            output_name="berlin_dem.tif"
        )

        logger.info(f"✓ Successfully downloaded DEM to: {dem_path}")
        logger.info(f"✓ File size: {dem_path.stat().st_size / 1024 / 1024:.2f} MB")

        return dem_path

    except Exception as e:
        logger.error(f"✗ Failed to download DEM: {e}")
        logger.info("\nTroubleshooting:")
        logger.info("1. Ensure you have 'planetary_computer' and 'pystac_client' installed:")
        logger.info("   pip install planetary-computer pystac-client")
        logger.info("2. Check your internet connection")
        logger.info("3. The Planetary Computer service may be temporarily unavailable")
        raise


if __name__ == "__main__":
    try:
        dem_path = download_berlin_dem()
        logger.info("\nNext steps:")
        logger.info("1. Run the analysis pipeline: python scripts/analyze_berlin_dem.py")
    except Exception as e:
        logger.error(f"Failed to download DEM: {e}")
        sys.exit(1)
