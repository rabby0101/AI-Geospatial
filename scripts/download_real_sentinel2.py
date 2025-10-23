"""
Download Real Sentinel-2 Data for NDVI Analysis
Uses Microsoft Planetary Computer (free, no API key required)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RealSentinel2Loader:
    """
    Download and process real Sentinel-2 data from Microsoft Planetary Computer
    No API key required - completely free and open access
    """

    def __init__(self, data_dir: str = "data/raster/sentinel2"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # NDVI output directory
        self.ndvi_dir = Path("data/raster/ndvi_timeseries")
        self.ndvi_dir.mkdir(parents=True, exist_ok=True)

    def search_sentinel2(self, bbox, start_date, end_date, max_cloud=20.0):
        """
        Search for Sentinel-2 scenes using STAC API

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            max_cloud: Maximum cloud cover %

        Returns:
            List of scenes sorted by cloud cover (lowest first)
        """
        try:
            from pystac_client import Client
            import planetary_computer as pc

            logger.info(f"🔍 Searching Sentinel-2 data from {start_date} to {end_date}")
            logger.info(f"   Region: {bbox}")
            logger.info(f"   Max cloud cover: {max_cloud}%")

            # Connect to Planetary Computer STAC catalog
            catalog = Client.open(
                "https://planetarycomputer.microsoft.com/api/stac/v1",
                modifier=pc.sign_inplace
            )

            # Search for Sentinel-2 L2A (atmospherically corrected)
            search = catalog.search(
                collections=["sentinel-2-l2a"],
                bbox=bbox,
                datetime=f"{start_date}/{end_date}",
                query={"eo:cloud_cover": {"lt": max_cloud}}
            )

            items = list(search.items())

            logger.info(f"✅ Found {len(items)} scenes")

            if len(items) == 0:
                logger.warning("No scenes found. Try:")
                logger.warning("  - Increasing max_cloud_cover")
                logger.warning("  - Expanding date range")
                logger.warning("  - Checking bbox coordinates")
                return []

            # Sort by cloud cover (lowest first)
            items_sorted = sorted(items, key=lambda x: x.properties.get('eo:cloud_cover', 100))

            # Show top 5 scenes
            logger.info("\n📊 Top scenes by cloud cover:")
            for i, item in enumerate(items_sorted[:5]):
                cloud = item.properties.get('eo:cloud_cover', 'N/A')
                date = item.properties.get('datetime', 'N/A')
                logger.info(f"  {i+1}. {item.id[:30]}... - Cloud: {cloud:.1f}% - Date: {date[:10]}")

            return items_sorted

        except ImportError as e:
            logger.error(f"❌ Missing dependencies: {e}")
            logger.error("Install: pip install pystac-client planetary-computer")
            return []
        except Exception as e:
            logger.error(f"❌ Search failed: {e}")
            return []

    def download_bands(self, item, bbox, bands=['B04', 'B08'], resolution=10):
        """
        Download specific bands from a Sentinel-2 scene

        Args:
            item: STAC item from search
            bbox: (min_lon, min_lat, max_lon, max_lat)
            bands: List of band names (B04=Red, B08=NIR for NDVI)
            resolution: Target resolution in meters (10, 20, or 60)

        Returns:
            Dictionary of {band_name: numpy_array}
        """
        try:
            import rioxarray
            import planetary_computer as pc

            logger.info(f"📥 Downloading bands {bands} from {item.id[:40]}...")

            # Sign the item for authenticated access
            signed_item = pc.sign(item)

            band_data = {}

            for band in bands:
                if band not in signed_item.assets:
                    logger.warning(f"⚠️  Band {band} not found in scene")
                    continue

                # Get the asset URL
                asset = signed_item.assets[band]
                href = asset.href

                logger.info(f"  Loading {band}...")

                # Open with rioxarray (handles cloud-optimized GeoTIFFs efficiently)
                da = rioxarray.open_rasterio(href, masked=True)

                # Clip to bbox
                da_clipped = da.rio.clip_box(
                    minx=bbox[0],
                    miny=bbox[1],
                    maxx=bbox[2],
                    maxy=bbox[3],
                    crs="EPSG:4326"
                )

                # Convert to numpy array
                band_array = da_clipped.values[0]  # First band

                band_data[band] = band_array

                logger.info(f"    ✅ {band}: {band_array.shape} pixels")

            return band_data

        except ImportError as e:
            logger.error(f"❌ Missing rioxarray: pip install rioxarray")
            return {}
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def compute_ndvi(self, red_band, nir_band):
        """
        Compute NDVI from red and NIR bands
        NDVI = (NIR - Red) / (NIR + Red)

        Args:
            red_band: Red band array (B04)
            nir_band: NIR band array (B08)

        Returns:
            NDVI array
        """
        logger.info("🌿 Computing NDVI...")

        # Convert to float
        red = red_band.astype(float)
        nir = nir_band.astype(float)

        # Compute NDVI
        ndvi = np.where(
            (nir + red) == 0,
            0,
            (nir - red) / (nir + red)
        )

        # Clip to valid range
        ndvi = np.clip(ndvi, -1, 1)

        # Mask invalid values
        ndvi = np.ma.masked_invalid(ndvi)

        logger.info(f"  NDVI range: [{np.nanmin(ndvi):.3f}, {np.nanmax(ndvi):.3f}]")
        logger.info(f"  Mean NDVI: {np.nanmean(ndvi):.3f}")

        return ndvi

    def save_ndvi_geotiff(self, ndvi_array, output_path, item, bbox):
        """
        Save NDVI as GeoTIFF with proper georeferencing

        Args:
            ndvi_array: NDVI numpy array
            output_path: Path to save file
            item: STAC item (for metadata)
            bbox: Bounding box used for clipping
        """
        from rasterio.transform import from_bounds

        logger.info(f"💾 Saving NDVI to {output_path}...")

        # Create transform from bbox
        height, width = ndvi_array.shape
        transform = from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], width, height)

        # Create raster profile
        profile = {
            'driver': 'GTiff',
            'height': height,
            'width': width,
            'count': 1,
            'dtype': rasterio.float32,
            'crs': 'EPSG:4326',
            'transform': transform,
            'compress': 'lzw',
            'nodata': -9999
        }

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(output_path, 'w', **profile) as dst:
            # Mask nodata values
            ndvi_masked = np.ma.filled(ndvi_array, -9999)
            dst.write(ndvi_masked.astype(rasterio.float32), 1)

            # Add metadata
            dst.update_tags(
                scene_id=item.id,
                date=item.properties.get('datetime', ''),
                cloud_cover=item.properties.get('eo:cloud_cover', ''),
                source='Sentinel-2 L2A via Planetary Computer'
            )

        logger.info(f"  ✅ Saved: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")

    def download_and_compute_ndvi(self, region_name, bbox, date, max_cloud=20.0):
        """
        Complete workflow: Search, download, compute NDVI

        Args:
            region_name: Name for output files (e.g., 'berlin')
            bbox: (min_lon, min_lat, max_lon, max_lat)
            date: Target date (YYYY-MM-DD)
            max_cloud: Maximum cloud cover %

        Returns:
            Path to NDVI GeoTIFF or None
        """
        logger.info("=" * 60)
        logger.info(f"🛰️  SENTINEL-2 NDVI DOWNLOAD")
        logger.info(f"   Region: {region_name}")
        logger.info(f"   Date: {date}")
        logger.info("=" * 60)

        # Search +/- 7 days from target date
        target = datetime.fromisoformat(date)
        start_date = (target - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = (target + timedelta(days=7)).strftime("%Y-%m-%d")

        # Search for scenes
        items = self.search_sentinel2(bbox, start_date, end_date, max_cloud)

        if not items:
            logger.error("❌ No scenes found")
            return None

        # Use best scene (lowest cloud cover)
        best_item = items[0]
        cloud_cover = best_item.properties.get('eo:cloud_cover', 'N/A')
        scene_date = best_item.properties.get('datetime', '')[:10]

        logger.info(f"\n🎯 Selected scene:")
        logger.info(f"   ID: {best_item.id}")
        logger.info(f"   Date: {scene_date}")
        logger.info(f"   Cloud cover: {cloud_cover}%")

        # Download Red and NIR bands
        bands = self.download_bands(best_item, bbox, bands=['B04', 'B08'])

        if 'B04' not in bands or 'B08' not in bands:
            logger.error("❌ Failed to download required bands")
            return None

        # Compute NDVI
        ndvi = self.compute_ndvi(bands['B04'], bands['B08'])

        # Save NDVI
        output_path = self.ndvi_dir / f"{region_name}_ndvi_{scene_date.replace('-', '')}.tif"
        self.save_ndvi_geotiff(ndvi, output_path, best_item, bbox)

        logger.info("\n" + "=" * 60)
        logger.info("✅ NDVI DOWNLOAD COMPLETE")
        logger.info(f"📁 Output: {output_path}")
        logger.info("=" * 60)

        return output_path


def main():
    """Download NDVI for Berlin (2018 and 2024)"""

    loader = RealSentinel2Loader()

    # Berlin bounding box
    BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)

    print("\n" + "=" * 60)
    print("REAL SENTINEL-2 NDVI DOWNLOAD WORKFLOW")
    print("=" * 60)
    print("\nThis script will download real Sentinel-2 data from")
    print("Microsoft Planetary Computer (free, no API key needed)")
    print("\nRegion: Berlin, Germany")
    print("Dates: 2018-07-15 and 2024-07-15")
    print("\nNote: This may take a few minutes depending on your connection.")
    print("=" * 60)

    input("\nPress Enter to start download...")

    # Download 2018 NDVI
    print("\n\n🔵 DOWNLOADING 2018 DATA...")
    ndvi_2018 = loader.download_and_compute_ndvi(
        region_name="berlin",
        bbox=BERLIN_BBOX,
        date="2018-07-15",
        max_cloud=30.0  # Slightly higher tolerance for older data
    )

    # Download 2024 NDVI
    print("\n\n🔵 DOWNLOADING 2024 DATA...")
    ndvi_2024 = loader.download_and_compute_ndvi(
        region_name="berlin",
        bbox=BERLIN_BBOX,
        date="2024-07-15",
        max_cloud=20.0
    )

    # Summary
    print("\n\n" + "=" * 60)
    print("📊 DOWNLOAD SUMMARY")
    print("=" * 60)

    if ndvi_2018:
        print(f"✅ 2018 NDVI: {ndvi_2018}")
    else:
        print("❌ 2018 NDVI: Failed to download")

    if ndvi_2024:
        print(f"✅ 2024 NDVI: {ndvi_2024}")
    else:
        print("❌ 2024 NDVI: Failed to download")

    if ndvi_2018 and ndvi_2024:
        print("\n🎉 SUCCESS! Both NDVI datasets downloaded.")
        print("\n📋 Next steps:")
        print("  1. Run NDVI change detection:")
        print("     python examples/04_ndvi_change_detection.py")
        print("\n  2. Or test via API:")
        print("     python -m uvicorn app.main:app --reload")
    else:
        print("\n⚠️  Some downloads failed. Check the logs above.")
        print("   Try increasing max_cloud or adjusting dates.")

    print("=" * 60)


if __name__ == "__main__":
    main()
