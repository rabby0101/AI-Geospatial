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
            echo=False,
            connect_args={"options": "-csearch_path=vector,public"}
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
                import logging
                logging.warning(f"Query result missing geometry column '{geom_col}'. Adding dummy None geometries.")
                df[geom_col] = None

            # Convert geometry column to shapely objects
            def convert_geometry(geom):
                if geom is None:
                    return None
                if isinstance(geom, (bytes, memoryview)):
                    # WKB format (binary)
                    try:
                        converted = wkb.loads(bytes(geom))
                        return converted
                    except Exception as e:
                        import logging
                        logging.warning(f"Failed to convert WKB geometry: {e}")
                        return None
                elif isinstance(geom, str):
                    # Check if it's hex-encoded WKB (EWKB from PostGIS)
                    if geom and all(c in '0123456789ABCDEFabcdef' for c in geom):
                        try:
                            # Hex-encoded WKB - decode and load
                            converted = wkb.loads(bytes.fromhex(geom))
                            return converted
                        except Exception as e:
                            import logging
                            logging.warning(f"Failed to convert hex-encoded WKB: {e}")
                            pass
                    # Try WKT format
                    try:
                        converted = wkt.loads(geom)
                        return converted
                    except Exception as e:
                        import logging
                        logging.warning(f"Failed to convert WKT geometry: {e}")
                        return None
                else:
                    # Try to use geoalchemy2 if available
                    try:
                        return to_shape(geom)
                    except Exception:
                        # Already a shapely object or unknown type
                        return geom

            # Apply conversion with tracking
            converted_geoms = df[geom_col].apply(convert_geometry)
            null_count_before = df[geom_col].isna().sum()
            null_count_after = converted_geoms.isna().sum()
            if null_count_after > null_count_before:
                import logging
                logging.warning(f"Geometry conversion failed for {null_count_after - null_count_before} features. "
                               f"Check for corrupt or unsupported geometry formats.")
            df[geom_col] = converted_geoms

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

        # Get column info with rich descriptions
        columns_query = f"""
        SELECT 
            c.column_name, 
            c.data_type,
            md.description,
            md.example_value
        FROM information_schema.columns c
        LEFT JOIN metadata.column_descriptions md 
            ON c.table_name = md.table_name 
            AND c.column_name = md.column_name
        WHERE c.table_schema = '{schema}'
        AND c.table_name = '{table_name}'
        """

        with self.engine.connect() as conn:
            count = conn.execute(text(count_query)).scalar()
            geom_type_result = conn.execute(text(geom_query)).fetchone()
            geom_type = geom_type_result[0] if geom_type_result else "Unknown"

            columns = conn.execute(text(columns_query)).fetchall()
            column_info = [
                {
                    "name": col[0], 
                    "type": col[1],
                    "description": col[2] if col[2] else "",
                    "example_values": col[3] if col[3] else ""
                } 
                for col in columns
            ]

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

    def get_schema_with_descriptions(self, schema: str = "vector") -> list:
        """
        Get all tables with descriptions from metadata.table_descriptions.

        This is the single source of truth for LLM knowledge about available tables.
        Reads from metadata.table_descriptions which is updated via the UI.
        Fetches live schema from database including descriptions, row counts, geometry types.

        Args:
            schema: Database schema to query (default: vector)

        Returns:
            List of dicts with table info:
            [
                {
                    "table": "osm_hospitals",
                    "description": "Emergency and general hospitals...",
                    "row_count": 59,
                    "geometry": "POINT",
                    "columns": ["osm_id", "name", "operator", "geometry"]
                },
                ...
            ]
        """
        if not self.engine:
            self.initialize()

        try:
            with self.engine.connect() as conn:
                # Try to fetch usage_hint if the column exists (added by Step 1 migration)
                try:
                    query = text("""
                        SELECT
                            table_name,
                            description,
                            row_count,
                            geometry_type,
                            usage_hint,
                            key_columns
                        FROM metadata.table_descriptions
                        ORDER BY table_name
                    """)
                    result = conn.execute(query)
                    metadata = {row[0]: {
                        "description": row[1],
                        "row_count": row[2],
                        "geometry_type": row[3],
                        "usage_hint": row[4] or "",
                        "key_columns": list(row[5]) if row[5] else [],
                    } for row in result}
                except Exception:
                    # usage_hint/key_columns columns not yet added; fall back to basic columns
                    query = text("""
                        SELECT
                            table_name,
                            description,
                            row_count,
                            geometry_type
                        FROM metadata.table_descriptions
                        ORDER BY table_name
                    """)
                    result = conn.execute(query)
                    metadata = {row[0]: {
                        "description": row[1],
                        "row_count": row[2],
                        "geometry_type": row[3],
                        "usage_hint": "",
                        "key_columns": [],
                    } for row in result}

                # Use geometry_columns as ground truth — metadata.geometry_type is often stale/NULL
                gc_result = conn.execute(text("""
                    SELECT f_table_name, type
                    FROM geometry_columns
                    WHERE f_table_schema = :schema
                    AND f_geometry_column = 'geometry'
                """), {"schema": schema})
                actual_geom_types = {row[0]: row[1] for row in gc_result}

            # Build result with column info
            tables_data = []
            for table_name in metadata.keys():
                try:
                    table_info = self.get_table_info(table_name, schema)

                    # geometry_columns is authoritative; fall back to metadata only if missing
                    geometry_type = (
                        actual_geom_types.get(table_name)
                        or metadata[table_name]["geometry_type"]
                        or "NONE"
                    )

                    tables_data.append({
                        "table": table_name,
                        "description": metadata[table_name]["description"],
                        "usage_hint": metadata[table_name]["usage_hint"],
                        "key_columns": metadata[table_name]["key_columns"],
                        "row_count": table_info["row_count"],
                        "geometry": geometry_type,
                        "columns": table_info["columns"]
                    })
                except Exception as e:
                    # Skip tables that can't be queried
                    print(f"Warning: Could not get info for table {table_name}: {e}")
                    continue

            return tables_data

        except Exception as e:
            print(f"Error fetching schema with descriptions: {e}")
            return []

    def update_table_description(self, table_name: str, description: str, schema: str = "vector") -> bool:
        """
        Update the description for a table in metadata.

        Args:
            table_name: Name of the table
            description: New description text
            schema: Database schema

        Returns:
            True if successful, False otherwise
        """
        if not self.engine:
            self.initialize()

        try:
            with self.engine.connect() as conn:
                query = text(f"""
                    UPDATE {schema}.table_metadata
                    SET description = :desc, updated_at = CURRENT_TIMESTAMP
                    WHERE table_name = :table
                """)
                conn.execute(query, {"desc": description, "table": table_name})
                conn.commit()
            return True
        except Exception as e:
            print(f"Error updating description: {e}")
            return False

    def create_temp_layer(self, geometry_json, session_id: str, schema: str = "temp") -> Optional[str]:
        """
        Create a temporary PostGIS layer from GeoJSON geometry/geometries.

        Supports both single geometry (dict) and multiple geometries (list of dicts) for multi-select support.

        Args:
            geometry_json: Single GeoJSON geometry dict OR list of GeoJSON geometry dicts
            session_id: Session ID for isolation (table name: temp_selected_{session_id})
            schema: Schema to create temp table in

        Returns:
            Table name if successful, None otherwise
        """
        if not self.engine:
            self.initialize()

        try:
            # Sanitize session_id to prevent SQL injection
            safe_session_id = session_id.replace('-', '_').replace(' ', '_')[:50]
            temp_table_name = f"temp_selected_{safe_session_id}"

            # Ensure schema exists
            with self.engine.connect() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
                conn.commit()

            # Drop existing temp table if it exists
            with self.engine.connect() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{temp_table_name} CASCADE"))
                conn.commit()

            # Create GeoDataFrame from geometry/geometries
            from shapely.geometry import shape

            # Handle both single geometry (dict) and multiple geometries (list)
            if isinstance(geometry_json, list):
                # Multi-select: list of geometries
                geometries = [shape(geom) for geom in geometry_json]
                ids = list(range(1, len(geometries) + 1))
                gdf = gpd.GeoDataFrame(
                    {'id': ids},
                    geometry=geometries,
                    crs='EPSG:4326'
                )
                print(f"📍 Processing {len(geometries)} selected geometries for temp layer")
            else:
                # Single select: single geometry (dict)
                geom = shape(geometry_json)
                gdf = gpd.GeoDataFrame(
                    {'id': [1]},
                    geometry=[geom],
                    crs='EPSG:4326'
                )
                print(f"📍 Processing 1 selected geometry for temp layer")

            # Write to PostGIS temp table
            gdf.to_postgis(
                temp_table_name,
                self.engine,
                schema=schema,
                if_exists='replace',
                index=False
            )

            # Create spatial index on temp table
            with self.engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{temp_table_name}_geom
                    ON {schema}.{temp_table_name} USING GIST(geometry)
                """))
                conn.commit()
            
            # Add geom_25833 column for fast distance queries (matches main tables)
            with self.engine.connect() as conn:
                conn.execute(text(f"""
                    ALTER TABLE {schema}.{temp_table_name} 
                    ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
                """))
                conn.execute(text(f"""
                    UPDATE {schema}.{temp_table_name} 
                    SET geom_25833 = ST_Transform(geometry, 25833)
                """))
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{temp_table_name}_geom_25833
                    ON {schema}.{temp_table_name} USING GIST(geom_25833)
                """))
                conn.commit()

            feature_count = len(geometries) if isinstance(geometry_json, list) else 1
            print(f"✅ Created temporary layer: {schema}.{temp_table_name} ({feature_count} features, with geom_25833)")
            return temp_table_name

        except Exception as e:
            print(f"❌ Error creating temp layer: {e}")
            import traceback
            traceback.print_exc()
            return None

    def drop_temp_layer(self, session_id: str, schema: str = "temp") -> bool:
        """
        Drop a temporary PostGIS layer.

        Args:
            session_id: Session ID matching the temp layer name
            schema: Schema of temp table

        Returns:
            True if successful, False otherwise
        """
        if not self.engine:
            self.initialize()

        try:
            # Sanitize session_id to prevent SQL injection
            safe_session_id = session_id.replace('-', '_').replace(' ', '_')[:50]
            temp_table_name = f"temp_selected_{safe_session_id}"

            with self.engine.connect() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{temp_table_name} CASCADE"))
                conn.commit()

            print(f"✅ Dropped temporary layer: {schema}.{temp_table_name}")
            return True

        except Exception as e:
            print(f"❌ Error dropping temp layer: {e}")
            return False

    # ======================= VALHALLA-BASED ROUTING HELPERS =======================

    def find_nearest_by_road_distance(
        self, 
        origin_lon: float, 
        origin_lat: float, 
        target_table: str,
        max_candidates: int = 15,
        max_radius_m: float = 5000.0,
        where_clause: str = None
    ) -> Optional[dict]:
        """
        Find the nearest feature from a target table using ROAD NETWORK distance.
        
        Uses Valhalla routing engine for accurate road distance computation.
        Pre-filters candidates by straight-line distance, then computes actual
        road distance via Valhalla for each candidate.
        
        Args:
            origin_lon: Longitude of origin point (e.g., selected building)
            origin_lat: Latitude of origin point
            target_table: Table to search (e.g., 'vector.osm_supermarkets')
            max_candidates: Max candidates to check with routing (performance limit)
            max_radius_m: Pre-filter radius in meters (straight-line)
            where_clause: Optional SQL WHERE filter (e.g., "brand ILIKE '%Netto%'")
            
        Returns:
            Dict with nearest feature, road distance, and route geometry
        """
        if not self.engine:
            self.initialize()
            
        try:
            import json
            
            # Step 1: Get candidate POIs within radius (straight-line pre-filter)
            # Build optional WHERE clause filter (e.g., brand ILIKE '%Netto%')
            extra_filter = f"AND {where_clause}" if where_clause else ""
            
            candidate_query = f"""
            WITH candidates AS (
                SELECT 
                    t.*,
                    ST_X(ST_Centroid(t.geometry)) as poi_lon,
                    ST_Y(ST_Centroid(t.geometry)) as poi_lat,
                    ST_Distance(
                        ST_Transform(t.geometry, 3857),
                        ST_Transform(ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326), 3857)
                    ) as straight_line_m
                FROM {target_table} t
                WHERE ST_DWithin(
                    ST_Transform(t.geometry, 3857),
                    ST_Transform(ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326), 3857),
                    :max_radius
                )
                {extra_filter}
                ORDER BY straight_line_m
                LIMIT :max_candidates
            )
            SELECT * FROM candidates
            """
            
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(candidate_query),
                    {
                        "origin_lon": origin_lon,
                        "origin_lat": origin_lat,
                        "max_radius": max_radius_m,
                        "max_candidates": max_candidates
                    }
                )
                candidates = result.fetchall()
                columns = result.keys()
                
            if not candidates:
                # Radius produced nothing — fall back to unconstrained nearest-N search
                fallback_query = f"""
                SELECT
                    t.*,
                    ST_X(ST_Centroid(t.geometry)) as poi_lon,
                    ST_Y(ST_Centroid(t.geometry)) as poi_lat,
                    ST_Distance(
                        ST_Transform(t.geometry, 3857),
                        ST_Transform(ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326), 3857)
                    ) as straight_line_m
                FROM {target_table} t
                {('WHERE ' + where_clause) if where_clause else ''}
                ORDER BY straight_line_m
                LIMIT :max_candidates
                """
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text(fallback_query),
                        {"origin_lon": origin_lon, "origin_lat": origin_lat,
                         "max_candidates": max_candidates}
                    )
                    candidates = result.fetchall()
                    columns = result.keys()

                if not candidates:
                    return {"success": False, "error": f"No features found in table {target_table}"}

                print(f"📍 Radius fallback: found {len(candidates)} candidate(s) (no radius limit)")
            else:
                print(f"📍 Found {len(candidates)} candidate(s) within {max_radius_m}m")
            
            # Step 2: Use Valhalla to compute road distance to each candidate
            from app.utils.valhalla_routing import valhalla_service
            
            results_with_road_distance = []
            
            for candidate in candidates:
                candidate_dict = dict(zip(columns, candidate))
                poi_lon = candidate_dict['poi_lon']
                poi_lat = candidate_dict['poi_lat']
                straight_line_m = candidate_dict['straight_line_m']
                
                try:
                    # Compute route via Valhalla
                    route_result = valhalla_service.get_route(
                        origin_lat=origin_lat,
                        origin_lon=origin_lon,
                        dest_lat=poi_lat,
                        dest_lon=poi_lon,
                        costing="pedestrian",
                        include_maneuvers=False
                    )
                    
                    if route_result.success:
                        results_with_road_distance.append({
                            "feature": candidate_dict,
                            "road_distance_m": route_result.distance_m,
                            "total_distance_m": route_result.distance_m,
                            "straight_line_m": straight_line_m,
                            "route_geometry": route_result.geometry,
                            "duration_minutes": route_result.duration_minutes
                        })
                    else:
                        print(f"   ⚠️ No route to candidate (straight-line: {straight_line_m:.0f}m): {route_result.error}")
                except Exception as e:
                    print(f"   ⚠️ Routing error for candidate: {e}")
            
            if not results_with_road_distance:
                return {"success": False, "error": "No routable path to any candidate"}
            
            # Step 3: Sort by road distance and return the nearest
            results_with_road_distance.sort(key=lambda x: x['total_distance_m'])
            nearest = results_with_road_distance[0]
            
            # Clean up feature dict (remove internal columns)
            feature = nearest['feature']
            for key in ['poi_lon', 'poi_lat', 'straight_line_m']:
                feature.pop(key, None)
            
            # Convert geometry to GeoJSON if it's WKB (bytes or hex string)
            if 'geometry' in feature and feature['geometry']:
                try:
                    from shapely import wkb
                    from shapely.geometry import mapping
                    geom_value = feature['geometry']
                    if isinstance(geom_value, bytes):
                        geom = wkb.loads(geom_value)
                        feature['geometry'] = mapping(geom)
                    elif isinstance(geom_value, str) and geom_value.startswith('01'):
                        geom = wkb.loads(bytes.fromhex(geom_value))
                        feature['geometry'] = mapping(geom)
                except Exception as e:
                    print(f"⚠️ Could not convert geometry: {e}")
                    feature.pop('geometry', None)
            
            print(f"✅ Nearest by road: {nearest['road_distance_m']:.0f}m "
                  f"({nearest.get('duration_minutes', 0):.1f} min walk, "
                  f"straight-line was {nearest['straight_line_m']:.0f}m)")
            
            return {
                "success": True,
                "feature": feature,
                "road_distance_m": nearest['road_distance_m'],
                "total_distance_m": nearest['total_distance_m'],
                "straight_line_m": nearest['straight_line_m'],
                "route_geometry": nearest['route_geometry'],
                "duration_minutes": nearest.get('duration_minutes', 0),
                "candidates_checked": len(candidates),
                "routable_candidates": len(results_with_road_distance),
                "routing_engine": "valhalla"
            }
            
        except Exception as e:
            print(f"❌ Error finding nearest by road: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}


# Global instance
db_manager = DatabaseManager()
