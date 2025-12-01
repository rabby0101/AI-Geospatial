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
                # Get metadata from metadata.table_descriptions (UI-managed source of truth)
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
                    "geometry_type": row[3]
                } for row in result}

            # Build result with column info
            tables_data = []
            for table_name in metadata.keys():
                try:
                    table_info = self.get_table_info(table_name, schema)

                    tables_data.append({
                        "table": table_name,
                        "description": metadata[table_name]["description"],
                        "row_count": table_info["row_count"],
                        "geometry": metadata[table_name]["geometry_type"] or "NONE",
                        "columns": [col["name"] for col in table_info["columns"]]
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

            feature_count = len(geometries) if isinstance(geometry_json, list) else 1
            print(f"✅ Created temporary layer: {schema}.{temp_table_name} ({feature_count} features)")
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

    # ======================= PGROUTING HELPER METHODS =======================

    def find_nearest_vertex_to_point(self, lon: float, lat: float) -> Optional[dict]:
        """
        Find the nearest pgRouting vertex to a given point.

        Args:
            lon: Longitude (X coordinate)
            lat: Latitude (Y coordinate)

        Returns:
            Dict with vertex_id, x, y, distance_m or None if error
        """
        if not self.engine:
            self.initialize()

        try:
            query = """
            SELECT
                v.id as vertex_id,
                ST_X(v.the_geom) as x,
                ST_Y(v.the_geom) as y,
                ST_Distance(v.the_geom::geography,
                    ST_GeomFromText('POINT(:lon :lat)', 4326)::geography) as distance_m
            FROM routing.ways_vertices_pgr v
            ORDER BY v.the_geom <-> ST_GeomFromText('POINT(:lon :lat)', 4326)
            LIMIT 1
            """

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {"lon": lon, "lat": lat}
                )
                row = result.fetchone()

                if row:
                    return {
                        "vertex_id": row[0],
                        "x": float(row[1]),
                        "y": float(row[2]),
                        "distance_m": float(row[3])
                    }
            return None

        except Exception as e:
            print(f"❌ Error finding nearest vertex: {e}")
            return None

    def get_shortest_path(self, source_vertex: int, target_vertex: int) -> Optional[dict]:
        """
        Get shortest path between two pgRouting vertices using Dijkstra algorithm.

        Args:
            source_vertex: Source vertex ID
            target_vertex: Target vertex ID

        Returns:
            Dict with path geometry, distance, and route details or None if error
        """
        if not self.engine:
            self.initialize()

        try:
            query = """
            WITH dijkstra_result AS (
                SELECT * FROM pgr_dijkstra(
                    'SELECT id, source, target, cost FROM routing.ways',
                    :source_vertex,
                    :target_vertex,
                    FALSE  -- directed = FALSE for bidirectional
                )
            ),
            path_agg AS (
                SELECT
                    ARRAY_AGG(edge ORDER BY seq) as edge_ids,
                    SUM(cost) as total_distance_m
                FROM dijkstra_result
                WHERE edge > 0
            ),
            path_geom AS (
                SELECT
                    ST_LineMerge(ST_Union(w.geometry)) as geometry,
                    pa.total_distance_m
                FROM path_agg pa
                CROSS JOIN LATERAL (
                    SELECT geometry FROM routing.ways
                    WHERE id = ANY(pa.edge_ids)
                ) w
                GROUP BY pa.total_distance_m
            )
            SELECT
                ST_AsGeoJSON(geometry) as geometry_json,
                total_distance_m as distance_m
            FROM path_geom
            """

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {"source_vertex": source_vertex, "target_vertex": target_vertex}
                )
                row = result.fetchone()

                if row:
                    import json
                    return {
                        "geometry": json.loads(row[0]),
                        "distance_m": float(row[1]) if row[1] else 0,
                        "source_vertex": source_vertex,
                        "target_vertex": target_vertex
                    }
            return None

        except Exception as e:
            print(f"❌ Error getting shortest path: {e}")
            import traceback
            traceback.print_exc()
            return None

    def compute_pairwise_shortest_paths(self, geometries: list) -> dict:
        """
        Compute all pairwise shortest paths between geometries.

        Args:
            geometries: List of GeoJSON geometries (Point, Polygon, or other types)

        Returns:
            Dict with all pairwise routes, total distance, and metadata
        """
        if not self.engine:
            self.initialize()

        try:
            from shapely.geometry import shape

            # 1. Find nearest vertices for each geometry
            vertices = []
            for idx, geom_dict in enumerate(geometries):
                geom = shape(geom_dict)

                # Handle different geometry types
                if geom.geom_type == 'Point':
                    lon, lat = geom.x, geom.y
                elif geom.geom_type in ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString']:
                    # Use centroid for non-point geometries
                    centroid = geom.centroid
                    lon, lat = centroid.x, centroid.y
                else:
                    # Fallback for other geometry types
                    centroid = geom.centroid
                    lon, lat = centroid.x, centroid.y

                vertex_info = self.find_nearest_vertex_to_point(lon, lat)

                if vertex_info:
                    vertex_info["geom_index"] = idx
                    vertex_info["geometry"] = geom_dict
                    vertices.append(vertex_info)
                else:
                    print(f"⚠️  Warning: Could not find vertex for geometry {idx}")

            if len(vertices) < 2:
                return {
                    "success": False,
                    "error": "Need at least 2 features with valid road network vertices"
                }

            # 2. Compute all pairwise shortest paths
            routes = []
            total_distance = 0

            for i in range(len(vertices)):
                for j in range(i + 1, len(vertices)):
                    source_vertex = vertices[i]["vertex_id"]
                    target_vertex = vertices[j]["vertex_id"]

                    # Get shortest path
                    path = self.get_shortest_path(source_vertex, target_vertex)

                    if path:
                        routes.append({
                            "from_index": i,
                            "to_index": j,
                            "from_geometry": vertices[i]["geometry"],
                            "to_geometry": vertices[j]["geometry"],
                            "route_geometry": path["geometry"],
                            "distance_m": path["distance_m"],
                            "from_name": f"Item {i+1}",
                            "to_name": f"Item {j+1}"
                        })
                        total_distance += path["distance_m"]

            return {
                "success": True,
                "routes": routes,
                "total_distance_m": total_distance,
                "route_count": len(routes),
                "feature_count": len(vertices),
                "vertices_used": vertices
            }

        except Exception as e:
            print(f"❌ Error computing pairwise paths: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    def compute_optimal_tour(self, geometries: list, feature_names: list = None) -> dict:
        """
        Compute optimal tour connecting all geometries using Nearest Neighbor TSP heuristic.
        Returns an open tour (visits all points without returning to start).

        Args:
            geometries: List of GeoJSON geometries (Point, Polygon, or other types)
            feature_names: Optional list of feature names for waypoint labeling

        Returns:
            Dict with optimal route, waypoints, directions, and metadata
        """
        if not self.engine:
            self.initialize()

        try:
            import json
            from shapely.geometry import shape, LineString
            import numpy as np

            # 1. Find nearest vertices for each geometry
            vertices = []
            for idx, geom_dict in enumerate(geometries):
                geom = shape(geom_dict)

                # Handle different geometry types
                if geom.geom_type == 'Point':
                    lon, lat = geom.x, geom.y
                elif geom.geom_type in ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString']:
                    # Use centroid for non-point geometries
                    centroid = geom.centroid
                    lon, lat = centroid.x, centroid.y
                else:
                    # Fallback for other geometry types
                    centroid = geom.centroid
                    lon, lat = centroid.x, centroid.y

                vertex_info = self.find_nearest_vertex_to_point(lon, lat)

                if vertex_info:
                    vertex_info["geom_index"] = idx
                    vertex_info["geometry"] = geom_dict
                    vertex_info["name"] = feature_names[idx] if feature_names and idx < len(feature_names) else f"Point {idx+1}"
                    vertices.append(vertex_info)
                else:
                    print(f"⚠️  Warning: Could not find vertex for geometry {idx}")

            if len(vertices) < 2:
                return {
                    "success": False,
                    "error": "Need at least 2 features with valid road network vertices"
                }

            # 2. Build distance matrix between all vertices
            n = len(vertices)
            distance_matrix = np.zeros((n, n))

            for i in range(n):
                for j in range(i + 1, n):
                    source_vertex = vertices[i]["vertex_id"]
                    target_vertex = vertices[j]["vertex_id"]

                    # Get shortest path distance
                    path = self.get_shortest_path(source_vertex, target_vertex)

                    if path:
                        dist = path["distance_m"]
                    else:
                        # Use large distance if path not found
                        dist = 999999

                    distance_matrix[i][j] = dist
                    distance_matrix[j][i] = dist  # Symmetric matrix

            # 3. Solve TSP using Nearest Neighbor heuristic
            optimal_sequence = self._nearest_neighbor_tsp(distance_matrix)

            # 4. Compute total route with all segments (OPEN TOUR - no return to start)
            all_routes = []
            total_distance = 0
            cumulative_distance = 0

            # Use open tour (no return to start)
            for idx in range(len(optimal_sequence) - 1):
                from_idx = optimal_sequence[idx]
                to_idx = optimal_sequence[idx + 1]

                source_vertex = vertices[from_idx]["vertex_id"]
                target_vertex = vertices[to_idx]["vertex_id"]

                print(f"🛣️  Computing segment {idx+1}/{len(optimal_sequence)-1}: vertex {source_vertex} → {target_vertex}")
                path = self.get_shortest_path(source_vertex, target_vertex)

                if path:
                    all_routes.append(path["geometry"])
                    segment_distance = path["distance_m"]
                    total_distance += segment_distance
                    print(f"   ✓ Segment distance: {segment_distance:.1f}m, Geometry type: {path['geometry'].get('type')}")
                else:
                    print(f"⚠️  Warning: Could not find path from vertex {source_vertex} to {target_vertex}")

            # 5. Merge all route geometries into single LineString
            if all_routes:
                # Filter to keep only geometries (all should be dicts)
                route_geoms = [g for g in all_routes if isinstance(g, dict)]
                print(f"🗺️  Collected {len(route_geoms)} route segments for merging")

                # Merge geometries into single route
                merged_route = self._merge_geojson_linestrings(route_geoms)

                if not merged_route:
                    return {
                        "success": False,
                        "error": "Failed to merge route geometries"
                    }
            else:
                return {
                    "success": False,
                    "error": "No routes computed for optimal tour"
                }

            # 6. Extract turn-by-turn directions from route
            directions = self._extract_directions_from_route(merged_route, vertices, optimal_sequence)

            # 7. Build waypoints in optimal order (OPEN TOUR - no return to start)
            waypoints = []
            cumulative_dist = 0

            for order, idx in enumerate(optimal_sequence, 1):
                waypoints.append({
                    "order": order,
                    "name": vertices[idx]["name"],
                    "lat": float(vertices[idx]["y"]),
                    "lon": float(vertices[idx]["x"]),
                    "arrival_distance_m": cumulative_dist
                })

                # Add distance to next waypoint
                if order < len(optimal_sequence):
                    next_idx = optimal_sequence[order]
                    source_vertex = vertices[idx]["vertex_id"]
                    target_vertex = vertices[next_idx]["vertex_id"]
                    path = self.get_shortest_path(source_vertex, target_vertex)
                    if path:
                        cumulative_dist += path["distance_m"]

            # 8. Estimate time (simple heuristic: 30 km/h average urban speed)
            avg_speed_kmh = 30
            total_time_minutes = (total_distance / 1000) / avg_speed_kmh * 60

            # 9. Generate layer name
            point_names = " → ".join([vertices[idx]["name"] for idx in optimal_sequence])
            layer_name = f"Optimal Route: {point_names}"

            return {
                "success": True,
                "geometry": merged_route,
                "total_distance_m": round(total_distance, 2),
                "total_time_minutes": round(total_time_minutes, 1),
                "waypoints": waypoints,
                "directions": directions,
                "optimal_sequence": optimal_sequence,
                "layer_name": layer_name,
                "metadata": {
                    "feature_count": len(vertices),
                    "waypoint_count": len(waypoints),
                    "algorithm": "Nearest Neighbor TSP",
                    "road_network": "Berlin Detailnetz"
                }
            }

        except Exception as e:
            print(f"❌ Error computing optimal tour: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    def _nearest_neighbor_tsp(self, distance_matrix: 'np.ndarray') -> list:
        """
        Solve Traveling Salesman Problem using Nearest Neighbor heuristic.

        Args:
            distance_matrix: NxN symmetric distance matrix

        Returns:
            List of indices representing optimal sequence (0-based)
        """
        import numpy as np

        n = len(distance_matrix)
        unvisited = set(range(n))
        current = 0
        sequence = [0]
        unvisited.remove(0)

        while unvisited:
            # Find nearest unvisited node
            nearest = min(unvisited, key=lambda x: distance_matrix[current][x])
            sequence.append(nearest)
            unvisited.remove(nearest)
            current = nearest

        return sequence

    def _merge_geojson_linestrings(self, linestrings: list) -> dict:
        """
        Merge multiple GeoJSON LineStrings into a single LineString.
        Properly connects segments end-to-end to form continuous route.
        Handles both LineString and MultiLineString geometries.

        Args:
            linestrings: List of GeoJSON LineString/MultiLineString objects (in order)

        Returns:
            Merged GeoJSON LineString or None if merge fails
        """
        try:
            from shapely.geometry import LineString, MultiLineString, shape
            import json

            if not linestrings:
                print("⚠️  Error: No linestrings provided to merge")
                return None

            print(f"🔗 Merging {len(linestrings)} route segments...")

            # Convert GeoJSON objects to Shapely geometries
            geoms = []
            for idx, ls_geojson in enumerate(linestrings):
                if isinstance(ls_geojson, str):
                    ls_geojson = json.loads(ls_geojson)

                geom = shape(ls_geojson)

                # Handle MultiLineString by extracting individual lines
                if geom.geom_type == 'MultiLineString':
                    print(f"   Segment {idx}: MultiLineString with {len(geom.geoms)} parts")
                    # Add individual linestrings from the MultiLineString
                    for line in geom.geoms:
                        if line.is_valid:
                            geoms.append(line)
                elif geom.geom_type == 'LineString':
                    if geom.is_valid:
                        print(f"   Segment {idx}: LineString with {len(list(geom.coords))} coords")
                        geoms.append(geom)
                else:
                    print(f"   ⚠️  Segment {idx}: Unexpected geometry type {geom.geom_type}, skipping")

            if not geoms:
                print("⚠️  Error: No valid LineStrings to merge")
                return None

            print(f"   Total valid linestrings to merge: {len(geoms)}")

            # Extract all coordinates in sequence, removing duplicate endpoints
            all_coords = []
            for i, line in enumerate(geoms):
                coords = list(line.coords)
                if i == 0:
                    # First segment: add all coordinates
                    all_coords.extend(coords)
                    print(f"   Added first segment: {len(coords)} coords")
                else:
                    # Subsequent segments: skip first coord (duplicate of previous last coord)
                    # Check if endpoint matches
                    if coords and all_coords:
                        last_coord = tuple(all_coords[-1][:2])  # Get x,y only
                        first_coord = tuple(coords[0][:2])
                        if last_coord == first_coord:
                            all_coords.extend(coords[1:])
                            print(f"   Added segment {i}: {len(coords)-1} coords (skipped duplicate endpoint)")
                        else:
                            # Endpoints don't match exactly, add anyway but log warning
                            print(f"   ⚠️  Segment {i} endpoint mismatch: last={last_coord}, first={first_coord}")
                            all_coords.extend(coords[1:])

            print(f"   Total coordinates after merging: {len(all_coords)}")

            # Remove duplicates while preserving order
            cleaned_coords = []
            seen = set()
            for coord in all_coords:
                # Use only x,y for deduplication (ignore z if present)
                coord_tuple = tuple(coord[:2]) if len(coord) >= 2 else tuple(coord)
                if coord_tuple not in seen:
                    cleaned_coords.append(coord)
                    seen.add(coord_tuple)

            print(f"   Coordinates after deduplication: {len(cleaned_coords)}")

            if len(cleaned_coords) < 2:
                print("⚠️  Error: Insufficient coordinates to create LineString")
                return None

            # Create merged LineString
            merged_line = LineString(cleaned_coords)

            if not merged_line.is_valid:
                print(f"⚠️  Warning: Merged LineString is invalid, attempting simplification...")
                merged_line = merged_line.simplify(0.0001)

            print(f"✓ Route merged successfully: {len(list(merged_line.coords))} coordinates")

            return {
                "type": "LineString",
                "coordinates": list(merged_line.coords)
            }

        except Exception as e:
            print(f"❌ Error merging linestrings: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_directions_from_route(self, route_geojson: dict, vertices: list, optimal_sequence: list) -> list:
        """
        Extract turn-by-turn directions from route geometry.

        Args:
            route_geojson: GeoJSON LineString of the complete route
            vertices: List of vertex dictionaries with coordinates and names
            optimal_sequence: Order of visited vertices (OPEN TOUR - no return)

        Returns:
            List of DirectionStep dictionaries
        """
        try:
            from shapely.geometry import shape, Point
            import math

            directions = []
            route_geom = shape(route_geojson)

            # Start instruction
            directions.append({
                "step": 1,
                "instruction": f"Start at {vertices[optimal_sequence[0]]['name']}",
                "street": "",
                "distance_m": 0.0
            })

            # For each segment in the tour (OPEN TOUR - no return to start)
            cumulative_distance = 0
            for seg_idx, (from_idx, to_idx) in enumerate(
                zip(optimal_sequence, optimal_sequence[1:])
            ):
                from_vertex = vertices[from_idx]
                to_vertex = vertices[to_idx]

                # Get the segment path
                path = self.get_shortest_path(from_vertex["vertex_id"], to_vertex["vertex_id"])

                if path:
                    segment_distance = path["distance_m"]
                    cumulative_distance += segment_distance

                    # Create direction instruction
                    # Try to extract street name from database if available
                    street_name = self._get_street_name_for_segment(
                        from_vertex["vertex_id"], to_vertex["vertex_id"]
                    ) or "Main road"

                    # Estimate direction (N, NE, E, etc.)
                    direction = self._calculate_direction(
                        from_vertex["x"], from_vertex["y"],
                        to_vertex["x"], to_vertex["y"]
                    )

                    instruction = f"Head {direction} on {street_name} for {int(segment_distance)}m"

                    # Estimate time (30 km/h average)
                    duration_sec = (segment_distance / 30000) * 3600

                    directions.append({
                        "step": len(directions) + 1,
                        "instruction": instruction,
                        "street": street_name,
                        "distance_m": round(segment_distance, 2),
                        "duration_seconds": round(duration_sec, 0)
                    })

            # Final arrival instruction (at last point, not back at start)
            last_point = vertices[optimal_sequence[-1]]['name']
            directions.append({
                "step": len(directions) + 1,
                "instruction": f"Arrive at {last_point} (destination)",
                "street": "",
                "distance_m": 0.0
            })

            return directions

        except Exception as e:
            print(f"⚠️  Warning: Could not extract detailed directions: {e}")
            # Return minimal directions
            return [{
                "step": 1,
                "instruction": "Follow optimal route",
                "street": "Berlin Road Network",
                "distance_m": 0.0
            }]

    def _get_street_name_for_segment(self, source_vertex_id: int, target_vertex_id: int) -> str:
        """
        Get street name for a routing segment.

        Args:
            source_vertex_id: Source vertex ID
            target_vertex_id: Target vertex ID

        Returns:
            Street name or empty string if not found
        """
        try:
            query = """
            SELECT DISTINCT name
            FROM routing.ways
            WHERE (source = :source AND target = :target)
               OR (source = :target AND target = :source)
            LIMIT 1
            """

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {"source": source_vertex_id, "target": target_vertex_id}
                )
                row = result.fetchone()
                return row[0] if row else ""

        except Exception:
            return ""

    def _calculate_direction(self, lon1: float, lat1: float, lon2: float, lat2: float) -> str:
        """
        Calculate cardinal direction between two points.

        Args:
            lon1, lat1: Starting point
            lon2, lat2: Ending point

        Returns:
            Cardinal direction (N, NE, E, SE, S, SW, W, NW)
        """
        import math

        # Calculate bearing
        dlon = lon2 - lon1
        dlat = lat2 - lat1

        bearing = math.atan2(dlon, dlat) * 180 / math.pi
        if bearing < 0:
            bearing += 360

        # Convert to cardinal direction
        directions = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
        index = int((bearing + 22.5) / 45) % 8
        return directions[index]


# Global instance
db_manager = DatabaseManager()
