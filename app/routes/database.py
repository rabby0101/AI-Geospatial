"""
Database schema and metadata management endpoints
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

router = APIRouter(prefix="/api/database", tags=["database"])

# Database connection helper
def get_db_engine():
    """Get database engine"""
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')

    connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    return create_engine(connection_string)


def get_table_info(table_name: str, schema: str = 'vector') -> Dict:
    """Get table structure from database"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        if not inspector.has_table(table_name, schema=schema):
            return None

        columns = inspector.get_columns(table_name, schema=schema)

        # Get row count
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table_name}"))
            row_count = result.scalar()

            # Try to get geometry type
            geometry_type = None
            geometry_col = None
            for col in columns:
                # Check for geometry column (PostGIS doesn't have standard python_type)
                col_type_str = str(col['type']).lower()
                if 'geometry' in col_type_str:
                    geometry_col = col['name']
                    break

            if geometry_col:
                try:
                    result = conn.execute(
                        text(f"SELECT ST_GeometryType(ST_AsText({geometry_col})) FROM {schema}.{table_name} WHERE {geometry_col} IS NOT NULL LIMIT 1")
                    )
                    geom_type_result = result.scalar()
                    if geom_type_result:
                        geometry_type = geom_type_result
                except Exception as e:
                    logger.debug(f"Error getting geometry type: {e}")
                    pass

        return {
            'table_name': table_name,
            'schema': schema,
            'row_count': row_count,
            'geometry_type': geometry_type,
            'columns': [
                {
                    'name': col['name'],
                    'type': str(col['type'])
                }
                for col in columns
            ]
        }
    except Exception as e:
        logger.error(f"Error getting table info: {e}")
        return None


@router.get("/tables")
async def list_tables():
    """List all tables with their metadata"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        # Get all tables from vector schema
        table_names = inspector.get_table_names(schema='vector')

        tables_data = []
        for table_name in sorted(table_names):
            table_info = get_table_info(table_name)
            if table_info:
                # Try to get metadata from metadata table
                with engine.connect() as conn:
                    try:
                        result = conn.execute(
                            text("""
                                SELECT description, category, source, geometry_type
                                FROM metadata.table_descriptions
                                WHERE table_name = :table_name
                            """),
                            {'table_name': table_name}
                        )
                        metadata = result.fetchone()
                        if metadata:
                            table_info['description'] = metadata[0]
                            table_info['category'] = metadata[1]
                            table_info['source'] = metadata[2]
                            table_info['geometry_type'] = metadata[3] or table_info['geometry_type']
                        else:
                            table_info['description'] = None
                            table_info['category'] = None
                            table_info['source'] = None
                    except:
                        table_info['description'] = None
                        table_info['category'] = None
                        table_info['source'] = None

                tables_data.append(table_info)

        return {
            'success': True,
            'tables': tables_data,
            'total': len(tables_data)
        }
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables/{table_name}")
async def get_table_details(table_name: str):
    """Get detailed information about a specific table"""
    try:
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        # Get metadata
        with engine.connect() as conn:
            # Table metadata
            result = conn.execute(
                text("""
                    SELECT id, description, category, source, geometry_type
                    FROM metadata.table_descriptions
                    WHERE table_name = :table_name
                """),
                {'table_name': table_name}
            )
            table_meta = result.fetchone()

            if table_meta:
                table_info['metadata_id'] = table_meta[0]
                table_info['description'] = table_meta[1]
                table_info['category'] = table_meta[2]
                table_info['source'] = table_meta[3]
                table_info['geometry_type'] = table_meta[4] or table_info['geometry_type']
            else:
                table_info['metadata_id'] = None
                table_info['description'] = None
                table_info['category'] = None
                table_info['source'] = None

            # Column metadata
            column_descriptions = {}
            result = conn.execute(
                text("""
                    SELECT column_name, description, data_type, example_value, english_name, is_german
                    FROM metadata.column_descriptions
                    WHERE table_name = :table_name
                    ORDER BY column_name
                """),
                {'table_name': table_name}
            )

            for col_meta in result.fetchall():
                column_descriptions[col_meta[0]] = {
                    'description': col_meta[1],
                    'data_type': col_meta[2],
                    'example_value': col_meta[3],
                    'english_name': col_meta[4],
                    'is_german': col_meta[5]
                }

            # Merge with column info
            for col in table_info['columns']:
                if col['name'] in column_descriptions:
                    col['metadata'] = column_descriptions[col['name']]
                else:
                    col['metadata'] = None

        return {
            'success': True,
            'table': table_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting table details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tables/{table_name}")
async def update_table_description(
    table_name: str,
    description: str,
    category: Optional[str] = None,
    source: Optional[str] = None,
    updated_by: Optional[str] = "api_user"
):
    """Add or update table description"""
    try:
        # Verify table exists
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if exists
            result = conn.execute(
                text("SELECT id FROM metadata.table_descriptions WHERE table_name = :table_name"),
                {'table_name': table_name}
            )
            exists = result.fetchone() is not None

            if exists:
                # Update
                conn.execute(
                    text("""
                        UPDATE metadata.table_descriptions
                        SET description = :description,
                            category = :category,
                            source = :source,
                            updated_at = CURRENT_TIMESTAMP,
                            updated_by = :updated_by,
                            geometry_type = :geometry_type,
                            row_count = :row_count
                        WHERE table_name = :table_name
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'category': category,
                        'source': source,
                        'updated_by': updated_by,
                        'geometry_type': table_info['geometry_type'],
                        'row_count': table_info['row_count']
                    }
                )
            else:
                # Insert
                conn.execute(
                    text("""
                        INSERT INTO metadata.table_descriptions
                        (table_name, description, category, source, geometry_type, row_count, updated_by)
                        VALUES (:table_name, :description, :category, :source, :geometry_type, :row_count, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'category': category,
                        'source': source,
                        'geometry_type': table_info['geometry_type'],
                        'row_count': table_info['row_count'],
                        'updated_by': updated_by
                    }
                )

            conn.commit()

        return {
            'success': True,
            'message': f"Table {table_name} description updated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating table description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/columns")
async def update_column_description(
    table_name: str,
    column_name: str,
    description: str,
    english_name: Optional[str] = None,
    example_value: Optional[str] = None,
    is_german: bool = False,
    updated_by: Optional[str] = "api_user"
):
    """Add or update column description"""
    try:
        # Verify table and column exist
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        col_names = [col['name'] for col in table_info['columns']]
        if column_name not in col_names:
            raise HTTPException(status_code=404, detail=f"Column {column_name} not found in {table_name}")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if exists
            result = conn.execute(
                text("""
                    SELECT id FROM metadata.column_descriptions
                    WHERE table_name = :table_name AND column_name = :column_name
                """),
                {'table_name': table_name, 'column_name': column_name}
            )
            exists = result.fetchone() is not None

            data_type = next((col['type'] for col in table_info['columns'] if col['name'] == column_name), None)

            if exists:
                # Update
                conn.execute(
                    text("""
                        UPDATE metadata.column_descriptions
                        SET description = :description,
                            english_name = :english_name,
                            example_value = :example_value,
                            is_german = :is_german,
                            data_type = :data_type,
                            updated_at = CURRENT_TIMESTAMP,
                            updated_by = :updated_by
                        WHERE table_name = :table_name AND column_name = :column_name
                    """),
                    {
                        'table_name': table_name,
                        'column_name': column_name,
                        'description': description,
                        'english_name': english_name,
                        'example_value': example_value,
                        'is_german': is_german,
                        'data_type': data_type,
                        'updated_by': updated_by
                    }
                )
            else:
                # Insert
                conn.execute(
                    text("""
                        INSERT INTO metadata.column_descriptions
                        (table_name, column_name, description, english_name, example_value, is_german, data_type, updated_by)
                        VALUES (:table_name, :column_name, :description, :english_name, :example_value, :is_german, :data_type, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'column_name': column_name,
                        'description': description,
                        'english_name': english_name,
                        'example_value': example_value,
                        'is_german': is_german,
                        'data_type': data_type,
                        'updated_by': updated_by
                    }
                )

            conn.commit()

        return {
            'success': True,
            'message': f"Column {table_name}.{column_name} description updated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating column description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema-for-prompt")
async def get_schema_for_prompt():
    """Get formatted schema for LLM prompt"""
    try:
        engine = get_db_engine()
        inspector = inspect(engine)

        table_names = inspector.get_table_names(schema='vector')

        schema_text = "# AVAILABLE DATABASE TABLES\n\n"

        for table_name in sorted(table_names):
            table_info = get_table_info(table_name)
            if not table_info:
                continue

            # Get metadata
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT description, category
                        FROM metadata.table_descriptions
                        WHERE table_name = :table_name
                    """),
                    {'table_name': table_name}
                )
                table_meta = result.fetchone()

            # Table header
            if table_meta and table_meta[0]:
                schema_text += f"## Table: {table_name}\n"
                schema_text += f"**Description**: {table_meta[0]}\n"
                if table_meta[1]:
                    schema_text += f"**Category**: {table_meta[1]}\n"
            else:
                schema_text += f"## Table: {table_name}\n"

            schema_text += f"**Geometry**: {table_info['geometry_type'] or 'None'}\n"
            schema_text += f"**Records**: {table_info['row_count']:,}\n"
            schema_text += "**Columns**:\n"

            # Columns with metadata
            with engine.connect() as conn:
                for col in table_info['columns']:
                    result = conn.execute(
                        text("""
                            SELECT description, english_name, is_german
                            FROM metadata.column_descriptions
                            WHERE table_name = :table_name AND column_name = :column_name
                        """),
                        {'table_name': table_name, 'column_name': col['name']}
                    )
                    col_meta = result.fetchone()

                    col_text = f"  - `{col['name']}`"
                    if col_meta and col_meta[0]:
                        col_text += f": {col_meta[0]}"
                        if col_meta[1] and col_meta[2]:
                            col_text += f" (English: {col_meta[1]})"
                    schema_text += col_text + "\n"

            schema_text += "\n"

        return {
            'success': True,
            'schema': schema_text
        }
    except Exception as e:
        logger.error(f"Error generating schema for prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/table-description")
async def update_table_description(table_name: str, description: str):
    """
    Update the description for a table in metadata.table_descriptions.

    This is the single source of truth for table descriptions displayed in the UI.

    Args:
        table_name: Name of the table to update
        description: New description text

    Returns:
        Success message with updated description
    """
    try:
        if not table_name or not description:
            raise HTTPException(status_code=400, detail="table_name and description are required")

        # Verify table exists
        table_info = get_table_info(table_name)
        if not table_info:
            raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

        engine = get_db_engine()

        with engine.connect() as conn:
            # Check if metadata record exists
            result = conn.execute(
                text("SELECT id FROM metadata.table_descriptions WHERE table_name = :table_name"),
                {'table_name': table_name}
            )
            exists = result.fetchone() is not None

            if exists:
                # Update existing record
                conn.execute(
                    text("""
                        UPDATE metadata.table_descriptions
                        SET description = :description,
                            updated_at = CURRENT_TIMESTAMP,
                            row_count = :row_count,
                            geometry_type = :geometry_type
                        WHERE table_name = :table_name
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'row_count': table_info['row_count'],
                        'geometry_type': table_info['geometry_type']
                    }
                )
            else:
                # Insert new record
                conn.execute(
                    text("""
                        INSERT INTO metadata.table_descriptions
                        (table_name, description, row_count, geometry_type, updated_by)
                        VALUES (:table_name, :description, :row_count, :geometry_type, :updated_by)
                    """),
                    {
                        'table_name': table_name,
                        'description': description,
                        'row_count': table_info['row_count'],
                        'geometry_type': table_info['geometry_type'],
                        'updated_by': 'ui_user'
                    }
                )

            conn.commit()

        return {
            'success': True,
            'table_name': table_name,
            'description': description,
            'message': f"Description updated for table: {table_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating table description: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables-with-metadata")
async def get_tables_with_metadata():
    """
    Get all tables with their descriptions from database.

    This is used by the database inspector UI to show available tables.

    Returns:
        List of tables with metadata
    """
    try:
        from app.utils.database import db_manager

        tables_data = db_manager.get_schema_with_descriptions()

        if not tables_data:
            return {
                'success': True,
                'tables': [],
                'message': 'No tables found'
            }

        return {
            'success': True,
            'tables': tables_data,
            'count': len(tables_data)
        }
    except Exception as e:
        logger.error(f"Error fetching tables with metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))
