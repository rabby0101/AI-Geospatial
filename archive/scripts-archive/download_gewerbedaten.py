#!/usr/bin/env python3
"""
Download and import Berlin Gewerbedaten (Business/Commercial Data) from WFS into PostGIS.

This script fetches data from the Berlin GDI WFS service and imports it into the PostGIS database.
"""

import os
import sys
import requests
import geopandas as gpd
from pathlib import Path
from urllib.parse import urljoin
import json

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.database import DatabaseManager

# WFS Service Configuration
WFS_BASE_URL = "https://gdi.berlin.de/services/wfs/gewerbedaten"
FEATURE_TYPE = "gewerbedaten:gewerbedaten"
OUTPUT_FORMAT = "application/json"  # GeoJSON format

# Database Configuration
TABLE_NAME = "gewerbedaten"
SCHEMA = "vector"

def build_wfs_request(feature_type, output_format="application/json", max_features=None):
    """
    Build a WFS GetFeature request URL.

    Args:
        feature_type: The feature type to request (e.g., 'gewerbedaten:gewerbedaten')
        output_format: Output format (e.g., 'application/json', 'application/gml+xml')
        max_features: Optional maximum number of features

    Returns:
        Complete WFS URL
    """
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": feature_type,
        "OUTPUTFORMAT": output_format,
        "SRSNAME": "EPSG:4326",  # Request in WGS84
    }

    if max_features:
        params["COUNT"] = max_features

    # Build URL with parameters
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{WFS_BASE_URL}?{query_string}"

def download_wfs_data(feature_type, output_format="application/json", max_features=None):
    """
    Download WFS data from Berlin GDI service.

    Args:
        feature_type: Feature type to download
        output_format: Output format
        max_features: Optional limit on number of features

    Returns:
        Dictionary with GeoJSON data or None if failed
    """
    url = build_wfs_request(feature_type, output_format, max_features)

    print(f"Downloading WFS data from: {url[:100]}...")

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()

        if output_format == "application/json":
            data = response.json()
            return data
        else:
            # For other formats, return raw content
            return response.text

    except requests.exceptions.RequestException as e:
        print(f"Error downloading WFS data: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        return None

def convert_wfs_to_geodataframe(wfs_data):
    """
    Convert WFS GeoJSON data to GeoDataFrame.

    Args:
        wfs_data: GeoJSON data from WFS

    Returns:
        GeoDataFrame or None if conversion failed
    """
    try:
        # WFS returns GeoJSON FeatureCollection
        if isinstance(wfs_data, dict):
            # Convert GeoJSON to GeoDataFrame
            gdf = gpd.GeoDataFrame.from_features(
                wfs_data.get('features', []),
                crs="EPSG:4326"
            )

            if gdf.empty:
                print("Warning: No features found in WFS response")
                return None

            print(f"Successfully converted {len(gdf)} features to GeoDataFrame")
            print(f"Columns: {list(gdf.columns)}")
            return gdf
        else:
            print(f"Unexpected data format: {type(wfs_data)}")
            return None

    except Exception as e:
        print(f"Error converting WFS data to GeoDataFrame: {e}")
        return None

def save_to_postgis(gdf, table_name, schema="vector", if_exists="replace"):
    """
    Save GeoDataFrame to PostGIS database.

    Args:
        gdf: GeoDataFrame to save
        table_name: Target table name
        schema: Database schema
        if_exists: Action if table exists ('replace', 'append', 'fail')

    Returns:
        True if successful, False otherwise
    """
    try:
        db = DatabaseManager()

        # Test connection
        if not db.test_connection():
            print("Failed to connect to database")
            return False

        print(f"Saving {len(gdf)} features to {schema}.{table_name}...")
        db.save_vector_to_db(gdf, table_name, schema=schema, if_exists=if_exists)

        print(f"Successfully saved data to {schema}.{table_name}")

        # Get table info
        info = db.get_table_info(table_name, schema=schema)
        print(f"Table Info:")
        print(f"  - Rows: {info['row_count']}")
        print(f"  - Geometry Type: {info['geometry_type']}")
        print(f"  - Columns: {len(info['columns'])}")

        return True

    except Exception as e:
        print(f"Error saving to PostGIS: {e}")
        return False

def main():
    """Main execution function."""
    print("=" * 70)
    print("Berlin Gewerbedaten WFS Import Tool")
    print("=" * 70)
    print()

    # Step 1: Download WFS data
    print("[1/3] Downloading WFS data...")
    print(f"      Feature Type: {FEATURE_TYPE}")
    print(f"      Format: {OUTPUT_FORMAT}")
    print()

    wfs_data = download_wfs_data(FEATURE_TYPE, OUTPUT_FORMAT)
    if not wfs_data:
        print("Failed to download WFS data")
        return False

    # Get feature count from response
    feature_count = len(wfs_data.get('features', []))
    print(f"      Downloaded {feature_count} features")
    print()

    # Step 2: Convert to GeoDataFrame
    print("[2/3] Converting to GeoDataFrame...")
    gdf = convert_wfs_to_geodataframe(wfs_data)
    if gdf is None or gdf.empty:
        print("Failed to convert WFS data")
        return False
    print()

    # Display sample
    print("      Sample data:")
    if len(gdf) > 0:
        print(f"      First row: {gdf.iloc[0].to_dict()}")
    print()

    # Step 3: Save to PostGIS
    print("[3/3] Saving to PostGIS...")
    print(f"      Table: {SCHEMA}.{TABLE_NAME}")
    print()

    success = save_to_postgis(gdf, TABLE_NAME, schema=SCHEMA, if_exists="replace")

    print()
    print("=" * 70)
    if success:
        print("Import completed successfully!")
    else:
        print("Import failed!")
    print("=" * 70)

    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
