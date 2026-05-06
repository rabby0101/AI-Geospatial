#!/usr/bin/env python3
"""
Setup metadata tables for user-curated schema documentation
"""

import sys
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
project_root = Path(__file__).parent.parent
env_path = project_root / '.env'
load_dotenv(str(env_path))


def setup_metadata_tables():
    """Create metadata schema and tables"""

    print("=" * 80)
    print("SETTING UP METADATA TABLES FOR SCHEMA DOCUMENTATION")
    print("=" * 80 + "\n")

    # Database connection
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')

    connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'

    print(f"Database Connection:")
    print(f"  Host: {db_host}:{db_port}")
    print(f"  Database: {db_name}")
    print(f"  User: {db_user}\n")

    try:
        print("Creating engine...", end="", flush=True)
        engine = create_engine(connection_string)
        print(" ✅\n")

        with engine.connect() as conn:
            # Create metadata schema
            print("Creating 'metadata' schema...", end="", flush=True)
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS metadata"))
            conn.commit()
            print(" ✅")

            # Create table_descriptions table
            print("Creating 'table_descriptions' table...", end="", flush=True)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS metadata.table_descriptions (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(255) UNIQUE NOT NULL,
                    description TEXT,
                    category VARCHAR(100),
                    source VARCHAR(255),
                    row_count INT,
                    geometry_type VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by VARCHAR(255)
                )
            """))
            conn.commit()
            print(" ✅")

            # Create column_descriptions table
            print("Creating 'column_descriptions' table...", end="", flush=True)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS metadata.column_descriptions (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    data_type VARCHAR(100),
                    example_value VARCHAR(255),
                    is_german BOOLEAN DEFAULT FALSE,
                    english_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by VARCHAR(255),
                    UNIQUE(table_name, column_name),
                    FOREIGN KEY (table_name) REFERENCES metadata.table_descriptions(table_name) ON DELETE CASCADE
                )
            """))
            conn.commit()
            print(" ✅")

            # Create indexes
            print("Creating indexes...", end="", flush=True)
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_col_desc_table
                ON metadata.column_descriptions(table_name)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_col_desc_column
                ON metadata.column_descriptions(column_name)
            """))
            conn.commit()
            print(" ✅\n")

            # Verify tables were created
            print("Verifying tables...")
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'metadata'
            """))
            tables = [row[0] for row in result]
            print(f"  Tables in 'metadata' schema: {tables}\n")

        print("=" * 80)
        print("✅ SUCCESS: Metadata tables created")
        print("=" * 80 + "\n")

        print("Next steps:")
        print("1. Populate initial table descriptions (optional)")
        print("2. Create API endpoints in app/routes/database.py")
        print("3. Create frontend Database Inspector page")
        print("4. Update prompt generation to use metadata\n")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.exception("Failed to setup metadata tables")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    try:
        success = setup_metadata_tables()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
