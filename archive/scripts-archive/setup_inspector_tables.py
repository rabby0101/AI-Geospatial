#!/usr/bin/env python3
"""
Setup additional metadata tables for the Database Inspector:
  - metadata.data_change_log  (audit trail)
  - metadata.custom_datasets  (user-uploaded datasets registry)
"""

import sys
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
load_dotenv(str(project_root / '.env'))


def setup_inspector_tables():
    """Create metadata.data_change_log and metadata.custom_datasets tables."""

    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')

    conn_str = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'

    print("=" * 70)
    print("SETUP: Database Inspector Tables")
    print("=" * 70)
    print(f"  Host: {db_host}:{db_port}  DB: {db_name}\n")

    try:
        engine = create_engine(conn_str)

        with engine.connect() as conn:
            # Ensure metadata schema exists
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS metadata"))
            conn.commit()
            print("✅ metadata schema ready")

            # ----- data_change_log -----
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS metadata.data_change_log (
                    id          SERIAL PRIMARY KEY,
                    table_name  VARCHAR(255),
                    action      VARCHAR(50) NOT NULL,
                    details     JSONB DEFAULT '{}',
                    performed_by VARCHAR(255) DEFAULT 'system',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_changelog_table
                ON metadata.data_change_log(table_name)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_changelog_action
                ON metadata.data_change_log(action)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_changelog_created
                ON metadata.data_change_log(created_at DESC)
            """))
            conn.commit()
            print("✅ metadata.data_change_log created")

            # ----- custom_datasets -----
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS metadata.custom_datasets (
                    id              SERIAL PRIMARY KEY,
                    table_name      VARCHAR(255) UNIQUE NOT NULL,
                    original_filename VARCHAR(500),
                    file_format     VARCHAR(50),
                    row_count       INT DEFAULT 0,
                    column_count    INT DEFAULT 0,
                    has_geometry    BOOLEAN DEFAULT FALSE,
                    uploaded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uploaded_by     VARCHAR(255) DEFAULT 'api_user'
                )
            """))
            conn.commit()
            print("✅ metadata.custom_datasets created")

            # Verify
            result = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'metadata'
                ORDER BY table_name
            """))
            tables = [r[0] for r in result]
            print(f"\n  Tables in 'metadata' schema: {tables}")

        print("\n" + "=" * 70)
        print("✅ SUCCESS – Inspector tables ready")
        print("=" * 70 + "\n")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = setup_inspector_tables()
    sys.exit(0 if success else 1)
