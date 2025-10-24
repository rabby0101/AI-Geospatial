"""
Dynamic Schema Discovery for PostGIS Database

Automatically discovers available tables, columns, and metadata from the database.
Enables the system to work with new tables without code changes.
"""

from typing import Dict, List, Optional, Any
from app.utils.database import db_manager
from sqlalchemy import text, inspect
import json
from pathlib import Path


class SchemaDiscovery:
    """Discover and cache database schema information"""

    # Cache file path
    CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "metadata" / "schema_cache.json"

    # Description file path
    DESCRIPTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "metadata" / "table_descriptions.json"

    def __init__(self):
        """Initialize schema discovery"""
        self.schema = "vector"
        self._tables_cache: Optional[Dict[str, Any]] = None
        self._descriptions_cache: Optional[Dict[str, str]] = None

    def get_all_tables(self) -> Dict[str, Any]:
        """
        Get all tables from the vector schema with metadata.

        Returns:
            Dictionary mapping table names to table info (columns, geometry type, row count)
        """
        if self._tables_cache:
            return self._tables_cache

        # Try to load from cache first
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, 'r') as f:
                    self._tables_cache = json.load(f)
                    return self._tables_cache
            except Exception as e:
                print(f"Warning: Could not load schema cache: {e}")

        # Discover from database
        tables = {}
        try:
            available_tables = db_manager.get_available_tables(self.schema)

            for table_name in available_tables:
                try:
                    info = db_manager.get_table_info(table_name, self.schema)
                    tables[table_name] = {
                        "row_count": info["row_count"],
                        "geometry_type": info["geometry_type"],
                        "columns": [
                            {"name": col["name"], "type": col["type"]}
                            for col in info["columns"]
                        ]
                    }
                except Exception as e:
                    print(f"Warning: Could not get info for table {table_name}: {e}")
                    continue
        except Exception as e:
            print(f"Warning: Could not discover tables from database: {e}")
            # Return empty dict - will use descriptions only
            tables = {}

        # Cache the results
        self._tables_cache = tables
        self._save_cache(tables)

        return tables

    def get_table_description(self, table_name: str) -> str:
        """
        Get human-readable description of a table.
        Falls back to generating one from table name if not found.

        Args:
            table_name: Name of the table

        Returns:
            Description string
        """
        descriptions = self.get_all_descriptions()

        if table_name in descriptions:
            return descriptions[table_name]

        # Auto-generate description from table name
        # osm_hospitals → Hospitals
        # berlin_districts → Berlin Districts
        # osm_restaurants → Restaurants

        clean_name = table_name.replace("osm_", "").replace("_", " ").title()
        return clean_name

    def get_all_descriptions(self) -> Dict[str, str]:
        """
        Get descriptions for all tables.
        Loads from description file if available.

        Returns:
            Dictionary mapping table names to descriptions
        """
        if self._descriptions_cache:
            return self._descriptions_cache

        descriptions = {}

        # Try to load from file
        if self.DESCRIPTIONS_FILE.exists():
            try:
                with open(self.DESCRIPTIONS_FILE, 'r') as f:
                    descriptions = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load table descriptions: {e}")

        self._descriptions_cache = descriptions
        return descriptions

    def get_schema_for_prompt(self) -> str:
        """
        Generate schema information formatted for LLM prompts.

        Returns:
            Formatted string describing all available tables and columns
        """
        tables = self.get_all_tables()
        descriptions = self.get_all_descriptions()

        schema_info = f"**Available Tables (schema: {self.schema}) - {len(tables)} Total Datasets:**\n\n"

        # Group tables by category (optional, based on name patterns)
        osm_tables = {k: v for k, v in tables.items() if k.startswith("osm_")}
        other_tables = {k: v for k, v in tables.items() if not k.startswith("osm_")}

        # Helper function to format column names with quoting for special characters
        def format_columns_for_sql(cols):
            """Format column names, showing quotes for columns with special characters"""
            formatted = []
            for col in cols:
                col_name = col.get("name", "?")
                # Columns with special characters (colons, etc.) need quoting in SQL
                if ":" in col_name or "-" in col_name or " " in col_name:
                    formatted.append(f'"{col_name}"')
                else:
                    formatted.append(col_name)
            return formatted

        # Add OSM tables
        if osm_tables:
            schema_info += "**OpenStreetMap Datasets:**\n"
            for table_name, info in sorted(osm_tables.items()):
                description = descriptions.get(table_name, self.get_table_description(table_name))
                geom_type = info.get("geometry_type", "Unknown")
                row_count = info.get("row_count", 0)

                cols = info.get("columns", [])
                formatted_cols = format_columns_for_sql(cols)

                # Show only key columns to keep prompt concise, plus an indicator if more exist
                key_cols = formatted_cols[:5]  # First 5 columns
                col_display = ", ".join(key_cols)
                if len(formatted_cols) > 5:
                    col_display += f", ... (+{len(formatted_cols)-5} more)"

                schema_info += f"- {table_name} ({geom_type}, {row_count:,} rows): {description}\n"
                if col_display:
                    schema_info += f"  Sample columns: {col_display}\n"

        # Add other tables
        if other_tables:
            schema_info += "\n**Other Tables:**\n"
            for table_name, info in sorted(other_tables.items()):
                description = descriptions.get(table_name, self.get_table_description(table_name))
                geom_type = info.get("geometry_type", "Unknown")
                row_count = info.get("row_count", 0)

                cols = info.get("columns", [])
                formatted_cols = format_columns_for_sql(cols)

                # Show only key columns to keep prompt concise
                key_cols = formatted_cols[:5]  # First 5 columns
                col_display = ", ".join(key_cols)
                if len(formatted_cols) > 5:
                    col_display += f", ... (+{len(formatted_cols)-5} more)"

                schema_info += f"- {table_name} ({geom_type}, {row_count:,} rows): {description}\n"
                if col_display:
                    schema_info += f"  Sample columns: {col_display}\n"

        # Add important guidance about column names with special characters
        schema_info += f"\n**IMPORTANT - Column Name Quoting:**\n"
        schema_info += f"- Column names with colons (addr:street, addr:city) must be quoted in SQL: SELECT \"addr:street\", \"addr:city\" FROM table\n"
        schema_info += f"- Use double quotes for any column names with special characters: colons (:), hyphens (-), spaces\n"
        schema_info += f"- Safe unquoted columns: osm_id, name, geometry, opening_hours, operator, etc.\n"
        schema_info += f"- Example: SELECT osm_id, name, \"addr:street\", \"addr:postcode\" FROM vector.osm_banks\n\n"

        schema_info += f"**Common Columns:** osm_id, name, geometry (EPSG:4326)\n"
        schema_info += f"**Data Coverage: BERLIN, GERMANY ONLY** (bbox: 13.08-13.76°E, 52.33-52.67°N)\n"

        return schema_info

    def get_geometry_column(self, table_name: str) -> str:
        """
        Get the geometry column name for a table.
        Most tables use 'geometry', but this checks to be sure.

        Args:
            table_name: Name of the table

        Returns:
            Geometry column name
        """
        tables = self.get_all_tables()

        if table_name not in tables:
            return "geometry"  # Default fallback

        # Look for geometry columns
        for col in tables[table_name].get("columns", []):
            col_name = col.get("name", "").lower()
            col_type = col.get("type", "").lower()

            if "geometry" in col_type or "geom" in col_name:
                return col.get("name", "geometry")

        # If no explicit geometry column found, return 'geometry'
        return "geometry"

    def get_non_geometry_columns(self, table_name: str) -> List[str]:
        """
        Get all non-geometry columns for a table.

        Args:
            table_name: Name of the table

        Returns:
            List of column names (excluding geometry)
        """
        tables = self.get_all_tables()

        if table_name not in tables:
            return []

        geom_col = self.get_geometry_column(table_name)

        columns = [
            col.get("name") for col in tables[table_name].get("columns", [])
            if col.get("name") != geom_col
        ]

        return columns

    def validate_table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table

        Returns:
            True if table exists, False otherwise
        """
        tables = self.get_all_tables()
        return table_name in tables

    def refresh_cache(self) -> None:
        """
        Force refresh of the schema cache by querying the database.
        Useful when new tables are added dynamically.
        """
        self._tables_cache = None
        self._descriptions_cache = None
        self.get_all_tables()
        self.get_all_descriptions()

    def _save_cache(self, tables: Dict[str, Any]) -> None:
        """
        Save schema cache to file.

        Args:
            tables: Tables dictionary to cache
        """
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(tables, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save schema cache: {e}")

    def get_suggested_tables_for_keyword(self, keyword: str) -> List[str]:
        """
        Get suggested tables for a given keyword.
        Useful for helping users find relevant datasets.

        Args:
            keyword: Search keyword (e.g., "hospital", "restaurant")

        Returns:
            List of suggested table names
        """
        tables = self.get_all_tables()
        keyword_lower = keyword.lower()

        suggestions = [
            table_name for table_name in tables.keys()
            if keyword_lower in table_name.lower()
        ]

        return suggestions


# Global instance
schema_discovery = SchemaDiscovery()
