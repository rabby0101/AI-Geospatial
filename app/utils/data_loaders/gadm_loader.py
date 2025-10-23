"""
GADM (Administrative Boundaries) loader
Completely free and open-source administrative boundaries
"""

import os
import requests
import geopandas as gpd
from pathlib import Path
from typing import Optional
import logging
import zipfile

logger = logging.getLogger(__name__)


class GADMLoader:
    """Load administrative boundaries from GADM (free and open)"""

    GADM_BASE_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1"

    def __init__(self, data_dir: str = "data/vector/gadm"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_country(
        self,
        country_code: str,
        admin_level: int = 0,
        format: str = "gpkg"
    ) -> Path:
        """
        Download GADM administrative boundaries for a country

        Args:
            country_code: ISO 3166-1 alpha-3 code (e.g., 'DEU' for Germany)
            admin_level: Administrative level (0=country, 1=states, 2=counties, etc.)
            format: 'gpkg' or 'shp'

        Returns:
            Path to downloaded file

        Free and Open Source: GADM is freely available for academic and other non-commercial use
        """

        if format == "gpkg":
            url = f"{self.GADM_BASE_URL}/gpkg/gadm41_{country_code}.gpkg"
            filename = f"gadm41_{country_code}.gpkg"
        elif format == "shp":
            url = f"{self.GADM_BASE_URL}/shp/gadm41_{country_code}_{admin_level}.zip"
            filename = f"gadm41_{country_code}_{admin_level}.zip"
        else:
            raise ValueError("Format must be 'gpkg' or 'shp'")

        output_path = self.data_dir / filename

        # Check if already downloaded
        if output_path.exists():
            logger.info(f"File already exists: {output_path}")
            return output_path

        logger.info(f"Downloading GADM data for {country_code} from {url}")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to {output_path}")

        # Extract if shapefile
        if format == "shp":
            with zipfile.ZipFile(output_path, 'r') as zip_ref:
                extract_dir = self.data_dir / f"{country_code}_{admin_level}"
                zip_ref.extractall(extract_dir)
                logger.info(f"Extracted to {extract_dir}")

        return output_path

    def load_boundaries(
        self,
        country_code: str,
        admin_level: int = 0
    ) -> gpd.GeoDataFrame:
        """
        Load administrative boundaries as GeoDataFrame

        Args:
            country_code: ISO country code
            admin_level: Administrative level

        Returns:
            GeoDataFrame with boundaries
        """

        # Download if needed
        gpkg_path = self.download_country(country_code, admin_level, "gpkg")

        # Layer name in GeoPackage
        layer_name = f"ADM_ADM_{admin_level}"

        gdf = gpd.read_file(gpkg_path, layer=layer_name)

        logger.info(f"Loaded {len(gdf)} administrative units")

        return gdf

    def get_available_countries(self) -> dict:
        """
        Return common country codes

        Returns:
            Dictionary of country names to ISO codes
        """

        return {
            "Germany": "DEU",
            "France": "FRA",
            "Italy": "ITA",
            "Spain": "ESP",
            "United Kingdom": "GBR",
            "United States": "USA",
            "Canada": "CAN",
            "Brazil": "BRA",
            "India": "IND",
            "China": "CHN",
            "Japan": "JPN",
            "Australia": "AUS",
            "South Africa": "ZAF",
            "Kenya": "KEN",
            "Nigeria": "NGA",
            "Bangladesh": "BGD"
        }


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = GADMLoader()

    # Download Germany administrative boundaries
    gdf = loader.load_boundaries("DEU", admin_level=1)  # States

    print(f"Loaded {len(gdf)} German states")
    print(gdf.columns)
    print(gdf[['NAME_1', 'TYPE_1']].head())
