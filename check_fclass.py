
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

def check_fclasses():
    print(f"Connecting to {DATABASE_URL}...")
    engine = create_engine(DATABASE_URL)
    
    print(f"\n--- Checking distinct fclass values in vector.custom_roads ---")
    
    with engine.connect() as conn:
        # Get count of each fclass to see which are common
        query = text("""
            SELECT fclass, COUNT(*) as count 
            FROM vector.custom_roads 
            GROUP BY fclass 
            ORDER BY count DESC
        """)
        
        result = conn.execute(query)
        rows = result.fetchall()
        
        print(f"{'FClass':<20} | {'Count':<10}")
        print("-" * 33)
        for row in rows:
            print(f"{row[0]:<20} | {row[1]:<10}")
            
    # Check what is CURRENTLY included in strict routing
    current_strict = ['footway', 'path', 'pedestrian', 'steps', 'living_street', 'track']
    print("\n--- Current Strict Profile ---")
    print(current_strict)

if __name__ == "__main__":
    check_fclasses()
