
import sys
import os
from sqlalchemy import create_engine, text

# Database configuration (matching app/utils/database.py defaults)
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

def diagnose_routing():
    print(f"Connecting to {DATABASE_URL}...")
    engine = create_engine(DATABASE_URL)
    
    # Vertices from previous successful run
    source = 47539
    target = 48595
    
    print(f"\n--- DIAGNOSTIC: Routing {source} -> {target} ---")
    
    # Test Fix: ST_Dump Unpack
    print(f"\nTesting Fix (ST_Dump)...")
    fix_query = text("""
        WITH dijkstra_result AS (
            SELECT * FROM pgr_dijkstra(
                :sql,
                :source,
                :target,
                FALSE
            )
        ),
        path_components AS (
            SELECT 
                d.seq,
                d.cost,
                (ST_Dump(
                    CASE 
                        WHEN d.node = r.source THEN r.geometry 
                        ELSE ST_Reverse(r.geometry) 
                    END
                )).geom as geometry
            FROM dijkstra_result d
            JOIN vector.custom_roads r ON d.edge = r.id
            WHERE d.edge != -1
            ORDER BY d.seq
        )
        SELECT
            ST_AsGeoJSON(ST_MakeLine(geometry)) as geometry_json,
            (SELECT SUM(cost) FROM dijkstra_result) as distance_m
        FROM path_components
    """)
    
    try:
        with engine.connect() as conn:
            # Reusing param_sql (Strict SQL)
            param_sql = "SELECT id, source, target, cost FROM vector.custom_roads WHERE source != target AND fclass IN ('footway', 'path', 'pedestrian', 'steps', 'living_street', 'track')"
            
            result = conn.execute(fix_query, {"sql": param_sql, "source": source, "target": target})
            row = result.fetchone()
            
            if row:
                if row[0]:
                    print("✅ ST_Dump FIX WORKED! Geometry returned.")
                    print(f"Distance: {row[1]}")
                    print(f"Geometry Start: {row[0][:50]}...")
                else:
                    print("❌ St_Dump failure. Geometry still None")
            else:
                print("❌ No row returned")

    except Exception as e:
        print(f"❌ Fix query failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_routing()
