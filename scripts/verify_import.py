#!/usr/bin/env python3
"""
Verify the buildings import and refresh schema cache
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.database import DatabaseManager
from app.utils.schema_manager import get_schema_manager

def verify_import():
    """Verify the buildings table import"""
    
    print("\n" + "="*60)
    print("VERIFYING BUILDINGS IMPORT")
    print("="*60)
    
    # Initialize database manager
    db_manager = DatabaseManager()
    db_manager.initialize()
    
    # Check connection
    print("\n1️⃣  Testing database connection...")
    if not db_manager.test_connection():
        print("❌ Failed to connect to database")
        return False
    
    # Get table info
    print("\n2️⃣  Checking osm_berlin_buildings table...")
    try:
        table_info = db_manager.get_table_info("osm_berlin_buildings", schema="vector")
        print(f"✅ Table found in database")
        print(f"   Rows: {table_info['row_count']:,}")
        print(f"   Geometry type: {table_info['geometry_type']}")
        print(f"   Columns: {len(table_info['columns'])}")
        print(f"   Column names: {', '.join([c['name'] for c in table_info['columns'][:5]])}...")
    except Exception as e:
        print(f"❌ Failed to get table info: {e}")
        return False
    
    # Test a simple query
    print("\n3️⃣  Testing sample query...")
    try:
        result = db_manager.execute_spatial_query(
            "SELECT uuid, gfk, bezgfk, ST_AsGeoJSON(geometry) as geometry FROM vector.osm_berlin_buildings LIMIT 3"
        )
        print(f"✅ Query successful, retrieved {len(result)} features")
        print(f"   Sample columns: {list(result.columns)}")
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return False
    
    # Refresh schema cache
    print("\n4️⃣  Refreshing schema cache...")
    try:
        schema_mgr = get_schema_manager()
        schema_mgr.refresh_cache()
        
        # Check if new table is in cache
        if "osm_berlin_buildings" in schema_mgr.get_all_tables():
            print("✅ Table added to schema cache")
            columns = schema_mgr.get_table_schema("osm_berlin_buildings")
            print(f"   Cached columns: {columns[:5]}...")
        else:
            print("⚠️  Table not in schema cache yet (may need app restart)")
    except Exception as e:
        print(f"⚠️  Warning refreshing cache: {e}")
    
    print("\n" + "="*60)
    print("✅ VERIFICATION COMPLETE")
    print("="*60)
    print("\nThe osm_berlin_buildings table is ready to use!")
    print("Try queries like:")
    print('  - "Show all buildings in Mitte"')
    print('  - "How many commercial buildings in Berlin?"')
    print('  - "Find buildings with residential use"')
    
    return True

if __name__ == "__main__":
    success = verify_import()
    sys.exit(0 if success else 1)
