"""
Intelligent Schema Manager for Context-Aware Query Processing

Manages database table schemas, caching, and intelligent table matching for user queries.
Enables sending only relevant table information to LLMs, significantly reducing prompt size.
"""

import logging
import re
from typing import Dict, List, Set, Optional
from app.utils.database import db_manager

logger = logging.getLogger(__name__)


class SchemaManager:
    """
    Manages database schema caching and intelligent table matching for queries.

    On initialization, caches all available tables and their column schemas.
    Analyzes user queries to identify relevant tables and return only needed schemas.
    """

    def __init__(self):
        """Initialize schema manager and cache all table schemas."""
        self.tables_cache: Dict[str, List[str]] = {}  # {table_name: [col1, col2, ...]}
        self.tables_info: Dict[str, Dict] = {}  # Full table info

        # Note: Keyword mappings have been moved to database.table_metadata descriptions.
        # The LLM now reads table descriptions directly from the database to understand
        # which tables are available and what they contain. This is a cleaner, more
        # maintainable approach than hardcoding keywords here.

        # Initialize cache
        self._load_schema_cache()

    def _load_schema_cache(self) -> None:
        """Load and cache all table schemas from database."""
        try:
            tables = db_manager.get_available_tables(schema="vector")
            logger.info(f"🔍 Discovering {len(tables)} tables...")

            for table in tables:
                try:
                    info = db_manager.get_table_info(table, schema="vector")
                    columns = [col['name'] for col in info['columns']]
                    self.tables_cache[table] = columns
                    self.tables_info[table] = info
                    logger.debug(f"  ✓ {table}: {len(columns)} columns")
                except Exception as e:
                    logger.warning(f"  ⚠ Could not cache {table}: {e}")

            logger.info(f"✅ Schema cache loaded: {len(self.tables_cache)} tables")

        except Exception as e:
            logger.error(f"❌ Failed to load schema cache: {e}")
            self.tables_cache = {}

    def match_tables_to_query(self, query: str) -> Dict[str, List[str]]:
        """
        Intelligently match user query to relevant database tables.

        Analyzes query keywords and returns schemas for only relevant tables.
        Only returns tables that actually exist in the database.
        Falls back to all tables if no clear matches found.

        Args:
            query: User's natural language query

        Returns:
            Dictionary of {table_name: [column_list]} for EXISTING matched tables only
        """
        query_lower = query.lower()
        matched_tables: Set[str] = set()

        # Extract keywords from query (words between 3-20 chars)
        words = re.findall(r'\b[a-z]{3,20}\b', query_lower)

        # Match keywords to tables
        for word in words:
            if word in self.keyword_mappings:
                table_name = self.keyword_mappings[word]
                # Only add if table actually exists in cache
                if table_name in self.tables_cache:
                    matched_tables.add(table_name)
                else:
                    logger.warning(f"  ⚠ Keyword '{word}' maps to table '{table_name}' but table not in database")

        # Always include landmarks table for location queries (if it exists)
        if any(keyword in query_lower for keyword in ['in ', 'near ', 'within ', 'at ']):
            if 'landmarks' in self.tables_cache:
                matched_tables.add('landmarks')

        # If no matches found, return a broader set of common tables (only if they exist)
        if not matched_tables:
            logger.warning(f"⚠ No table matches for query: {query}")
            # Return common location-based tables as fallback (only existing ones)
            fallback_tables = {
                'landmarks',
                'berlin_districts',
                'osm_transport_stops',
                'osm_parks',
                'osm_hospitals',
            }
            matched_tables = {t for t in fallback_tables if t in self.tables_cache}

        # Build result dictionary with columns for each matched table
        # Double-check all returned tables actually exist
        result = {}
        for table in matched_tables:
            if table in self.tables_cache:
                result[table] = self.tables_cache[table]
            else:
                logger.warning(f"  ⚠ Matched table '{table}' not in cache (was it deleted?)")

        logger.info(f"📊 Matched {len(result)} tables for query: {query[:50]}...")
        return result

    def get_all_tables(self) -> Dict[str, List[str]]:
        """
        Get all cached table schemas.

        Returns:
            Dictionary of {table_name: [column_list]} for all tables
        """
        return self.tables_cache.copy()

    def get_full_schema_string(self) -> str:
        """
        Get all available tables and columns as a formatted string for LLM context.

        Returns:
            Formatted string with all tables and their columns
        """
        if not self.tables_cache:
            return "No tables available"

        schema_str = "**AVAILABLE TABLES (schema: vector):**\n\n"

        # Group tables by type for clarity
        amenity_tables = [t for t in sorted(self.tables_cache.keys()) if 'osm_' in t]
        admin_tables = [t for t in sorted(self.tables_cache.keys()) if t in ['berlin_districts', 'landmarks']]
        other_tables = [t for t in sorted(self.tables_cache.keys()) if t not in amenity_tables + admin_tables]

        # Amenities
        if amenity_tables:
            schema_str += "**Amenities & Points of Interest:**\n"
            for table in amenity_tables:
                cols = self.tables_cache[table]
                schema_str += f"- `{table}`: {', '.join(cols)}\n"

        # Administrative
        if admin_tables:
            schema_str += "\n**Administrative & Location Reference:**\n"
            for table in admin_tables:
                cols = self.tables_cache[table]
                schema_str += f"- `{table}`: {', '.join(cols)}\n"

        # Other
        if other_tables:
            schema_str += "\n**Other Tables (Business & Miscellaneous):**\n"
            for table in other_tables:
                cols = self.tables_cache[table]
                schema_str += f"- `{table}`: {', '.join(cols)}\n"

        return schema_str

    def get_table_schema(self, table_name: str) -> Optional[List[str]]:
        """
        Get column list for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            List of column names, or None if table not found
        """
        return self.tables_cache.get(table_name)

    def refresh_cache(self) -> None:
        """Refresh the schema cache from database."""
        logger.info("🔄 Refreshing schema cache...")
        self._load_schema_cache()

    def format_table_schema_for_prompt(self, tables: Dict[str, List[str]]) -> str:
        """
        Format table schemas for inclusion in LLM prompt.

        Args:
            tables: Dictionary of {table_name: [columns]}

        Returns:
            Formatted string for prompt
        """
        if not tables:
            return ""

        formatted = "**Available Tables (schema: vector):**\n\n"
        for table_name, columns in sorted(tables.items()):
            formatted += f"- `{table_name}`: {', '.join(columns)}\n"

        return formatted


# Global instance
_schema_manager: Optional[SchemaManager] = None


def get_schema_manager() -> SchemaManager:
    """
    Get or create the global SchemaManager instance.

    Returns:
        SchemaManager instance
    """
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SchemaManager()
    return _schema_manager
