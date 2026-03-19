
import os
import sys
import logging
from sqlalchemy import text
import geopandas as gpd

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import db_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def import_custom_roads(geojson_path: str, table_name: str = "custom_roads", schema: str = "vector"):
    """
    Import custom roads from GeoJSON and build topology for routing.
    """
    try:
        if not os.path.exists(geojson_path):
            logger.error(f"File not found: {geojson_path}")
            return False

        logger.info(f"Reading {geojson_path}...")
        gdf = gpd.read_file(geojson_path)
        logger.info(f"Loaded {len(gdf)} features.")

        # Ensure CRS is EPSG:4326 for storage, but for accurate routing length we might need projection?
        # pgRouting usually works on the geometry provided.
        # If the input is 4326, length calculation in degrees is bad.
        # However, pgr_createTopology handles tolerance in the units of the projection.
        # Existing 'routing.ways' is likely 4326 geometry but might have len attributes.
        
        # Let's save to DB first.
        # To avoid overwriting other tables in 'vector' if name collides, we use specific name.
        
        logger.info(f"Saving to database table {schema}.{table_name}...")
        
        if not db_manager.engine:
            db_manager.initialize()
            
        gdf.to_postgis(
            table_name,
            db_manager.engine,
            schema=schema,
            if_exists='replace',
            index=False,
            dtype={'geometry': 'Geometry'} 
        )
        
        logger.info("Data saved. Building topology (this may take a while)...")
        
        with db_manager.engine.connect() as conn:
            # 1. Add source/target columns required by pgRouting
            conn.execute(text(f"ALTER TABLE {schema}.{table_name} ADD COLUMN IF NOT EXISTS source integer;"))
            conn.execute(text(f"ALTER TABLE {schema}.{table_name} ADD COLUMN IF NOT EXISTS target integer;"))
            conn.execute(text(f"ALTER TABLE {schema}.{table_name} ADD COLUMN IF NOT EXISTS cost double precision;"))
            conn.execute(text(f"ALTER TABLE {schema}.{table_name} ADD COLUMN IF NOT EXISTS reverse_cost double precision;"))
            
            # 2. Add 'id' column if not exists (pgr needs unique id, usually 'id')
            # GeoPandas might have saved without 'id' or with 'id' from file.
            # Let's check columns or just ensure we have a primary key 'id'
            # If 'id' is missing, add serial. 
            # If 'osm_id' exists but not 'id', create 'id'.
            try:
                # Add serial PK 'id' if not present. 
                # Be careful if 'id' already exists but isn't integer/unique.
                # Simplest is to drop 'id' if exists and recreate to be safe? 
                # Or rename existing 'id' to 'original_id'.
                # Let's try adding it if missing.
                conn.execute(text(f"ALTER TABLE {schema}.{table_name} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"))
            except Exception as e:
                logger.warning(f"Could not add serial ID (maybe exists?): {e}")

            conn.commit()
            
            # 3. Create Topology
            # pgr_createTopology('<table>', tolerance, 'the_geom', 'id', 'source', 'target')
            # geometry column name from to_postgis is usually 'geometry'
            
            logger.info("Running pgr_createTopology...")
            # 0.00001 degrees tolerance approx 1 meter
            conn.execute(text(f"SELECT pgr_createTopology('{schema}.{table_name}', 0.00001, 'geometry', 'id');"))
            conn.commit()
            
            # 4. Calculate Link Costs (Length)
            logger.info("Calculating costs (length in meters)...")
            # Cost based on length (ST_Length of geography gives meters)
            conn.execute(text(f"""
                UPDATE {schema}.{table_name} 
                SET cost = ST_Length(geometry::geography),
                    reverse_cost = ST_Length(geometry::geography);
            """))
            conn.commit()
            
            # 5. Analyze graph to ensure connectivity (optional, useful for logging)
            result = conn.execute(text(f"SELECT count(*) FROM {schema}.{table_name}_vertices_pgr;"))
            vertex_count = result.scalar()
            logger.info(f"Topology built. Vertices: {vertex_count}")

        logger.info(f"Successfully imported custom roads to {schema}.{table_name}")
        return True

    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    geojson_path = "/Users/skfazlarabby/Documents/GitHub/AI-Geospatial/Data_sets/Roads.geojson"
    import_custom_roads(geojson_path)
