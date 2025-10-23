"""
Sentinel-2 satellite imagery loader using Sentinel Hub or Microsoft Planetary Computer
"""

import os
import requests
import rasterio
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SentinelLoader:
    """Load Sentinel-2 data from various sources"""

    def __init__(self, data_dir: str = "data/raster/sentinel2"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Planetary Computer STAC API
        self.stac_url = "https://planetarycomputer.microsoft.com/api/stac/v1"

    def search_planetary_computer(
        self,
        bbox: Tuple[float, float, float, float],
        start_date: str,
        end_date: str,
        max_cloud_cover: float = 20.0
    ) -> List[dict]:
        """
        Search for Sentinel-2 scenes using Microsoft Planetary Computer

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            start_date: ISO format date string (YYYY-MM-DD)
            end_date: ISO format date string (YYYY-MM-DD)
            max_cloud_cover: Maximum cloud cover percentage

        Returns:
            List of scene metadata
        """

        search_url = f"{self.stac_url}/search"

        query = {
            "collections": ["sentinel-2-l2a"],
            "bbox": bbox,
            "datetime": f"{start_date}/{end_date}",
            "query": {
                "eo:cloud_cover": {
                    "lt": max_cloud_cover
                }
            },
            "limit": 100
        }

        logger.info(f"Searching Planetary Computer: {start_date} to {end_date}")

        response = requests.post(search_url, json=query)
        response.raise_for_status()

        data = response.json()
        scenes = data.get('features', [])

        logger.info(f"Found {len(scenes)} scenes")

        return scenes

    def download_scene(
        self,
        scene: dict,
        bands: List[str] = ['B04', 'B03', 'B02', 'B08'],
        output_name: Optional[str] = None
    ) -> Path:
        """
        Download specific bands from a Sentinel-2 scene

        Args:
            scene: Scene metadata from search results
            bands: List of band names (B02=Blue, B03=Green, B04=Red, B08=NIR)
            output_name: Custom output filename

        Returns:
            Path to downloaded file
        """

        import planetary_computer as pc

        # Sign the assets for access
        signed_item = pc.sign(scene)

        if output_name is None:
            scene_id = scene['id']
            output_name = f"{scene_id}.tif"

        output_path = self.data_dir / output_name

        # Download each band
        band_arrays = []
        profile = None

        for band in bands:
            asset = signed_item['assets'].get(band)
            if not asset:
                logger.warning(f"Band {band} not found in scene")
                continue

            href = asset['href']

            with rasterio.open(href) as src:
                if profile is None:
                    profile = src.profile.copy()
                    profile.update(count=len(bands))

                band_data = src.read(1)
                band_arrays.append(band_data)

        # Stack bands and save
        stacked = np.stack(band_arrays)

        with rasterio.open(output_path, 'w', **profile) as dst:
            dst.write(stacked)

        logger.info(f"Downloaded scene to {output_path}")

        return output_path

    def compute_ndvi(
        self,
        scene_path: Path,
        red_band: int = 3,
        nir_band: int = 4,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Compute NDVI from a Sentinel-2 scene

        Args:
            scene_path: Path to multi-band raster
            red_band: Index of red band (1-based)
            nir_band: Index of NIR band (1-based)
            output_path: Optional output path

        Returns:
            Path to NDVI raster
        """

        if output_path is None:
            output_path = scene_path.parent / f"{scene_path.stem}_ndvi.tif"

        with rasterio.open(scene_path) as src:
            red = src.read(red_band).astype(float)
            nir = src.read(nir_band).astype(float)

            # NDVI = (NIR - Red) / (NIR + Red)
            ndvi = np.where(
                (nir + red) == 0,
                0,
                (nir - red) / (nir + red)
            )

            # Update profile for single band
            profile = src.profile.copy()
            profile.update(
                dtype=rasterio.float32,
                count=1,
                compress='lzw'
            )

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(ndvi.astype(rasterio.float32), 1)

        logger.info(f"Computed NDVI to {output_path}")

        return output_path

    def download_for_region(
        self,
        region_name: str,
        bbox: Tuple[float, float, float, float],
        date: str,
        max_cloud: float = 20.0
    ) -> Optional[Path]:
        """
        Download best available Sentinel-2 scene for a region and date

        Args:
            region_name: Name for output files
            bbox: Bounding box
            date: Target date (YYYY-MM-DD)
            max_cloud: Maximum cloud cover

        Returns:
            Path to downloaded scene or None
        """

        # Search +/- 7 days from target date
        target = datetime.fromisoformat(date)
        start = (target - timedelta(days=7)).isoformat()
        end = (target + timedelta(days=7)).isoformat()

        scenes = self.search_planetary_computer(bbox, start, end, max_cloud)

        if not scenes:
            logger.warning(f"No scenes found for {region_name}")
            return None

        # Get scene with lowest cloud cover
        best_scene = min(scenes, key=lambda x: x['properties'].get('eo:cloud_cover', 100))

        logger.info(f"Best scene: {best_scene['id']} with {best_scene['properties'].get('eo:cloud_cover')}% cloud cover")

        # Download
        output_name = f"{region_name}_{date}.tif"
        scene_path = self.download_scene(best_scene, output_name=output_name)

        # Also compute NDVI
        self.compute_ndvi(scene_path)

        return scene_path


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = SentinelLoader()

    # Berlin bounding box
    berlin_bbox = (13.088, 52.338, 13.761, 52.675)

    # Search for scenes
    scenes = loader.search_planetary_computer(
        bbox=berlin_bbox,
        start_date="2024-06-01",
        end_date="2024-06-30",
        max_cloud_cover=15.0
    )

    print(f"Found {len(scenes)} scenes")

    # Download best scene
    if scenes:
        best = scenes[0]
        print(f"Best scene: {best['id']}")
        # loader.download_scene(best)
