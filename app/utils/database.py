import os
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
import geopandas as gpd
from dotenv import load_dotenv

load_dotenv()

# Database configuration from environment variables
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

# Connection URL
# Handle empty password (common for local Homebrew PostgreSQL)
if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


class DatabaseManager:
    """Manages database connections and spatial queries"""

    def __init__(self):
        self.engine = None
        self.SessionLocal = None

    def initialize(self):
        """Initialize database engine and session maker with connection pooling"""
        self.engine = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=5,          # Keep 5 connections alive
            max_overflow=10,      # Allow up to 10 additional connections
            pool_pre_ping=True,   # Verify connections before using
            pool_recycle=3600,    # Recycle connections after 1 hour
            echo=False
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    @contextmanager
    def get_session(self):
        """Context manager for database sessions"""
        if not self.SessionLocal:
            self.initialize()

        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            if not self.engine:
                self.initialize()

            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT PostGIS_Version();"))
                version = result.fetchone()
                print(f"PostGIS Version: {version[0] if version else 'Unknown'}")
                return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False

    def load_vector_from_db(self, table_name: str, schema: str = "vector") -> gpd.GeoDataFrame:
        """
        Load vector data from PostGIS database.

        Args:
            table_name: Name of the table
            schema: Database schema (default: vector)

        Returns:
            GeoDataFrame with the data
        """
        if not self.engine:
            self.initialize()

        query = f"SELECT * FROM {schema}.{table_name}"
        gdf = gpd.read_postgis(query, self.engine, geom_col="geometry")
        return gdf

    def save_vector_to_db(
        self,
        gdf: gpd.GeoDataFrame,
        table_name: str,
        schema: str = "vector",
        if_exists: str = "replace"
    ):
        """
        Save GeoDataFrame to PostGIS database.

        Args:
            gdf: GeoDataFrame to save
            table_name: Name of the table
            schema: Database schema (default: vector)
            if_exists: What to do if table exists ('replace', 'append', 'fail')
        """
        if not self.engine:
            self.initialize()

        gdf.to_postgis(
            table_name,
            self.engine,
            schema=schema,
            if_exists=if_exists,
            index=False
        )

    def execute_spatial_query(self, query: str, geom_col: str = "geometry") -> gpd.GeoDataFrame:
        """
        Execute a spatial SQL query and return results as GeoDataFrame.

        Args:
            query: SQL query string
            geom_col: Name of geometry column (default: geometry)

        Returns:
            GeoDataFrame with results
        """
        if not self.engine:
            self.initialize()

        # Use manual conversion approach due to geopandas/sqlalchemy compatibility issues
        try:
            import pandas as pd
            from shapely import wkb, wkt
            from geoalchemy2 import Geometry
            from geoalchemy2.shape import to_shape

            # Execute query and get raw results
            with self.engine.connect() as conn:
                result = conn.execute(text(query))
                rows = result.fetchall()
                columns = result.keys()

            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in rows]

            if not data:
                # Return empty GeoDataFrame with correct structure
                empty_gdf = gpd.GeoDataFrame(columns=columns, crs="EPSG:4326")
                # Set the geometry column
                if geom_col in empty_gdf.columns:
                    empty_gdf = empty_gdf.set_geometry(geom_col)
                return empty_gdf

            # Create DataFrame
            df = pd.DataFrame(data)

            # Check for geometry column
            if geom_col not in df.columns:
                raise ValueError(f"Query result missing geometry column '{geom_col}'")

            # Convert geometry column to shapely objects
            def convert_geometry(geom):
                if geom is None:
                    return None
                if isinstance(geom, (bytes, memoryview)):
                    # WKB format (binary)
                    try:
                        return wkb.loads(bytes(geom))
                    except Exception:
                        return None
                elif isinstance(geom, str):
                    # Check if it's hex-encoded WKB (EWKB from PostGIS)
                    if geom and all(c in '0123456789ABCDEFabcdef' for c in geom):
                        try:
                            # Hex-encoded WKB - decode and load
                            return wkb.loads(bytes.fromhex(geom))
                        except Exception:
                            pass
                    # Try WKT format
                    try:
                        return wkt.loads(geom)
                    except Exception:
                        return None
                else:
                    # Try to use geoalchemy2 if available
                    try:
                        return to_shape(geom)
                    except Exception:
                        # Already a shapely object or unknown type
                        return geom

            df[geom_col] = df[geom_col].apply(convert_geometry)

            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(df, geometry=geom_col, crs="EPSG:4326")

            return gdf

        except Exception as e:
            raise Exception(f"Spatial query failed: {str(e)}")

    def buffer_query(
        self,
        table_name: str,
        distance: float,
        schema: str = "vector"
    ) -> gpd.GeoDataFrame:
        """
        Create buffer around features using PostGIS.

        Args:
            table_name: Source table
            distance: Buffer distance in meters
            schema: Database schema

        Returns:
            GeoDataFrame with buffered geometries
        """
        query = f"""
        SELECT
            *,
            ST_Buffer(geometry::geography, {distance})::geometry as geometry
        FROM {schema}.{table_name}
        """
        return self.execute_spatial_query(query)

    def intersection_query(
        self,
        table1: str,
        table2: str,
        schema: str = "vector"
    ) -> gpd.GeoDataFrame:
        """
        Find spatial intersection between two tables.

        Args:
            table1: First table name
            table2: Second table name
            schema: Database schema

        Returns:
            GeoDataFrame with intersecting features
        """
        query = f"""
        SELECT
            a.*,
            ST_Intersection(a.geometry, b.geometry) as geometry
        FROM {schema}.{table1} a, {schema}.{table2} b
        WHERE ST_Intersects(a.geometry, b.geometry)
        """
        return self.execute_spatial_query(query)

    def within_distance_query(
        self,
        table1: str,
        table2: str,
        distance: float,
        schema: str = "vector"
    ) -> gpd.GeoDataFrame:
        """
        Find features in table1 within distance of features in table2.

        Args:
            table1: First table (features to return)
            table2: Second table (reference features)
            distance: Distance in meters
            schema: Database schema

        Returns:
            GeoDataFrame with features within distance
        """
        query = f"""
        SELECT DISTINCT a.*
        FROM {schema}.{table1} a, {schema}.{table2} b
        WHERE ST_DWithin(a.geometry::geography, b.geometry::geography, {distance})
        """
        return self.execute_spatial_query(query)

    def get_available_tables(self, schema: str = "vector") -> list:
        """
        Get list of available tables in schema.

        Args:
            schema: Database schema to query

        Returns:
            List of table names
        """
        if not self.engine:
            self.initialize()

        query = f"""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = '{schema}'
        ORDER BY tablename
        """

        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return [row[0] for row in result]

    def get_table_info(self, table_name: str, schema: str = "vector") -> dict:
        """
        Get information about a table.

        Args:
            table_name: Name of the table
            schema: Database schema

        Returns:
            Dictionary with table info
        """
        if not self.engine:
            self.initialize()

        # Get row count
        count_query = f"SELECT COUNT(*) FROM {schema}.{table_name}"

        # Get geometry type
        geom_query = f"""
        SELECT type
        FROM geometry_columns
        WHERE f_table_schema = '{schema}'
        AND f_table_name = '{table_name}'
        """

        # Get column info
        columns_query = f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = '{schema}'
        AND table_name = '{table_name}'
        """

        with self.engine.connect() as conn:
            count = conn.execute(text(count_query)).scalar()
            geom_type_result = conn.execute(text(geom_query)).fetchone()
            geom_type = geom_type_result[0] if geom_type_result else "Unknown"

            columns = conn.execute(text(columns_query)).fetchall()
            column_info = [{"name": col[0], "type": col[1]} for col in columns]

        return {
            "table_name": table_name,
            "schema": schema,
            "row_count": count,
            "geometry_type": geom_type,
            "columns": column_info
        }

    def execute_query(self, query: str):
        """
        Execute a non-spatial SQL query and return results as DataFrame.

        This is for aggregation/statistics queries that don't return geometries.

        Args:
            query: SQL query string

        Returns:
            pandas.DataFrame with results
        """
        if not self.engine:
            self.initialize()

        try:
            import pandas as pd

            with self.engine.connect() as conn:
                result = conn.execute(text(query))
                # Get column names
                columns = result.keys()
                # Fetch all rows
                rows = result.fetchall()

                # Create DataFrame
                df = pd.DataFrame(rows, columns=columns)
                return df

        except Exception as e:
            raise Exception(f"Query execution failed: {str(e)}")


# Global instance
db_manager = DatabaseManager()
