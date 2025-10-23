"""
Copernicus Data Loader (ESA WorldCover, Copernicus DEM, etc.)
All free and open-source from ESA Copernicus program
"""

import os
import requests
import rasterio
import geopandas as gpd
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class CopernicusLoader:
    """Load free and open Copernicus datasets"""

    def __init__(self, data_dir: str = "data/raster/copernicus"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_worldcover(
        self,
        tile_code: str,
        year: int = 2021,
        output_name: Optional[str] = None
    ) -> Path:
        """
        Download ESA WorldCover land cover map (10m resolution)

        Args:
            tile_code: Tile code (e.g., 'N51E000' for London area)
            year: Year (2020 or 2021 available)
            output_name: Optional output filename

        Returns:
            Path to downloaded file

        Free and Open Source: ESA WorldCover is freely available
        Download tiles from: https://esa-worldcover.org/
        """

        base_url = f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/{year}/map"
        filename = f"ESA_WorldCover_10m_{year}v200_{tile_code}_Map.tif"

        url = f"{base_url}/{filename}"

        if output_name is None:
            output_name = filename

        output_path = self.data_dir / output_name

        if output_path.exists():
            logger.info(f"File already exists: {output_path}")
            return output_path

        logger.info(f"Downloading WorldCover tile {tile_code} for {year}")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to {output_path}")

        return output_path

    def get_worldcover_classes(self) -> dict:
        """
        Get WorldCover land cover classification

        Returns:
            Dictionary mapping pixel values to land cover types
        """

        return {
            10: "Tree cover",
            20: "Shrubland",
            30: "Grassland",
            40: "Cropland",
            50: "Built-up",
            60: "Bare / sparse vegetation",
            70: "Snow and ice",
            80: "Permanent water bodies",
            90: "Herbaceous wetland",
            95: "Mangroves",
            100: "Moss and lichen"
        }

    def download_corine_land_cover(
        self,
        year: int = 2018,
        country: Optional[str] = None
    ) -> Path:
        """
        Download CORINE Land Cover (European land cover dataset)

        Args:
            year: Year (2000, 2006, 2012, 2018 available)
            country: Optional country filter

        Returns:
            Path to downloaded file

        Free and Open Source: Available from Copernicus Land Monitoring Service
        """

        base_url = "https://land.copernicus.eu/api/en/products/corine-land-cover"

        logger.info(f"CORINE Land Cover {year} is available at:")
        logger.info("https://land.copernicus.eu/en/products/corine-land-cover")
        logger.info("Download manually and place in: " + str(self.data_dir))

        # Manual download required - provide instructions
        raise NotImplementedError(
            "CORINE requires manual download from Copernicus portal. "
            "Visit: https://land.copernicus.eu/en/products/corine-land-cover"
        )

    def download_global_surface_water(
        self,
        lon: int,
        lat: int,
        output_name: Optional[str] = None
    ) -> Path:
        """
        Download JRC Global Surface Water dataset

        Args:
            lon: Longitude (tile)
            lat: Latitude (tile)
            output_name: Optional output filename

        Returns:
            Path to downloaded file

        Free and Open Source: JRC Global Surface Water
        """

        # Format coordinates
        lon_str = f"{abs(lon)}{'E' if lon >= 0 else 'W'}"
        lat_str = f"{abs(lat)}{'N' if lat >= 0 else 'S'}"

        filename = f"occurrence_{lon_str}_{lat_str}v1_4_2021.tif"

        url = f"https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/{filename}"

        if output_name is None:
            output_name = filename

        output_path = self.data_dir / output_name

        if output_path.exists():
            logger.info(f"File already exists: {output_path}")
            return output_path

        logger.info(f"Downloading Global Surface Water tile ({lon}, {lat})")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to {output_path}")

        return output_path

    def load_from_planetary_computer(
        self,
        dataset: str,
        bbox: Tuple[float, float, float, float],
        output_name: str
    ) -> Path:
        """
        Load Copernicus datasets from Microsoft Planetary Computer

        Args:
            dataset: Dataset name ('cop-dem-glo-30', 'io-lulc', etc.)
            bbox: Bounding box
            output_name: Output filename

        Returns:
            Path to downloaded file

        Free datasets available:
        - cop-dem-glo-30: Copernicus DEM 30m
        - cop-dem-glo-90: Copernicus DEM 90m
        - io-lulc: Impact Observatory Land Use/Land Cover
        """

        import planetary_computer as pc
        import pystac_client
        import rioxarray

        catalog = pystac_client.Client.open(
            "https://planetarycomputer.microsoft.com/api/stac/v1",
            modifier=pc.sign_inplace
        )

        search = catalog.search(
            collections=[dataset],
            bbox=bbox
        )

        items = list(search.items())

        if not items:
            raise ValueError(f"No items found for {dataset} in this bbox")

        logger.info(f"Found {len(items)} tiles for {dataset}")

        # Use first item (or mosaic if needed)
        item = items[0]
        asset = item.assets['data']

        output_path = self.data_dir / output_name

        # Download
        import urllib.request
        urllib.request.urlretrieve(asset.href, output_path)

        logger.info(f"Downloaded {dataset} to {output_path}")

        return output_path


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = CopernicusLoader()

    # Download WorldCover for London area
    tile = loader.download_worldcover("N51E000", year=2021)

    print(f"Downloaded: {tile}")

    # Show land cover classes
    classes = loader.get_worldcover_classes()
    print("\nWorldCover classes:")
    for code, name in classes.items():
        print(f"  {code}: {name}")
