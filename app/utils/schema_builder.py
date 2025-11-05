"""
Dynamic schema builder for LLM prompts
Pulls real-time table and column information from database with user-curated metadata
"""

import logging
from sqlalchemy import create_engine, inspect, text
import os
from dotenv import load_dotenv
# Import GeoAlchemy2 geometry type so SQLAlchemy recognizes PostGIS columns
try:
    from geoalchemy2 import Geometry
except ImportError:
    pass  # GeoAlchemy2 optional, warning will be suppressed anyway

logger = logging.getLogger(__name__)
load_dotenv()


class SchemaBuilder:
    """Build dynamic schema strings from database"""

    def __init__(self):
        self.engine = self._get_engine()

    def _get_engine(self):
        """Get database engine"""
        db_user = os.getenv('POSTGRES_USER', 'geoassist')
        db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = os.getenv('POSTGRES_PORT', '5433')
        db_name = os.getenv('POSTGRES_DB', 'geoassist')

        connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
        return create_engine(connection_string)

    def get_all_tables(self, schema: str = 'vector') -> list:
        """Get list of all tables in schema"""
        try:
            inspector = inspect(self.engine)
            return sorted(inspector.get_table_names(schema=schema))
        except Exception as e:
            logger.error(f"Error getting table list: {e}")
            return []

    def get_table_columns(self, table_name: str, schema: str = 'vector') -> list:
        """Get list of column names for a table"""
        try:
            import warnings
            # Suppress SQLAlchemy warnings about unrecognized geometry type
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=Warning)
                inspector = inspect(self.engine)
                columns = inspector.get_columns(table_name, schema=schema)
            return [col['name'] for col in columns]
        except Exception as e:
            logger.error(f"Error getting columns for {table_name}: {e}")
            return []

    def get_geometry_type(self, table_name: str, schema: str = 'vector') -> str:
        """Get geometry type for a table"""
        try:
            import warnings
            # Suppress SQLAlchemy warnings about unrecognized geometry type
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=Warning)
                inspector = inspect(self.engine)
                columns = inspector.get_columns(table_name, schema=schema)

            # Find geometry column
            for col in columns:
                if 'geometry' in str(col['type']).lower():
                    # Query actual geometry type
                    with self.engine.connect() as conn:
                        result = conn.execute(
                            text(f"""
                                SELECT ST_GeometryType(ST_AsText(geometry))
                                FROM {schema}.{table_name}
                                WHERE geometry IS NOT NULL
                                LIMIT 1
                            """)
                        )
                        geom_type = result.scalar()
                        return geom_type if geom_type else "UNKNOWN"
            return None
        except Exception as e:
            logger.warning(f"Error getting geometry type for {table_name}: {e}")
            return None

    def get_table_metadata(self, table_name: str) -> dict:
        """Get table description from metadata table"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT description, category, source, row_count
                        FROM metadata.table_descriptions
                        WHERE table_name = :table_name
                    """),
                    {'table_name': table_name}
                )
                row = result.fetchone()
                if row:
                    return {
                        'description': row[0],
                        'category': row[1],
                        'source': row[2],
                        'row_count': row[3]
                    }
        except Exception as e:
            logger.debug(f"No metadata for table {table_name}: {e}")
        return {}

    def get_column_metadata(self, table_name: str, column_name: str) -> dict:
        """Get column description from metadata table"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT description, english_name, is_german, example_value
                        FROM metadata.column_descriptions
                        WHERE table_name = :table_name AND column_name = :column_name
                    """),
                    {'table_name': table_name, 'column_name': column_name}
                )
                row = result.fetchone()
                if row:
                    return {
                        'description': row[0],
                        'english_name': row[1],
                        'is_german': row[2],
                        'example_value': row[3]
                    }
        except Exception as e:
            logger.debug(f"No metadata for {table_name}.{column_name}: {e}")
        return {}

    def build_schema_string(self, schema: str = 'vector') -> str:
        """Build comprehensive schema string for LLM prompt"""
        tables = self.get_all_tables(schema)
        schema_text = "# AVAILABLE DATABASE TABLES\n\n"
        schema_text += "Only use tables from this list. Do not invent table names.\n"
        schema_text += f"Total tables available: {len(tables)}\n\n"

        for table_name in tables:
            schema_text += f"## Table: `{table_name}`\n"

            # Table metadata
            table_meta = self.get_table_metadata(table_name)
            if table_meta.get('description'):
                schema_text += f"**Description**: {table_meta['description']}\n"
            if table_meta.get('category'):
                schema_text += f"**Category**: {table_meta['category']}\n"
            if table_meta.get('source'):
                schema_text += f"**Source**: {table_meta['source']}\n"
            if table_meta.get('row_count'):
                schema_text += f"**Records**: {table_meta['row_count']:,}\n"

            # Geometry
            geom_type = self.get_geometry_type(table_name, schema)
            if geom_type:
                schema_text += f"**Geometry**: {geom_type}\n"

            # Columns
            columns = self.get_table_columns(table_name, schema)
            if columns:
                schema_text += "**Columns**:\n"
                for col in columns:
                    col_meta = self.get_column_metadata(table_name, col)

                    col_text = f"  - `{col}`"

                    if col_meta.get('description'):
                        col_text += f": {col_meta['description']}"
                        if col_meta.get('english_name') and col_meta.get('is_german'):
                            col_text += f" (English: {col_meta['english_name']})"
                        if col_meta.get('example_value'):
                            col_text += f" (Example: {col_meta['example_value']})"
                    col_text += "\n"
                    schema_text += col_text

            schema_text += "\n"

        return schema_text

    def build_compact_schema_list(self, schema: str = 'vector') -> str:
        """Build compact list of available tables and columns (for validation)"""
        tables = self.get_all_tables(schema)
        schema_list = "AVAILABLE TABLES:\n"

        for table_name in tables:
            columns = self.get_table_columns(table_name, schema)
            schema_list += f"\n{table_name}:\n"
            schema_list += "  Columns: " + ", ".join(columns) + "\n"

        return schema_list

    def validate_table_exists(self, table_name: str, schema: str = 'vector') -> bool:
        """Check if a table exists in the database"""
        tables = self.get_all_tables(schema)
        return table_name in tables

    def validate_column_exists(self, table_name: str, column_name: str, schema: str = 'vector') -> bool:
        """Check if a column exists in a table"""
        columns = self.get_table_columns(table_name, schema)
        return column_name in columns

    def suggest_similar_tables(self, invalid_table: str, schema: str = 'vector') -> list:
        """Find similar table names (fuzzy matching)"""
        from difflib import get_close_matches

        tables = self.get_all_tables(schema)
        similar = get_close_matches(invalid_table, tables, n=3, cutoff=0.6)
        return similar

    def get_available_tables_for_category(self, category: str) -> list:
        """Get all tables in a specific category"""
        try:
            tables = self.get_all_tables()
            category_tables = []

            for table_name in tables:
                meta = self.get_table_metadata(table_name)
                if meta.get('category') == category:
                    category_tables.append(table_name)

            return category_tables
        except Exception as e:
            logger.error(f"Error getting tables for category {category}: {e}")
            return []


# Global schema builder instance
_schema_builder = None


def get_schema_builder() -> SchemaBuilder:
    """Get or create global schema builder instance"""
    global _schema_builder
    if _schema_builder is None:
        _schema_builder = SchemaBuilder()
    return _schema_builder


# Convenience functions
def get_database_schema_for_prompt() -> str:
    """Get full schema string for LLM prompt"""
    builder = get_schema_builder()
    return builder.build_schema_string()


def validate_table_exists(table_name: str) -> bool:
    """Validate that a table exists"""
    builder = get_schema_builder()
    return builder.validate_table_exists(table_name)


def suggest_tables(invalid_table: str) -> list:
    """Suggest similar table names"""
    builder = get_schema_builder()
    return builder.suggest_similar_tables(invalid_table)
