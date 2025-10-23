"""
Setup PostGIS database and create schema for geospatial data
"""

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PostGISSetup:
    """Setup and initialize PostGIS database"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "postgres",
        database: str = "geoassist"
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def create_database(self):
        """Create database if it doesn't exist"""

        # Connect to default postgres database
        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        cursor = conn.cursor()

        # Check if database exists
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (self.database,)
        )

        if cursor.fetchone():
            logger.info(f"Database '{self.database}' already exists")
        else:
            cursor.execute(f'CREATE DATABASE {self.database}')
            logger.info(f"Created database '{self.database}'")

        cursor.close()
        conn.close()

    def enable_postgis(self):
        """Enable PostGIS extension"""

        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database
        )

        cursor = conn.cursor()

        # Enable PostGIS
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology")

        conn.commit()

        # Verify
        cursor.execute("SELECT PostGIS_Version()")
        version = cursor.fetchone()
        logger.info(f"PostGIS version: {version[0]}")

        cursor.close()
        conn.close()

    def create_schemas(self):
        """Create schemas for organizing data"""

        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database
        )

        cursor = conn.cursor()

        schemas = [
            "vector",      # Vector datasets
            "raster",      # Raster datasets
            "analysis",    # Analysis results
            "metadata"     # Dataset metadata
        ]

        for schema in schemas:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            logger.info(f"Created schema: {schema}")

        conn.commit()
        cursor.close()
        conn.close()

    def create_tables(self):
        """Create tables for storing datasets"""

        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database
        )

        cursor = conn.cursor()

        # Dataset catalog table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata.dataset_catalog (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                type VARCHAR(50) NOT NULL,  -- 'vector' or 'raster'
                source VARCHAR(255),
                description TEXT,
                bbox GEOMETRY(Polygon, 4326),
                crs VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB
            )
        """)

        # OSM buildings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector.osm_buildings (
                id SERIAL PRIMARY KEY,
                osm_id BIGINT,
                name VARCHAR(255),
                building_type VARCHAR(100),
                geometry GEOMETRY(Polygon, 4326),
                tags JSONB,
                region VARCHAR(100)
            )
        """)

        # OSM hospitals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector.osm_hospitals (
                id SERIAL PRIMARY KEY,
                osm_id BIGINT,
                name VARCHAR(255),
                geometry GEOMETRY(Point, 4326),
                tags JSONB,
                region VARCHAR(100)
            )
        """)

        # OSM roads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector.osm_roads (
                id SERIAL PRIMARY KEY,
                osm_id BIGINT,
                name VARCHAR(255),
                highway_type VARCHAR(100),
                geometry GEOMETRY(LineString, 4326),
                tags JSONB,
                region VARCHAR(100)
            )
        """)

        # Administrative boundaries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector.admin_boundaries (
                id SERIAL PRIMARY KEY,
                country_code VARCHAR(3),
                admin_level INTEGER,
                name VARCHAR(255),
                geometry GEOMETRY(MultiPolygon, 4326),
                properties JSONB
            )
        """)

        # Land cover table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector.land_cover (
                id SERIAL PRIMARY KEY,
                region VARCHAR(100),
                class_code INTEGER,
                class_name VARCHAR(100),
                geometry GEOMETRY(Polygon, 4326),
                area_sqm FLOAT,
                source VARCHAR(100)
            )
        """)

        # Create spatial indices
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_buildings_geom
            ON vector.osm_buildings USING GIST(geometry)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hospitals_geom
            ON vector.osm_hospitals USING GIST(geometry)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_roads_geom
            ON vector.osm_roads USING GIST(geometry)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_geom
            ON vector.admin_boundaries USING GIST(geometry)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_landcover_geom
            ON vector.land_cover USING GIST(geometry)
        """)

        conn.commit()

        logger.info("Created tables and spatial indices")

        cursor.close()
        conn.close()

    def setup_all(self):
        """Run complete setup"""

        logger.info("Starting PostGIS setup...")

        self.create_database()
        self.enable_postgis()
        self.create_schemas()
        self.create_tables()

        logger.info("PostGIS setup completed successfully!")


if __name__ == "__main__":
    # Get database credentials from environment or use defaults
    import getpass
    default_user = getpass.getuser()  # Use current system user

    setup = PostGISSetup(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER", default_user),
        password=os.getenv("DB_PASSWORD", ""),  # No password for local Homebrew install
        database=os.getenv("DB_NAME", "geoassist")
    )

    setup.setup_all()
