"""
Data ingestion script to download and load real geospatial data
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders import (
    OSMLoader,
    SentinelLoader,
    DEMLoader,
    GADMLoader,
    CopernicusLoader
)
import geopandas as gpd
from sqlalchemy import create_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataIngestion:
    """Ingest real geospatial data into the system"""

    def __init__(self, db_url: str = "postgresql://postgres:postgres@localhost:5432/geoassist"):
        self.db_engine = create_engine(db_url)

        # Initialize loaders
        self.osm_loader = OSMLoader()
        self.sentinel_loader = SentinelLoader()
        self.dem_loader = DEMLoader()
        self.gadm_loader = GADMLoader()
        self.copernicus_loader = CopernicusLoader()

    def ingest_osm_data(self, region_name: str, bbox: tuple):
        """
        Ingest OpenStreetMap data for a region

        Args:
            region_name: Name of region (e.g., 'berlin')
            bbox: (min_lon, min_lat, max_lon, max_lat)
        """

        logger.info(f"Ingesting OSM data for {region_name}")

        # Download buildings
        try:
            buildings = self.osm_loader.query_overpass(bbox, ['building'])
            if not buildings.empty:
                buildings['region'] = region_name
                buildings['building_type'] = buildings.get('building', 'yes')

                # Rename osm_id column if it exists
                if 'osm_id' in buildings.columns:
                    buildings = buildings.rename(columns={'id': 'id_orig'})

                # Save to PostGIS
                buildings[['osm_id', 'building_type', 'geometry', 'region']].to_postgis(
                    'osm_buildings',
                    self.db_engine,
                    schema='vector',
                    if_exists='append',
                    index=False
                )

                logger.info(f"Loaded {len(buildings)} buildings")
        except Exception as e:
            logger.error(f"Failed to load buildings: {e}")

        # Download hospitals
        try:
            hospitals = self.osm_loader.query_overpass(bbox, ['hospital'])
            if not hospitals.empty:
                hospitals['region'] = region_name

                hospitals[['osm_id', 'name', 'geometry', 'region']].to_postgis(
                    'osm_hospitals',
                    self.db_engine,
                    schema='vector',
                    if_exists='append',
                    index=False
                )

                logger.info(f"Loaded {len(hospitals)} hospitals")
        except Exception as e:
            logger.error(f"Failed to load hospitals: {e}")

        # Download roads
        try:
            roads = self.osm_loader.query_overpass(bbox, ['road'])
            if not roads.empty:
                roads['region'] = region_name
                roads['highway_type'] = roads.get('highway', 'unknown')

                roads[['osm_id', 'name', 'highway_type', 'geometry', 'region']].to_postgis(
                    'osm_roads',
                    self.db_engine,
                    schema='vector',
                    if_exists='append',
                    index=False
                )

                logger.info(f"Loaded {len(roads)} roads")
        except Exception as e:
            logger.error(f"Failed to load roads: {e}")

    def ingest_admin_boundaries(self, country_code: str, admin_level: int = 1):
        """
        Ingest administrative boundaries from GADM

        Args:
            country_code: ISO 3166-1 alpha-3 code
            admin_level: Administrative level
        """

        logger.info(f"Ingesting admin boundaries for {country_code}")

        try:
            gdf = self.gadm_loader.load_boundaries(country_code, admin_level)

            # Prepare for database
            gdf['country_code'] = country_code
            gdf['admin_level'] = admin_level

            # Ensure MultiPolygon geometry
            from shapely.geometry import MultiPolygon, Polygon

            def to_multipolygon(geom):
                if isinstance(geom, Polygon):
                    return MultiPolygon([geom])
                return geom

            gdf['geometry'] = gdf['geometry'].apply(to_multipolygon)

            # Select relevant columns
            cols = ['country_code', 'admin_level', 'geometry']
            if 'NAME_1' in gdf.columns:
                gdf['name'] = gdf['NAME_1']
                cols.append('name')

            gdf[cols].to_postgis(
                'admin_boundaries',
                self.db_engine,
                schema='vector',
                if_exists='append',
                index=False
            )

            logger.info(f"Loaded {len(gdf)} admin boundaries")

        except Exception as e:
            logger.error(f"Failed to load admin boundaries: {e}")

    def ingest_sentinel_data(self, region_name: str, bbox: tuple, date: str):
        """
        Ingest Sentinel-2 imagery (saved as raster files)

        Args:
            region_name: Name of region
            bbox: Bounding box
            date: Target date (YYYY-MM-DD)
        """

        logger.info(f"Ingesting Sentinel-2 data for {region_name} on {date}")

        try:
            scene_path = self.sentinel_loader.download_for_region(
                region_name,
                bbox,
                date
            )

            if scene_path:
                logger.info(f"Downloaded Sentinel-2 scene: {scene_path}")

                # Register in catalog
                self._register_dataset(
                    name=f"sentinel2_{region_name}_{date}",
                    type='raster',
                    source='Sentinel-2',
                    description=f"Sentinel-2 imagery for {region_name}",
                    bbox=bbox,
                    metadata={'date': date, 'path': str(scene_path)}
                )

        except Exception as e:
            logger.error(f"Failed to load Sentinel-2: {e}")

    def ingest_land_cover(self, tile_code: str, year: int = 2021):
        """
        Ingest ESA WorldCover land cover data

        Args:
            tile_code: Tile code (e.g., 'N51E000')
            year: Year
        """

        logger.info(f"Ingesting WorldCover {year} tile {tile_code}")

        try:
            raster_path = self.copernicus_loader.download_worldcover(tile_code, year)

            logger.info(f"Downloaded WorldCover: {raster_path}")

            # Register in catalog
            self._register_dataset(
                name=f"worldcover_{tile_code}_{year}",
                type='raster',
                source='ESA WorldCover',
                description=f"Land cover classification",
                metadata={'tile': tile_code, 'year': year, 'path': str(raster_path)}
            )

        except Exception as e:
            logger.error(f"Failed to load WorldCover: {e}")

    def _register_dataset(self, name: str, type: str, source: str,
                         description: str, bbox: tuple = None, metadata: dict = None):
        """Register dataset in catalog"""

        from sqlalchemy import text

        with self.db_engine.connect() as conn:
            if bbox:
                bbox_wkt = f"POLYGON(({bbox[0]} {bbox[1]}, {bbox[2]} {bbox[1]}, " \
                          f"{bbox[2]} {bbox[3]}, {bbox[0]} {bbox[3]}, {bbox[0]} {bbox[1]}))"
                bbox_geom = f"ST_GeomFromText('{bbox_wkt}', 4326)"
            else:
                bbox_geom = "NULL"

            query = text(f"""
                INSERT INTO metadata.dataset_catalog
                (name, type, source, description, bbox, metadata)
                VALUES
                (:name, :type, :source, :description, {bbox_geom}, :metadata)
                ON CONFLICT (name) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
            """)

            import json
            conn.execute(query, {
                'name': name,
                'type': type,
                'source': source,
                'description': description,
                'metadata': json.dumps(metadata or {})
            })
            conn.commit()


def main():
    """Main ingestion workflow"""

    ingestion = DataIngestion()

    # Example regions to ingest
    regions = {
        'berlin': {
            'bbox': (13.088, 52.338, 13.761, 52.675),
            'country_code': 'DEU',
            'worldcover_tile': 'N51E013'
        },
        'london': {
            'bbox': (-0.510, 51.286, 0.334, 51.686),
            'country_code': 'GBR',
            'worldcover_tile': 'N51E000'
        }
    }

    # Choose which region to ingest
    region_name = 'berlin'
    region_config = regions[region_name]

    # 1. Ingest OSM data
    logger.info(f"\n=== Ingesting OSM data for {region_name} ===")
    ingestion.ingest_osm_data(region_name, region_config['bbox'])

    # 2. Ingest administrative boundaries
    logger.info(f"\n=== Ingesting admin boundaries ===")
    ingestion.ingest_admin_boundaries(region_config['country_code'], admin_level=1)

    # 3. Ingest land cover
    logger.info(f"\n=== Ingesting land cover data ===")
    ingestion.ingest_land_cover(region_config['worldcover_tile'], year=2021)

    # 4. Ingest Sentinel-2 (optional - requires more setup)
    # ingestion.ingest_sentinel_data(region_name, region_config['bbox'], '2024-06-15')

    logger.info("\n=== Data ingestion completed! ===")


if __name__ == "__main__":
    main()
