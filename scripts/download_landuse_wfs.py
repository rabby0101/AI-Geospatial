#!/usr/bin/env python3
"""
Download landuse data from Berlin's official WFS service (GDI Berlin)
Source: https://gdi.berlin.de/services/wfs/elu_forst
"""

import sys
import logging
import requests
import geopandas as gpd
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# WFS endpoint
WFS_BASE_URL = "https://gdi.berlin.de/services/wfs/elu_forst"

# Berlin bounding box (EPSG:4326)
BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)


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
        print(f"Error: {e}")
        return []


def download_wfs_layer(layer_name):
    """Download a layer from WFS as GeoJSON"""

    print(f"\nDownloading layer: {layer_name}...", end="", flush=True)

    try:
        # WFS GetFeature request - try different versions
        for version in ['1.1.0', '1.0.0', '2.0.0']:
            try:
                params = {
                    'SERVICE': 'WFS',
                    'VERSION': version,
                    'REQUEST': 'GetFeature',
                    'TYPENAME': layer_name,
                    'OUTPUTFORMAT': 'GeoJSON' if version == '2.0.0' else 'application/json',
                    'SRSNAME': 'EPSG:4326' if version == '2.0.0' else 'http://www.opengis.net/gml/srs/epsg.xml#4326',
                    'maxfeatures': '10000'
                }

                response = requests.get(WFS_BASE_URL, params=params, timeout=120)

                if response.status_code == 200:
                    # Save to temp file
                    temp_file = Path("/tmp") / f"{layer_name}.geojson"
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)

                    # Try to read with geopandas
                    gdf = gpd.read_file(str(temp_file))
                    print(f" ✅")

                    print(f"  Version: WFS {version}")
                    print(f"  Features: {len(gdf):,}")
                    print(f"  CRS: {gdf.crs}")
                    print(f"  Geometry types: {gdf.geometry.type.unique().tolist()}")

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
        print(f"  Error: {e}")
        return None


def main():
    """Download landuse data from Berlin WFS"""

    print("=" * 80)
    print("DOWNLOADING LANDUSE DATA FROM BERLIN GDI WFS")
    print("=" * 80)
    print(f"\nSource: {WFS_BASE_URL}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    project_root = Path(__file__).parent.parent
    output_dir = project_root / "data/vector/osm"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get available layers
    layers = get_wfs_capabilities()

    if not layers:
        print("\n❌ No layers found in WFS service")
        return False

    # Look for landuse-related layers
    landuse_layers = [l for l in layers if 'landuse' in l.lower() or 'nutzung' in l.lower()]

    if not landuse_layers:
        print(f"\n⚠️  No landuse layers found. Available layers: {layers}")
        print("\nTrying first available layer...")
        landuse_layers = layers[:1]

    print(f"\nLanduse layers found: {landuse_layers}\n")

    all_gdfs = []

    for layer in landuse_layers:
        print(f"Attempting to download: {layer}")
        gdf = download_wfs_layer(layer)

        if gdf is not None and len(gdf) > 0:
            all_gdfs.append(gdf)
        else:
            print(f"  ⚠️  Skipping {layer} (empty or error)")

    if not all_gdfs:
        print("\n❌ Failed to download any landuse data")
        return False

    # Combine all dataframes
    print(f"\nCombining {len(all_gdfs)} datasets...", end="", flush=True)
    combined_gdf = gpd.GeoDataFrame(
        pd.concat(all_gdfs, ignore_index=True)
    )
    print(f" ✅")

    # Ensure correct CRS
    if combined_gdf.crs is None:
        combined_gdf.crs = 'EPSG:4326'
    elif combined_gdf.crs != 'EPSG:4326':
        combined_gdf = combined_gdf.to_crs('EPSG:4326')

    # Save to file
    output_file = output_dir / "berlin_landuse.geojson"
    print(f"\nSaving to {output_file}...", end="", flush=True)
    combined_gdf.to_file(output_file, driver='GeoJSON')
    print(f" ✅")

    print(f"\n" + "=" * 80)
    print("DOWNLOAD SUMMARY")
    print("=" * 80)
    print(f"\nTotal features: {len(combined_gdf):,}")
    print(f"CRS: {combined_gdf.crs}")
    print(f"Geometry types: {combined_gdf.geometry.type.unique().tolist()}")
    print(f"Columns: {list(combined_gdf.columns)}")

    file_size = output_file.stat().st_size / 1024 / 1024
    print(f"\nFile: {output_file}")
    print(f"Size: {file_size:.1f} MB")

    print(f"\n{'=' * 80}")
    print(f"✅ Next step: Load data into PostGIS")
    print(f"   python scripts/load_landuse.py\n")

    return True


if __name__ == "__main__":
    import pandas as pd

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
