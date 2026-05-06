"""
Download OpenStreetMap data for Berlin
Fetches hospitals, toilets, pharmacies, and other key amenities
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import from app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders.osm_loader import OSMLoader
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Berlin bounding box (min_lon, min_lat, max_lon, max_lat)
BERLIN_BBOX = (13.088, 52.338, 13.761, 52.675)
CITY_NAME = "berlin"

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "vector" / "osm"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def download_berlin_features():
    """Download all Berlin OSM features"""

    logger.info("=" * 70)
    logger.info("Berlin OSM Data Download")
    logger.info("=" * 70)
    logger.info(f"Bounding Box: {BERLIN_BBOX}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    # Initialize loader
    loader = OSMLoader(data_dir=str(OUTPUT_DIR))

    # Define features to download
    features_to_download = [
        ('hospitals', ['hospital'], 'Medical facilities'),
        ('toilets', ['toilet'], 'Public toilets'),
        ('pharmacies', ['pharmacy'], 'Pharmacies and drugstores'),
        ('fire_stations', ['fire_station'], 'Fire stations'),
        ('police_stations', ['police'], 'Police stations'),
        ('parks', ['park'], 'Parks and recreational areas'),
        ('schools', ['school'], 'Educational institutions'),
        ('restaurants', ['restaurant'], 'Restaurants'),
        ('transport_stops', ['transport_stop'], 'Public transport stops'),
    ]

    results = {}
    successful_downloads = 0
    failed_downloads = 0

    # Download each feature type
    for feature_name, feature_tags, description in features_to_download:
        logger.info("")
        logger.info(f"Downloading: {feature_name} ({description})")
        logger.info("-" * 70)

        try:
            # Query Overpass API
            gdf = loader.query_overpass(
                bbox=BERLIN_BBOX,
                features=feature_tags,
                timeout=180
            )

            if len(gdf) > 0:
                # Save to file
                output_file = OUTPUT_DIR / f"{CITY_NAME}_{feature_name}.geojson"
                gdf.to_file(output_file, driver='GeoJSON')

                results[feature_name] = {
                    'count': len(gdf),
                    'file': str(output_file),
                    'status': 'success'
                }

                logger.info(f"✅ Successfully downloaded {len(gdf)} {feature_name}")
                logger.info(f"   Saved to: {output_file.name}")

                # Show sample attributes
                if 'name' in gdf.columns:
                    sample_names = gdf['name'].dropna().head(3).tolist()
                    if sample_names:
                        logger.info(f"   Sample names: {', '.join(sample_names)}")

                successful_downloads += 1
            else:
                logger.warning(f"⚠️  No {feature_name} found in Berlin bbox")
                results[feature_name] = {
                    'count': 0,
                    'status': 'empty'
                }

        except Exception as e:
            logger.error(f"❌ Failed to download {feature_name}: {str(e)}")
            results[feature_name] = {
                'status': 'failed',
                'error': str(e)
            }
            failed_downloads += 1

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("Download Summary")
    logger.info("=" * 70)
    logger.info(f"Total features attempted: {len(features_to_download)}")
    logger.info(f"Successful downloads: {successful_downloads}")
    logger.info(f"Failed downloads: {failed_downloads}")
    logger.info("")

    total_features = sum(r['count'] for r in results.values() if 'count' in r)
    logger.info(f"Total OSM features downloaded: {total_features:,}")
    logger.info("")

    # Detailed results
    for feature_name, result in results.items():
        if result['status'] == 'success':
            logger.info(f"  ✅ {feature_name:20s}: {result['count']:6,} features")
        elif result['status'] == 'empty':
            logger.info(f"  ⚠️  {feature_name:20s}: No data found")
        else:
            logger.info(f"  ❌ {feature_name:20s}: Failed")

    logger.info("")
    logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    return results

if __name__ == "__main__":
    try:
        results = download_berlin_features()

        # Exit with appropriate code
        failed_count = sum(1 for r in results.values() if r['status'] == 'failed')
        if failed_count > 0:
            logger.warning(f"\n⚠️  {failed_count} downloads failed")
            sys.exit(1)
        else:
            logger.info("\n✅ All downloads completed successfully!")
            sys.exit(0)

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Download interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {str(e)}")
        sys.exit(1)
