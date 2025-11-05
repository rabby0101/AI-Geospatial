"""
Layer Manager: Handles creation, tracking, and cleanup of temporary PostGIS layers.

Each query result is automatically saved as a temporary PostGIS table with:
- Unique layer_id and user-friendly layer_name
- Metadata tracking (creation time, source query, geometry info)
- Auto-expiration (default 1 hour)
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import geopandas as gpd
import pandas as pd
from sqlalchemy import text

from app.utils.database import db_manager

logger = logging.getLogger(__name__)


class LayerManager:
    """Manages temporary PostGIS layers for multi-step queries."""

    TEMP_SCHEMA = "temp_layers"
    DEFAULT_TTL_MINUTES = 60
    METADATA_TABLE = "layer_metadata"

    def __init__(self):
        """Initialize layer manager and ensure schema exists."""
        self._ensure_schema_exists()

    def _ensure_schema_exists(self):
        """Create temp_layers schema and metadata table if they don't exist."""
        try:
            # Use SQLAlchemy connection for DDL statements
            with db_manager.engine.begin() as conn:
                # Create schema
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.TEMP_SCHEMA}"))

                # Create metadata table
                conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {self.TEMP_SCHEMA}.{self.METADATA_TABLE} (
                    layer_id VARCHAR(50) PRIMARY KEY,
                    layer_name VARCHAR(255) NOT NULL,
                    table_name VARCHAR(255) NOT NULL UNIQUE,
                    session_id VARCHAR(255),
                    geometry_type VARCHAR(50),
                    feature_count INTEGER,
                    source_query TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    expires_at TIMESTAMP,
                    source_bounds JSONB,
                    crs VARCHAR(50) DEFAULT 'EPSG:4326'
                )
                """))

                # Create indexes
                conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_temp_layers_session
                    ON {self.TEMP_SCHEMA}.{self.METADATA_TABLE}(session_id)
                """))

                conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_temp_layers_expires
                    ON {self.TEMP_SCHEMA}.{self.METADATA_TABLE}(expires_at)
                """))

            logger.info(f"✅ Temp layers schema '{self.TEMP_SCHEMA}' initialized")

        except Exception as e:
            logger.error(f"Error initializing temp_layers schema: {e}")
            # Don't raise - schema might already exist from previous run
            pass

    def save_layer(
        self,
        gdf: gpd.GeoDataFrame,
        session_id: str,
        source_query: str,
        layer_name_hint: Optional[str] = None,
        ttl_minutes: int = DEFAULT_TTL_MINUTES
    ) -> Dict[str, Any]:
        """
        Save query results as a temporary PostGIS layer.

        Args:
            gdf: GeoDataFrame with query results
            session_id: Session ID for tracking
            source_query: Original user question/query
            layer_name_hint: Human-readable name hint (e.g., "hospitals_mitte")
            ttl_minutes: Time-to-live in minutes

        Returns:
            Dictionary with layer_id, layer_name, table_name, feature_count
        """
        try:
            if gdf is None or len(gdf) == 0:
                logger.warning("Cannot save empty GeoDataFrame as layer")
                return {
                    "success": False,
                    "error": "No features to save"
                }

            # Generate layer identifiers
            layer_id = f"layer_{str(uuid.uuid4())[:8]}"
            layer_name = layer_name_hint or f"query_result_{str(uuid.uuid4())[:8]}"

            # Sanitize layer name for SQL table
            table_name = f"{self.TEMP_SCHEMA}.layer_{layer_name[:40]}_{str(uuid.uuid4())[:8]}"

            # Get geometry info
            geometry_type = None
            if len(gdf) > 0 and not gdf.geometry.empty:
                geom_types = gdf.geometry.geom_type.unique()
                geometry_type = geom_types[0] if len(geom_types) > 0 else "Unknown"

            # Get bounds
            bounds = None
            try:
                total_bounds = gdf.total_bounds.tolist()
                bounds = {
                    "minx": float(total_bounds[0]),
                    "miny": float(total_bounds[1]),
                    "maxx": float(total_bounds[2]),
                    "maxy": float(total_bounds[3])
                }
            except Exception as e:
                logger.warning(f"Could not compute bounds: {e}")

            # Save to PostGIS
            gdf.to_postgis(
                name=table_name.split(".")[-1],
                con=db_manager.engine,
                schema=self.TEMP_SCHEMA,
                if_exists="replace",
                index=False
            )

            # Calculate expiration time
            expires_at = datetime.now() + timedelta(minutes=ttl_minutes)

            # Save metadata using SQLAlchemy for proper parameterized queries
            with db_manager.engine.begin() as conn:
                conn.execute(text(f"""
                INSERT INTO {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                (layer_id, layer_name, table_name, session_id, geometry_type, feature_count,
                 source_query, expires_at, source_bounds)
                VALUES (:layer_id, :layer_name, :table_name, :session_id, :geometry_type, :feature_count,
                        :source_query, :expires_at, :source_bounds)
                """), {
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    "table_name": table_name,
                    "session_id": session_id,
                    "geometry_type": geometry_type,
                    "feature_count": len(gdf),
                    "source_query": source_query,
                    "expires_at": expires_at,
                    "source_bounds": str(bounds) if bounds else None
                })

            logger.info(f"✅ Layer saved: {layer_name} ({len(gdf)} features, expires in {ttl_minutes}m)")

            return {
                "success": True,
                "layer_id": layer_id,
                "layer_name": layer_name,
                "table_name": table_name,
                "feature_count": len(gdf),
                "geometry_type": geometry_type,
                "bounds": bounds,
                "expires_at": expires_at.isoformat()
            }

        except Exception as e:
            logger.error(f"Error saving layer: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_layer_schema(self, layer_name: str) -> Optional[Dict[str, Any]]:
        """
        Get column schema for a temporary layer (for DeepSeek system prompt).

        Args:
            layer_name: Layer name (e.g., "hospitals_mitte")

        Returns:
            Dictionary with column info for SQL generation
        """
        try:
            # Find the full table name using SQLAlchemy
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(f"""
                SELECT table_name, geometry_type, feature_count
                FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                WHERE layer_name = :layer_name
                AND expires_at > NOW()
                """), {"layer_name": layer_name})
                rows = result.fetchall()

            if not rows:
                return None

            row = rows[0]
            table_name = row[0]
            geom_type = row[1]
            feature_count = row[2]

            # Get columns
            with db_manager.engine.connect() as conn:
                cols_result = conn.execute(text(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :tname
                ORDER BY ordinal_position
                """), {"schema": self.TEMP_SCHEMA, "tname": table_name.split(".")[-1]})
                col_rows = cols_result.fetchall()

            columns = {}
            for col_name, col_type in col_rows:
                columns[col_name] = col_type

            return {
                "layer_name": layer_name,
                "table_name": table_name,
                "geometry_type": geom_type,
                "feature_count": feature_count,
                "columns": columns
            }

        except Exception as e:
            logger.warning(f"Could not get layer schema for {layer_name}: {e}")
            return None

    def list_layers(
        self,
        session_id: Optional[str] = None,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List available temporary layers.

        Args:
            session_id: Filter by session (None = all sessions)
            include_expired: Include expired layers

        Returns:
            List of layer metadata dictionaries
        """
        try:
            where_clauses = []
            params = {}

            if session_id:
                where_clauses.append("session_id = :session_id")
                params["session_id"] = session_id

            if not include_expired:
                where_clauses.append("expires_at > NOW()")

            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            with db_manager.engine.connect() as conn:
                result = conn.execute(text(f"""
                SELECT layer_id, layer_name, table_name, geometry_type, feature_count,
                       created_at, expires_at, source_bounds
                FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                {where_sql}
                ORDER BY created_at DESC
                """), params)
                rows = result.fetchall()

            layers = []
            for row in rows:
                layers.append({
                    "layer_id": row[0],
                    "layer_name": row[1],
                    "geometry_type": row[3],
                    "feature_count": row[4],
                    "created_at": row[5].isoformat() if hasattr(row[5], 'isoformat') else str(row[5]),
                    "expires_at": row[6].isoformat() if hasattr(row[6], 'isoformat') else str(row[6])
                })

            return layers

        except Exception as e:
            logger.error(f"Error listing layers: {e}")
            return []

    def delete_layer(self, layer_name: str) -> bool:
        """Delete a temporary layer."""
        try:
            # Get table name
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(f"""
                SELECT table_name FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                WHERE layer_name = :layer_name
                """), {"layer_name": layer_name})
                rows = result.fetchall()

            if not rows:
                logger.warning(f"Layer '{layer_name}' not found")
                return False

            table_name = rows[0][0]

            # Drop table and delete metadata
            with db_manager.engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                conn.execute(text(f"""
                DELETE FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                WHERE layer_name = :layer_name
                """), {"layer_name": layer_name})

            logger.info(f"✅ Layer deleted: {layer_name}")
            return True

        except Exception as e:
            logger.error(f"Error deleting layer '{layer_name}': {e}")
            return False

    def cleanup_expired_layers(self) -> int:
        """Remove expired temporary layers. Returns count deleted."""
        try:
            # Get expired layer tables
            with db_manager.engine.connect() as conn:
                result = conn.execute(text(f"""
                SELECT table_name FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                WHERE expires_at <= NOW()
                """))
                rows = result.fetchall()

            deleted_count = 0
            for row in rows:
                table_name = row[0]
                try:
                    with db_manager.engine.begin() as conn:
                        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete table {table_name}: {e}")

            # Delete metadata
            with db_manager.engine.begin() as conn:
                conn.execute(text(f"""
                DELETE FROM {self.TEMP_SCHEMA}.{self.METADATA_TABLE}
                WHERE expires_at <= NOW()
                """))

            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} expired layers")

            return deleted_count

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0


# Singleton instance
_layer_manager = None


def get_layer_manager() -> LayerManager:
    """Get or create the LayerManager singleton."""
    global _layer_manager
    if _layer_manager is None:
        _layer_manager = LayerManager()
    return _layer_manager
