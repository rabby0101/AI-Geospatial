#!/usr/bin/env python3
"""
Download Berlin Parking Locations (Parkplätze) from WFS
"""

import json
import sys
import requests
import geopandas as gpd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, '/Users/skfazlarabby/projects/AI Geospatial')
from app.utils.database import db_manager


def build_wfs_request(feature_type="parkplaetze:parkplaetze"):
    """Build WFS GetFeature request URL."""
    base_url = "https://gdi.berlin.de/services/wfs/parkplaetze"

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "typeNames": feature_type,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }

    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{base_url}?{query_string}"


def download_wfs_data(feature_type="parkplaetze:parkplaetze"):
    """Download WFS data."""
    url = build_wfs_request(feature_type)
    logger.info(f"Downloading {feature_type}...")

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()

        data = response.json()
        logger.info(f"✅ Downloaded {len(data.get('features', []))} features")
        return data
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        raise


def convert_wfs_to_geodataframe(wfs_data):
    """Convert WFS GeoJSON to GeoDataFrame."""
    try:
        gdf = gpd.GeoDataFrame.from_features(wfs_data['features'])
        gdf = gdf.set_crs("EPSG:4326")
        logger.info(f"✅ Converted: {len(gdf)} features, {len(gdf.columns)} columns")
        logger.info(f"   Columns: {list(gdf.columns)}")
        return gdf
    except Exception as e:
        logger.error(f"❌ Conversion failed: {e}")
        raise


def save_to_postgis(gdf, table_name="parkplaetze"):
    """Save to PostGIS."""
    try:
        logger.info(f"📤 Saving {len(gdf)} features to vector.{table_name}...")

        if 'geom' in gdf.columns and 'geometry' not in gdf.columns:
            gdf = gdf.rename(columns={'geom': 'geometry'})

        gdf = gdf.set_geometry('geometry')

        # Use the correct database manager method
        db_manager.save_vector_to_db(gdf, table_name=table_name, schema="vector", if_exists='replace')

        logger.info(f"✅ Successfully saved {len(gdf)} features to vector.{table_name}")

        return True

    except Exception as e:
        logger.error(f"❌ Save failed: {e}")
        raise


def main():
    """Download and import parking data."""
    logger.info("=" * 70)
    logger.info("DOWNLOADING BERLIN PARKING LOCATIONS DATA")
    logger.info("=" * 70)

    try:
        wfs_data = download_wfs_data()
        gdf = convert_wfs_to_geodataframe(wfs_data)
        save_to_postgis(gdf, table_name="parkplaetze")

        logger.info("=" * 70)
        logger.info("✅ IMPORT COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Table: vector.parkplaetze")
        logger.info(f"Features: {len(gdf)}")
        logger.info(f"Columns: {list(gdf.columns)}")

    except Exception as e:
        logger.error(f"❌ FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
