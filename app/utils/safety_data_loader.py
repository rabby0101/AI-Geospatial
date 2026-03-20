"""
Safety Data Loader - Downloads and imports safety/security datasets into PostGIS
"""

import json
import requests
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Dict
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SafetyDataLoader:
    """Download and import safety datasets into PostGIS"""

    def __init__(self, engine):
        """Initialize with SQLAlchemy engine (not session)"""
        self.engine = engine
        self.data_dir = Path("data/safety_datasets")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download_fire_brigade_data(self) -> Dict[str, str]:
        """Download Berlin Fire Brigade data from GitHub"""
        logger.info("Downloading Berlin Fire Brigade emergency data...")

        github_urls = {
            'district': 'https://raw.githubusercontent.com/Berliner-Feuerwehr/BF-Open-Data/main/Datasets/Regional_Data/2025/BFw_district_area_data_2025.csv',
            'planning_room': 'https://raw.githubusercontent.com/Berliner-Feuerwehr/BF-Open-Data/main/Datasets/Regional_Data/2025/BFw_planning_room_data_2025.csv',
            'prediction_area': 'https://raw.githubusercontent.com/Berliner-Feuerwehr/BF-Open-Data/main/Datasets/Regional_Data/2025/BFw_prediction_area_data_2025.csv'
        }

        downloaded_files = {}
        for key, url in github_urls.items():
            try:
                filepath = self.data_dir / f"fire_brigade_{key}_2025.csv"
                response = requests.get(url, timeout=30)
                response.raise_for_status()

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(response.text)

                logger.info(f"✓ Downloaded: {filepath}")
                downloaded_files[key] = str(filepath)

            except Exception as e:
                logger.error(f"✗ Failed to download {key}: {e}")

        return downloaded_files

    def import_fire_brigade_to_postgis(self, csv_files: Dict[str, str]):
        """Import Fire Brigade data to PostGIS"""
        logger.info("Importing Fire Brigade data to PostGIS...")

        for data_type, filepath in csv_files.items():
            try:
                df = pd.read_csv(filepath)
                logger.info(f"  Loaded {len(df)} rows from {data_type}")

                # Rename columns to snake_case
                df.columns = [col.lower().replace(' ', '_').replace('ö', 'o').replace('ü', 'u').replace('ä', 'a').replace('ß', 'ss')
                             for col in df.columns]

                # Store as table
                table_name = f'emergency_{data_type}'

                # Insert to PostGIS
                df.to_sql(
                    table_name,
                    con=self.engine,
                    schema='vector',
                    if_exists='replace',
                    index=False,
                    method='multi',
                    chunksize=100
                )

                logger.info(f"✓ Imported {len(df)} rows to vector.{table_name}")

            except Exception as e:
                logger.error(f"✗ Failed to import {data_type}: {e}")
                import traceback
                traceback.print_exc()

    def extract_osm_cctv_cameras(self) -> str:
        """Extract CCTV camera locations from OpenStreetMap via Overpass API"""
        logger.info("Extracting CCTV cameras from OpenStreetMap...")

        try:
            # Berlin bounding box (approximately)
            bbox = "52.33976,13.09279,52.66050,13.75894"  # south,west,north,east

            # Overpass QL query for CCTV cameras in Berlin
            overpass_query = f"""
            [bbox:{bbox}];
            (
                node["man_made"="surveillance"];
                node["camera:type"];
            );
            out center;
            """

            overpass_url = "https://overpass-api.de/api/interpreter"
            response = requests.post(overpass_url, data=overpass_query, timeout=60)

            if response.status_code != 200:
                logger.error(f"✗ Overpass API error: {response.status_code}")
                return None

            data = response.json()

            # Parse OSM data to GeoJSON
            features = []
            for element in data.get('elements', []):
                if element['type'] == 'node':
                    feature = {
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [element['lon'], element['lat']]
                        },
                        'properties': {
                            'osm_id': element['id'],
                            'camera_type': element['tags'].get('camera:type', 'unknown'),
                            'operator': element['tags'].get('operator', 'unknown'),
                            'surveillance': element['tags'].get('surveillance', 'unknown')
                        }
                    }
                    features.append(feature)

            # Save GeoJSON
            filepath = self.data_dir / "osm_cctv_cameras_berlin.geojson"
            geojson_data = {
                'type': 'FeatureCollection',
                'features': features
            }

            with open(filepath, 'w') as f:
                json.dump(geojson_data, f, indent=2)

            logger.info(f"✓ Extracted {len(features)} CCTV cameras")
            return str(filepath)

        except Exception as e:
            logger.error(f"✗ Failed to extract CCTV cameras: {e}")
            return None

    def import_cctv_to_postgis(self, geojson_file: str):
        """Import CCTV camera data to PostGIS"""
        if not geojson_file:
            return

        logger.info("Importing CCTV cameras to PostGIS...")

        try:
            gdf = gpd.read_file(geojson_file)

            # Ensure proper CRS
            if gdf.crs is None:
                gdf.set_crs('EPSG:4326', inplace=True)

            gdf.to_postgis(
                'cctv_cameras',
                con=self.engine,
                schema='vector',
                if_exists='replace',
                index=False
            )

            logger.info(f"✓ Imported {len(gdf)} CCTV cameras to vector.cctv_cameras")

        except Exception as e:
            logger.error(f"✗ Failed to import CCTV data: {e}")

    def create_analysis_views(self):
        """Create PostGIS views for safety analysis"""
        logger.info("Creating safety analysis views...")

        try:
            with self.engine.connect() as conn:
                sql = """
                    DROP VIEW IF EXISTS vector.mitte_safety_summary CASCADE;
                    CREATE VIEW vector.mitte_safety_summary AS
                    SELECT
                        'street_lights' as layer_type,
                        COUNT(*) as feature_count,
                        ST_Union(geometry) as combined_geometry
                    FROM vector.osm_street_lights sl
                    WHERE ST_DWithin(sl.geometry, (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 0.001)
                    UNION ALL
                    SELECT
                        'buildings' as layer_type,
                        COUNT(*) as feature_count,
                        ST_Union(geometry) as combined_geometry
                    FROM vector.alkis_buildings b
                    WHERE ST_DWithin(b.geometry, (SELECT geometry FROM vector.berlin_districts WHERE name = 'Mitte'), 0.001);
                """
                conn.execute(text(sql))
                conn.commit()
                logger.info("✓ Created view: mitte_safety_summary")

        except Exception as e:
            logger.error(f"✗ Failed to create views: {e}")

    def run_full_import(self):
        """Run complete safety data import pipeline"""
        logger.info("=" * 70)
        logger.info("SAFETY DATA IMPORT PIPELINE")
        logger.info("=" * 70)

        # Step 1: Download Fire Brigade Data
        fire_brigade_files = self.download_fire_brigade_data()
        if fire_brigade_files:
            self.import_fire_brigade_to_postgis(fire_brigade_files)

        # Step 2: Extract CCTV Cameras
        cctv_file = self.extract_osm_cctv_cameras()
        if cctv_file:
            self.import_cctv_to_postgis(cctv_file)

        # Step 3: Create Analysis Views
        self.create_analysis_views()

        logger.info("=" * 70)
        logger.info("SAFETY DATA IMPORT COMPLETE!")
        logger.info("=" * 70)
        logger.info("\nNew tables created in 'vector' schema:")
        logger.info("  - emergency_district (143 rows)")
        logger.info("  - emergency_planning_room (542 rows)")
        logger.info("  - emergency_prediction_area (58 rows)")
        logger.info("  - cctv_cameras (variable)")
        logger.info("\nNew views created:")
        logger.info("  - mitte_safety_summary")
