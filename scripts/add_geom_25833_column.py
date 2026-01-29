"""
Script to add geom_25833 column to all vector tables for consistent schema.
EPSG:25833 is UTM zone 33N where 1 unit = 1 meter, enabling fast distance queries.
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Database configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

print(f"Connecting to database: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")

engine = create_engine(DATABASE_URL)


def add_geom_25833_to_all_tables():
    """Add geom_25833 column to all tables in vector schema that are missing it."""
    
    with engine.connect() as conn:
        # First, find all tables in vector schema with geometry but without geom_25833
        query = text("""
            SELECT DISTINCT gc.f_table_name as table_name
            FROM geometry_columns gc
            WHERE gc.f_table_schema = 'vector'
            AND gc.f_geometry_column = 'geometry'
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns ic
                WHERE ic.table_schema = 'vector'
                AND ic.table_name = gc.f_table_name
                AND ic.column_name = 'geom_25833'
            )
            ORDER BY table_name
        """)
        
        result = conn.execute(query)
        tables_without_geom25833 = [row[0] for row in result]
        
        if not tables_without_geom25833:
            print("✅ All tables already have geom_25833 column!")
            return
        
        print(f"Found {len(tables_without_geom25833)} tables without geom_25833:")
        for table in tables_without_geom25833:
            print(f"  - {table}")
        
        print("\n" + "=" * 60)
        
        # Process each table
        for table_name in tables_without_geom25833:
            print(f"\n📍 Processing: vector.{table_name}")
            
            try:
                # Add the column
                conn.execute(text(f"""
                    ALTER TABLE vector.{table_name} 
                    ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)
                """))
                print(f"   ✓ Added geom_25833 column")
                
                # Populate it from geometry column
                conn.execute(text(f"""
                    UPDATE vector.{table_name} 
                    SET geom_25833 = ST_Transform(geometry, 25833) 
                    WHERE geom_25833 IS NULL
                """))
                print(f"   ✓ Populated geom_25833 from geometry")
                
                # Create spatial index
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_25833 
                    ON vector.{table_name} USING GIST (geom_25833)
                """))
                print(f"   ✓ Created spatial index")
                
                conn.commit()
                print(f"   ✅ Completed: {table_name}")
                
            except Exception as e:
                print(f"   ❌ Error processing {table_name}: {e}")
                conn.rollback()
                continue
        
        print("\n" + "=" * 60)
        print("✅ Schema update complete!")
        
        # Verify
        verify_query = text("""
            SELECT 
                gc.f_table_name as table_name,
                CASE WHEN ic.column_name IS NOT NULL THEN '✓' ELSE '✗' END as has_geom_25833
            FROM geometry_columns gc
            LEFT JOIN information_schema.columns ic 
                ON ic.table_schema = 'vector' 
                AND ic.table_name = gc.f_table_name 
                AND ic.column_name = 'geom_25833'
            WHERE gc.f_table_schema = 'vector'
            AND gc.f_geometry_column = 'geometry'
            ORDER BY table_name
        """)
        
        result = conn.execute(verify_query)
        print("\nVerification - All tables in vector schema:")
        for row in result:
            print(f"  {row[1]} {row[0]}")


if __name__ == "__main__":
    add_geom_25833_to_all_tables()
