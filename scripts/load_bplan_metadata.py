#!/usr/bin/env python3
"""
Load Bauleitplanung (Building Plans) metadata into PostgreSQL as non-spatial table
This contains document references and administrative metadata without geometry
"""

import sys
import os
import logging
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_USER = os.getenv('POSTGRES_USER', 'geoassist')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
DB_HOST = os.getenv('POSTGRES_HOST', 'localhost')
DB_PORT = os.getenv('POSTGRES_PORT', '5433')
DB_NAME = os.getenv('POSTGRES_DB', 'geoassist')

# Database connection string
DB_CONNECTION_STRING = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Table configuration
SCHEMA = 'vector'
TABLE_NAME = 'bplan_official_documents'


def create_schema(engine):
    """Create the vector schema if it doesn't exist"""
    print(f"Creating schema '{SCHEMA}' if not exists...", end="", flush=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        print(" ✅")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error creating schema: {e}")
        return False


def extract_document_info(row):
    """Extract document information from complex nested structure"""
    try:
        info = {
            'id': row.get('id'),
            'identifier': None,  # Will be JSON string
            'name': None,
            'date': None,
            'document_link': None,
            'plan_type': None
        }

        # Extract identifier as JSON string
        identifier = row.get('identifier')
        if identifier:
            if isinstance(identifier, dict):
                info['identifier'] = identifier.get('value', json.dumps(identifier))
            else:
                info['identifier'] = str(identifier)

        # Extract planDocument
        if 'planDocument' in row and isinstance(row['planDocument'], dict):
            plan_doc = row['planDocument']

            if 'DocumentCitation' in plan_doc:
                doc_cite = plan_doc['DocumentCitation']
                info['name'] = doc_cite.get('name')

                # Extract date
                if 'date' in doc_cite:
                    date_obj = doc_cite['date']
                    if isinstance(date_obj, dict) and 'CI_Date' in date_obj:
                        info['date'] = date_obj['CI_Date'].get('date')

                # Extract document link
                info['document_link'] = doc_cite.get('link')

            # Extract plan type
            if 'planType' in plan_doc:
                plan_type = plan_doc['planType']
                if isinstance(plan_type, dict):
                    info['plan_type'] = plan_type.get('@codeListValue', plan_type.get('value'))

        return info
    except Exception as e:
        logger.debug(f"Error extracting document info: {e}")
        return None


def load_geojson_as_dataframe(filepath):
    """Load GeoJSON and extract document metadata"""
    print(f"Loading metadata from {filepath.name}...", end="", flush=True)
    try:
        import geopandas as gpd
        gdf = gpd.read_file(filepath)

        # Extract relevant fields
        records = []
        for idx, row in gdf.iterrows():
            doc_info = extract_document_info(row.to_dict())
            if doc_info:
                records.append(doc_info)

        df = pd.DataFrame(records)
        print(f" ✅")
        print(f"  Records: {len(df):,}")
        print(f"  Columns: {list(df.columns)}")
        return df
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error loading GeoJSON: {e}")
        return None


def upload_to_postgres(df, engine):
    """Upload DataFrame to PostgreSQL"""
    full_table_name = f"{SCHEMA}.{TABLE_NAME}"
    print(f"Uploading to {full_table_name}...", end="", flush=True)
    try:
        df.to_sql(
            TABLE_NAME,
            engine,
            schema=SCHEMA,
            if_exists='replace',
            index=False,
            chunksize=500
        )
        print(f" ✅")
        return True
    except Exception as e:
        print(f" ❌")
        logger.error(f"Error uploading to PostgreSQL: {e}")
        return False


def get_table_statistics(engine):
    """Get statistics about the loaded table"""
    full_table_name = f"{SCHEMA}.{TABLE_NAME}"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table_name}"))
            count = result.scalar()
        print(f"  Total documents: {count:,}")
        return True
    except Exception as e:
        logger.debug(f"Error getting statistics: {e}")
        return True


def main():
    """Main function"""
    print("=" * 80)
    print("LOADING BAULEITPLANUNG (BUILDING PLANS) METADATA INTO POSTGRESQL")
    print("=" * 80)
    print(f"\nDatabase: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"Schema: {SCHEMA}")
    print(f"Table: {TABLE_NAME}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    # Find input file
    project_root = Path(__file__).parent.parent
    input_file = project_root / "data/vector/wfs/berlin_bplan_officialdocumentation.geojson"

    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        print(f"\nFirst run: python scripts/download_bplan_landuse.py")
        return False

    # Connect to database
    print(f"Connecting to database...", end="", flush=True)
    try:
        engine = create_engine(DB_CONNECTION_STRING)
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
        print(f" ✅")
        print(f"  {version[:50]}...")
    except Exception as e:
        print(f" ❌")
        logger.error(f"Database connection failed: {e}")
        return False

    # Create schema
    if not create_schema(engine):
        return False

    # Load data
    df = load_geojson_as_dataframe(input_file)
    if df is None or df.empty:
        print("❌ No metadata to load")
        return False

    # Upload to database
    if not upload_to_postgres(df, engine):
        return False

    # Get statistics
    get_table_statistics(engine)

    print(f"\n{'=' * 80}")
    print("✅ BAULEITPLANUNG METADATA SUCCESSFULLY LOADED")
    print(f"{'=' * 80}")
    print(f"\nYou can now query this table in your application:")
    print(f"  - Table: {SCHEMA}.{TABLE_NAME}")
    print(f"  - API endpoint: /api/query-stats (for non-spatial queries)")
    print(f"  - Example queries:")
    print(f"    'Find building plan documents from 2023'")
    print(f"    'List all Bebauungspläne documents'")
    print()

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Loading interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
