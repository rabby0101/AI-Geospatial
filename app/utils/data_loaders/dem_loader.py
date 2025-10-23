"""
Digital Elevation Model (DEM) loader - Copernicus DEM, SRTM, etc.
"""

import os
import requests
import rasterio
import numpy as np
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class DEMLoader:
    """Load Digital Elevation Models from various sources"""

    def __init__(self, data_dir: str = "data/raster/dem"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_copernicus_dem(
        self,
        bbox: Tuple[float, float, float, float],
        output_name: str = "dem.tif"
    ) -> Path:
        """
        Download Copernicus DEM (30m resolution) from OpenTopography

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            output_name: Output filename

        Returns:
            Path to downloaded DEM
        """

        # OpenTopography API for Copernicus DEM
        url = "https://portal.opentopography.org/API/globaldem"

        params = {
            'demtype': 'COP30',  # Copernicus 30m
            'south': bbox[1],
            'north': bbox[3],
            'west': bbox[0],
            'east': bbox[2],
            'outputFormat': 'GTiff',
            'API_Key': os.getenv('OPENTOPO_API_KEY', '')  # Get free key from opentopography.org
        }

        output_path = self.data_dir / output_name

        logger.info(f"Downloading Copernicus DEM for bbox {bbox}")

        response = requests.get(url, params=params, stream=True)

        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded DEM to {output_path}")
            return output_path
        else:
            logger.error(f"Failed to download DEM: {response.status_code}")
            logger.info("Alternative: Use SRTM or manual download from Copernicus")
            raise Exception(f"Download failed: {response.text}")

    def download_srtm_tile(
        self,
        lat: int,
        lon: int,
        output_name: Optional[str] = None
    ) -> Path:
        """
        Download SRTM 1-degree tile from USGS

        Args:
            lat: Latitude of tile (integer)
            lon: Longitude of tile (integer)
            output_name: Optional output filename

        Returns:
            Path to downloaded tile
        """

        # SRTM tile naming convention
        ns = 'N' if lat >= 0 else 'S'
        ew = 'E' if lon >= 0 else 'W'

        tile_name = f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"

        # USGS Earth Explorer or alternative source
        # This is a simplified example - actual download may require authentication
        url = f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{tile_name}.SRTMGL1.hgt.zip"

        if output_name is None:
            output_name = f"{tile_name}.tif"

        output_path = self.data_dir / output_name

        logger.info(f"Downloading SRTM tile {tile_name}")
        logger.info("Note: This may require USGS Earth Explorer authentication")

        # For actual use, consider using elevation package:
        # pip install elevation
        # import elevation
        # elevation.clip(bounds=bbox, output=output_path)

        return output_path

    def compute_slope(
        self,
        dem_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Compute slope from DEM

        Args:
            dem_path: Path to DEM raster
            output_path: Optional output path

        Returns:
            Path to slope raster
        """

        if output_path is None:
            output_path = dem_path.parent / f"{dem_path.stem}_slope.tif"

        with rasterio.open(dem_path) as src:
            dem = src.read(1)
            transform = src.transform

            # Compute gradients
            dx, dy = np.gradient(dem, transform.a, transform.e)

            # Slope in degrees
            slope = np.arctan(np.sqrt(dx**2 + dy**2)) * (180.0 / np.pi)

            # Save
            profile = src.profile.copy()
            profile.update(dtype=rasterio.float32, compress='lzw')

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(slope.astype(rasterio.float32), 1)

        logger.info(f"Computed slope to {output_path}")

        return output_path

    def compute_aspect(
        self,
        dem_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Compute aspect (orientation) from DEM

        Args:
            dem_path: Path to DEM raster
            output_path: Optional output path

        Returns:
            Path to aspect raster
        """

        if output_path is None:
            output_path = dem_path.parent / f"{dem_path.stem}_aspect.tif"

        with rasterio.open(dem_path) as src:
            dem = src.read(1)
            transform = src.transform

            dx, dy = np.gradient(dem, transform.a, transform.e)

            # Aspect in degrees (0-360)
            aspect = np.arctan2(-dy, dx) * (180.0 / np.pi)
            aspect = (aspect + 360) % 360  # Normalize to 0-360

            profile = src.profile.copy()
            profile.update(dtype=rasterio.float32, compress='lzw')

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(aspect.astype(rasterio.float32), 1)

        logger.info(f"Computed aspect to {output_path}")

        return output_path

    def load_from_planetary_computer(
        self,
        bbox: Tuple[float, float, float, float],
        output_name: str = "copernicus_dem.tif"
    ) -> Path:
        """
        Load Copernicus DEM from Microsoft Planetary Computer

        Args:
            bbox: Bounding box
            output_name: Output filename

        Returns:
            Path to DEM
        """

        import planetary_computer as pc
        import pystac_client

        # Open STAC catalog
        catalog = pystac_client.Client.open(
            "https://planetarycomputer.microsoft.com/api/stac/v1",
            modifier=pc.sign_inplace
        )

        # Search for DEM
        search = catalog.search(
            collections=["cop-dem-glo-30"],
            bbox=bbox
        )

        items = list(search.items())

        if not items:
            raise ValueError("No DEM tiles found for this bbox")

        logger.info(f"Found {len(items)} DEM tiles")

        # For simplicity, use first tile (you may want to mosaic multiple)
        item = items[0]
        dem_asset = item.assets['data']

        output_path = self.data_dir / output_name

        # Download
        import urllib.request
        urllib.request.urlretrieve(dem_asset.href, output_path)

        logger.info(f"Downloaded Copernicus DEM to {output_path}")

        return output_path


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = DEMLoader()

    # Berlin bounding box
    berlin_bbox = (13.088, 52.338, 13.761, 52.675)

    try:
        # Try Planetary Computer
        dem_path = loader.load_from_planetary_computer(berlin_bbox, "berlin_dem.tif")

        # Compute derivatives
        loader.compute_slope(dem_path)
        loader.compute_aspect(dem_path)

    except Exception as e:
        logger.error(f"Failed to download DEM: {e}")
        logger.info("Install required packages: pip install planetary-computer pystac-client")
