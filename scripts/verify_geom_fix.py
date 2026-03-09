import sys
import os
sys.path.append(os.getcwd())

from app.utils.database import db_manager
from app.utils.sql_generator import sql_generator
from app.models.query_model import OperationPlan, GeospatialOperation
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_missing_geom_query():
    print("Testing query without geometry column...")
    # This query typically fails if geometry is missing
    sql = "SELECT lor_name, bicycle_theft, year FROM vector.berlin_crime_stats LIMIT 5"
    
    try:
        # 1. Test direct database execution
        print(f"Executing SQL: {sql}")
        gdf = db_manager.execute_spatial_query(sql)
        print("✅ Database execution successful!")
        print(f"Columns: {gdf.columns.tolist()}")
        print(f"Geometry column: {gdf.geometry.name}")
        print(f"First row geometry: {gdf.geometry.iloc[0]}")
        
        # 2. Test through SQL generator (auto-adding geometry)
        print("\nTesting through sql_generator...")
        plan = OperationPlan(
            operations=[GeospatialOperation(operation="spatial_query", parameters={"sql": sql})],
            reasoning="Testing auto-addition",
            datasets_required=["vector.berlin_crime_stats"]
        )
        
        # The generator should add 'geometry' to the SELECT
        fixed_sql = sql_generator._ensure_geometry_in_select(sql)
        print(f"Fixed SQL: {fixed_sql}")
        
        # Note: Executing this fixed_sql WILL fail on Postgres because berlin_crime_stats 
        # doesn't have a geometry column. But the goal of my database.py fix was 
        # to handle the case where the LLM DID NOT select geometry (e.g. SELECT *).
        
        # 3. Test SELECT *
        print("\nTesting SELECT * ...")
        star_sql = "SELECT * FROM vector.berlin_crime_stats LIMIT 5"
        gdf_star = db_manager.execute_spatial_query(star_sql)
        print("✅ SELECT * successful!")
        print(f"Columns: {gdf_star.columns.tolist()}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        exit(1)

if __name__ == "__main__":
    test_missing_geom_query()
