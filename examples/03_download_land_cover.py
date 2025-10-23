"""
Example 3: Download ESA WorldCover land cover data

Free 10m resolution global land cover from ESA
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders import CopernicusLoader
import rasterio
from rasterio.plot import show
import matplotlib.pyplot as plt
import logging

logging.basicConfig(level=logging.INFO)


def main():
    """Download and analyze ESA WorldCover land cover"""

    loader = CopernicusLoader(data_dir="data/raster/copernicus")

    print("=" * 60)
    print("Downloading ESA WorldCover Land Cover Data")
    print("=" * 60)

    # WorldCover uses a tile grid system
    # Find your tile at: https://esa-worldcover.org/en/data-access

    tiles = {
        'London': 'N51E000',
        'Berlin': 'N51E013',
        'Paris': 'N48E002',
        'Rome': 'N41E012'
    }

    # Download tiles
    downloaded_tiles = {}

    for city, tile_code in tiles.items():
        print(f"\n{city} (Tile: {tile_code})")
        print("-" * 40)

        try:
            tile_path = loader.download_worldcover(
                tile_code=tile_code,
                year=2021
            )
            downloaded_tiles[city] = tile_path
            print(f"✓ Downloaded to: {tile_path}")

        except Exception as e:
            print(f"✗ Failed: {e}")

    # Analyze land cover classes
    print("\n" + "=" * 60)
    print("Land Cover Classes")
    print("=" * 60)

    classes = loader.get_worldcover_classes()
    for code, name in classes.items():
        print(f"  {code:3d}: {name}")

    # Example: Analyze Berlin tile
    if 'Berlin' in downloaded_tiles:
        print("\n" + "=" * 60)
        print("Analyzing Berlin Land Cover")
        print("=" * 60)

        with rasterio.open(downloaded_tiles['Berlin']) as src:
            landcover = src.read(1)

            print(f"\nRaster info:")
            print(f"  Size: {src.width} x {src.height} pixels")
            print(f"  Resolution: {src.res[0]:.1f} x {src.res[1]:.1f} meters")
            print(f"  CRS: {src.crs}")
            print(f"  Bounds: {src.bounds}")

            # Count pixels by class
            import numpy as np

            unique, counts = np.unique(landcover, return_counts=True)

            print("\nLand cover distribution:")
            total_pixels = landcover.size

            for value, count in sorted(zip(unique, counts), key=lambda x: -x[1]):
                if value in classes:
                    percentage = (count / total_pixels) * 100
                    print(f"  {classes[value]:30s}: {percentage:6.2f}%")

            # Visualize (optional)
            try:
                plt.figure(figsize=(10, 10))
                show(src, title='ESA WorldCover - Berlin Area')
                plt.savefig('data/raster/copernicus/berlin_landcover_preview.png', dpi=150)
                print("\nVisualization saved to: data/raster/copernicus/berlin_landcover_preview.png")
            except:
                print("\nSkipped visualization (matplotlib display not available)")

    print("\n" + "=" * 60)
    print("Download completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
