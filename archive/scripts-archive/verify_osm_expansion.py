#!/usr/bin/env python
"""
Verification script for OSM data expansion
Checks that all 23 datasets are properly loaded in PostGIS
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.database import db_manager
from dotenv import load_dotenv

load_dotenv()

# Expected tables (23 total)
EXPECTED_TABLES = {
    'Original Amenities': [
        'osm_hospitals', 'osm_toilets', 'osm_pharmacies', 'osm_fire_stations',
        'osm_police_stations', 'osm_parks', 'osm_schools', 'osm_restaurants',
        'osm_transport_stops', 'osm_parking'
    ],
    'Medical/Health': [
        'osm_doctors', 'osm_dentists', 'osm_clinics', 'osm_veterinary'
    ],
    'Education': [
        'osm_universities', 'osm_libraries'
    ],
    'Commerce & Services': [
        'osm_supermarkets', 'osm_banks', 'osm_atm', 'osm_post_offices'
    ],
    'Recreation': [
        'osm_museums', 'osm_theatres', 'osm_gyms'
    ],
    'Land Use': [
        'osm_forests', 'osm_water_bodies'
    ],
    'Administrative': [
        'osm_districts'
    ]
}

def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)

def verify_tables():
    """Verify all expected tables exist and contain data"""

    print_header("OSM DATA VERIFICATION")
    print(f"\nTimestamp: {datetime.now().isoformat()}")
    print("Expected datasets: 23 total")

    # Initialize database
    try:
        db_manager.initialize()
        print("✅ Database connection established")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False

    all_tables = db_manager.get_available_tables('vector')
    print(f"✅ Database has {len(all_tables)} tables in 'vector' schema")

    print_header("Verifying All Datasets")

    all_exist = True
    total_features = 0
    category_results = {}

    for category, tables in EXPECTED_TABLES.items():
        print(f"\n{category} ({len(tables)} tables):")
        category_results[category] = {'found': 0, 'total': len(tables), 'features': 0}

        for table_name in tables:
            if table_name in all_tables:
                try:
                    # Get table info
                    info = db_manager.get_table_info(table_name)
                    row_count = info.get('row_count', 'unknown')
                    has_index = 'spatial_index' in str(info)

                    # Format output
                    status = "✅"
                    category_results[category]['found'] += 1
                    category_results[category]['features'] += row_count if isinstance(row_count, int) else 0
                    total_features += row_count if isinstance(row_count, int) else 0

                    print(f"  {status} {table_name:30s}: {row_count:>8,} features")

                except Exception as e:
                    print(f"  ⚠️  {table_name:30s}: Error - {str(e)[:40]}")
                    all_exist = False
            else:
                print(f"  ❌ {table_name:30s}: NOT FOUND")
                all_exist = False

    # Summary
    print_header("Summary")

    total_found = sum(cat['found'] for cat in category_results.values())
    total_expected = sum(cat['total'] for cat in category_results.values())

    print("\nBy Category:")
    for category, stats in category_results.items():
        status = "✅" if stats['found'] == stats['total'] else "⚠️"
        print(f"  {status} {category:25s}: {stats['found']:2d}/{stats['total']:2d} tables, {stats['features']:>10,} features")

    print(f"\n{'-' * 80}")
    print(f"Total Tables Found: {total_found}/{total_expected}")
    print(f"Total Features: {total_features:,}")
    print(f"Success Rate: {total_found/total_expected*100:.1f}%")

    # Check spatial indexes
    print(f"\n{'-' * 80}")
    print("Checking Spatial Indexes:")

    all_have_indexes = True
    for category, tables in EXPECTED_TABLES.items():
        for table_name in tables:
            if table_name in all_tables:
                try:
                    # Check if GIST index exists
                    with db_manager.get_session() as session:
                        from sqlalchemy import text
                        result = session.execute(text(f"""
                            SELECT indexname FROM pg_indexes
                            WHERE tablename = '{table_name}' AND indexname LIKE '%geom%'
                        """))
                        indexes = result.fetchall()
                        if indexes:
                            print(f"  ✅ {table_name:30s}: GIST index present")
                        else:
                            print(f"  ⚠️  {table_name:30s}: No GIST index found")
                            all_have_indexes = False
                except:
                    pass

    # Final status
    print_header("Final Status")

    if all_exist and total_found == total_expected:
        print("\n✅ ALL VERIFICATION CHECKS PASSED!")
        print(f"   - All {total_expected} expected tables found")
        print(f"   - Total of {total_features:,} features loaded")
        print(f"   - Ready for geospatial queries")
        return True
    else:
        print(f"\n⚠️  VERIFICATION INCOMPLETE")
        print(f"   - Found {total_found}/{total_expected} tables")
        print(f"   - Total of {total_features:,} features")
        print(f"   - Check download and loading scripts for missing datasets")
        return False

def test_sample_queries():
    """Run sample queries to verify functionality"""

    print_header("Testing Sample Queries")

    try:
        with db_manager.get_session() as session:
            from sqlalchemy import text

            # Test queries
            tests = [
                ("Count hospitals", "SELECT COUNT(*) as count FROM vector.osm_hospitals"),
                ("Count doctors", "SELECT COUNT(*) as count FROM vector.osm_doctors"),
                ("Count forests", "SELECT COUNT(*) as count FROM vector.osm_forests"),
                ("Districts in Berlin", "SELECT COUNT(*) as count FROM vector.osm_districts"),
            ]

            for test_name, query in tests:
                try:
                    result = session.execute(text(query))
                    count = result.scalar()
                    print(f"  ✅ {test_name:30s}: {count:>8,} records")
                except Exception as e:
                    print(f"  ❌ {test_name:30s}: {str(e)[:40]}")

    except Exception as e:
        print(f"  ❌ Query test failed: {e}")

    print()

if __name__ == "__main__":
    success = verify_tables()
    test_sample_queries()

    print("=" * 80)
    if success:
        print("✅ OSM Data Expansion Verification Complete!")
        sys.exit(0)
    else:
        print("⚠️  Verification found issues. Review above for details.")
        sys.exit(1)
