#!/usr/bin/env python3
"""
Import ALKIS Buildings data (GeoJSON) to PostGIS
"""

import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import geopandas as gpd
from app.utils.database import DatabaseManager

def import_buildings_data():
    """Import buildings GeoJSON file to PostGIS"""
    
    geojson_file = Path("/Users/skfazlarabby/Downloads/alkis_gebaeude_gebaeude_WGS84.geojson")
    
    if not geojson_file.exists():
        print(f"❌ File not found: {geojson_file}")
        return False
    
    print(f"📂 Loading GeoJSON file: {geojson_file}")
    print(f"   File size: {geojson_file.stat().st_size / 1024 / 1024:.1f} MB")
    
    try:
        # Load the GeoJSON file
        print("🔄 Reading GeoJSON (this may take a moment for a 98MB file)...")
        gdf = gpd.read_file(geojson_file)
        
        print(f"✅ Loaded {len(gdf)} features")
        print(f"   Geometry type: {gdf.geometry.type.unique()}")
        print(f"   CRS: {gdf.crs}")
        print(f"   Columns: {list(gdf.columns)}")
        
        # Ensure CRS is EPSG:4326
        if gdf.crs != "EPSG:4326":
            print(f"⚠️  Converting CRS from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")
        
        # Save to PostGIS
        print("\n🔄 Importing to PostGIS as 'osm_berlin_buildings'...")
        db_manager = DatabaseManager()
        db_manager.save_vector_to_db(
            gdf=gdf,
            table_name="osm_berlin_buildings",
            schema="vector",
            if_exists="replace"
        )
        
        print("✅ Successfully imported to PostGIS")
        
        # Get table info
        db_manager.initialize()
        table_info = db_manager.get_table_info("osm_berlin_buildings", schema="vector")
        print(f"\n📊 Table Info:")
        print(f"   Rows: {table_info['row_count']}")
        print(f"   Geometry: {table_info['geometry_type']}")
        print(f"   Columns: {len(table_info['columns'])}")
        
        # Update metadata
        print("\n📝 Updating metadata...")
        metadata_file = Path("/Users/skfazlarabby/projects/AI Geospatial/data/metadata/table_descriptions.json")
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        metadata["osm_berlin_buildings"] = (
            "Building polygons from ALKIS cadastral data for Berlin. "
            "Contains detailed building footprints with properties like building type (gfk), "
            "function (bezgfk), height classification (bat), and cadastral reference data."
        )
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        print("✅ Metadata updated")
        
        print("\n" + "="*60)
        print("✅ IMPORT COMPLETE")
        print("="*60)
        print(f"Table: vector.osm_berlin_buildings")
        print(f"Features: {table_info['row_count']:,}")
        print(f"Geometry Type: {table_info['geometry_type']}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = import_buildings_data()
    sys.exit(0 if success else 1)
