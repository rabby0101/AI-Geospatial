#!/usr/bin/env python3
"""
Load allotment gardens GeoJSON into PostGIS
"""

import geopandas as gpd
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/Users/skfazlarabby/projects/AI Geospatial/.env')

def load_gardens_to_postgis():
    """Load allotment gardens GeoJSON into PostGIS"""
    
    # Database connection
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')
    
    connection_string = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    
    print(f"Connecting to PostGIS: {db_host}:{db_port}/{db_name}")
    
    try:
        engine = create_engine(connection_string)
        
        # Read GeoJSON
        geojson_path = '/Users/skfazlarabby/projects/AI Geospatial/data/vector/osm_allotment_gardens.geojson'
        print(f"Reading {geojson_path}...")
        
        gdf = gpd.read_file(geojson_path)
        print(f"Loaded {len(gdf)} allotment gardens")
        
        # Ensure CRS is correct
        if gdf.crs is None:
            gdf.crs = 'EPSG:4326'
        elif gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        
        print(f"CRS: {gdf.crs}")
        
        # Create table in PostGIS
        table_name = 'osm_allotment_gardens'
        schema = 'vector'
        
        print(f"Writing to {schema}.{table_name}...")
        
        # Write to PostGIS with if_exists='replace' to create new table
        gdf.to_postgis(
            name=table_name,
            con=engine,
            schema=schema,
            if_exists='replace',
            index=False
        )
        
        print(f"Successfully loaded {len(gdf)} gardens into {schema}.{table_name}")
        
        # Create spatial index using proper SQLAlchemy text() function
        with engine.connect() as conn:
            conn.execute(text(f"CREATE INDEX idx_{table_name}_geom ON {schema}.{table_name} USING GIST (geometry)"))
            conn.commit()
        
        print(f"Created spatial index on geometry")
        
        # Verify the data
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table_name}")).fetchone()
            count = result[0]
            print(f"\nVerification: {count} records in database")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = load_gardens_to_postgis()
    exit(0 if success else 1)
