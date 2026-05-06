#!/usr/bin/env python3
"""
Download Detailnetz (Berlin Detailed Road Network) from GDI Berlin WFS service
Source: https://gdi.berlin.de/services/wfs/detailnetz
Includes: Road Segments, Connection Points/Nodes, and Engineering Structures (Bridges/Tunnels)
"""

import sys
import logging
import requests
import geopandas as gpd
import pandas as pd
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# WFS endpoint
WFS_BASE_URL = "https://gdi.berlin.de/services/wfs/detailnetz"

# Berlin bounding box (EPSG:4326)
BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)

# Feature types to download
FEATURE_TYPES = {
    'detailnetz:c_strassenabschnitte': 'road_segments',
    'detailnetz:a_verbindungspunkte': 'connection_points',
    'detailnetz:b_bauwerke': 'structures'
}


def get_wfs_capabilities():
    """Get WFS service capabilities to find available layers"""
    print("Querying WFS GetCapabilities...", end="", flush=True)

    try:
        params = {
            'SERVICE': 'WFS',
            'VERSION': '2.0.0',
            'REQUEST': 'GetCapabilities'
        }

        response = requests.get(WFS_BASE_URL, params=params, timeout=30)
        response.raise_for_status()

        # Parse XML
        root = ET.fromstring(response.content)

        # Extract feature types (layers)
        ns = {'wfs': 'http://www.opengis.net/wfs/2.0'}
        feature_types = root.findall('.//wfs:FeatureType', ns)

        if not feature_types:
            # Try without namespace
            feature_types = root.findall('.//FeatureType')

        layers = []
        for ft in feature_types:
            name_elem = ft.find('.//{http://www.opengis.net/wfs/2.0}Name')
            if name_elem is None:
                name_elem = ft.find('.//Name')

            if name_elem is not None:
                layers.append(name_elem.text)

        print(f" ✅\n")

        print(f"Available WFS Layers ({len(layers)}):")
        for layer in layers:
            print(f"  - {layer}")

        return layers

    except Exception as e:
        print(f" ❌\n")
        logger.error(f"Error getting capabilities: {e}")
        return []


def download_wfs_layer(layer_name, bbox=None):
    """Download a layer from WFS as GeoJSON"""

    print(f"\nDownloading layer: {layer_name}...", end="", flush=True)

    try:
        # WFS GetFeature request - try different versions
        for version in ['2.0.0', '1.1.0', '1.0.0']:
            try:
                # WFS 2.0 uses typeNames, older versions use typeName
                type_param = 'typeNames' if version == '2.0.0' else 'TYPENAME'

                params = {
                    'SERVICE': 'WFS',
                    'VERSION': version,
                    'REQUEST': 'GetFeature',
                    type_param: layer_name,
                    'OUTPUTFORMAT': 'GeoJSON' if version == '2.0.0' else 'application/json',
                    'SRSNAME': 'EPSG:4326' if version == '2.0.0' else 'http://www.opengis.net/gml/srs/epsg.xml#4326',
                }

                # Don't use BBOX for detailnetz - causes empty results
                # The service returns better results without spatial filtering

                # Don't set maxfeatures - get all data
                response = requests.get(WFS_BASE_URL, params=params, timeout=180)

                if response.status_code == 200:
                    # Save to temp file
                    temp_file = Path("/tmp") / f"{layer_name.split(':')[-1]}.geojson"
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)

                    # Try to read with geopandas
                    gdf = gpd.read_file(str(temp_file))
                    print(f" ✅")

                    print(f"  Version: WFS {version}")
                    print(f"  Features: {len(gdf):,}")
                    print(f"  CRS: {gdf.crs}")
                    print(f"  Geometry types: {gdf.geometry.type.unique().tolist()}")
                    print(f"  Columns: {len(gdf.columns)}")

                    # Clean up
                    temp_file.unlink()

                    return gdf

            except Exception as e:
                logger.debug(f"Version {version} failed: {e}")
                continue

        print(f" ❌")
        return None

    except Exception as e:
        print(f" ❌")
        logger.error(f"Error downloading layer: {e}")
        return None


def main():
    """Download Detailnetz data from Berlin WFS"""

    print("=" * 80)
    print("DOWNLOADING DETAILNETZ (BERLIN DETAILED ROAD NETWORK) FROM GDI WFS")
    print("=" * 80)
    print(f"\nSource: {WFS_BASE_URL}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    project_root = Path(__file__).parent.parent
    output_dir = project_root / "data/vector/detailnetz"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get available layers
    layers = get_wfs_capabilities()

    if not layers:
        print("\n❌ No layers found in WFS service")
        return False

    print(f"\nAttempting to download available layers\n")

    downloaded_data = {}

    for layer_name, safe_name in FEATURE_TYPES.items():
        if layer_name in layers:
            print(f"Attempting to download: {layer_name}")
            gdf = download_wfs_layer(layer_name, bbox=BERLIN_BBOX)

            if gdf is not None and len(gdf) > 0:
                downloaded_data[safe_name] = gdf
            else:
                print(f"  ⚠️  Layer {layer_name} returned no data")
        else:
            print(f"⚠️  Layer {layer_name} not found in WFS")

    if not downloaded_data:
        print("\n❌ Failed to download any Detailnetz data")
        return False

    print(f"\n{'=' * 80}")
    print("SAVING DATA")
    print(f"{'=' * 80}")

    # Process and save each layer
    for safe_name, gdf in downloaded_data.items():
        # Ensure correct CRS
        if gdf.crs is None:
            gdf.crs = 'EPSG:4326'
        elif gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')

        output_file = output_dir / f"berlin_detailnetz_{safe_name}.geojson"

        print(f"\nSaving {safe_name} to {output_file}...", end="", flush=True)
        gdf.to_file(output_file, driver='GeoJSON')
        print(f" ✅")

        file_size = output_file.stat().st_size / 1024 / 1024
        print(f"  Features: {len(gdf):,}")
        print(f"  Size: {file_size:.1f} MB")
        print(f"  CRS: {gdf.crs}")
        print(f"  Geometry types: {gdf.geometry.type.unique().tolist()}")

    print(f"\n{'=' * 80}")
    print("✅ DOWNLOAD COMPLETE")
    print(f"{'=' * 80}")
    print(f"\nNext step: Load data into PostGIS")
    print(f"   python scripts/load_detailnetz.py\n")

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
