
import psycopg2
import time

try:
    conn = psycopg2.connect(
        host='localhost',
        database='geoassist',
        user='geoassist',
        password='geoassist_password',
        port=5433
    )
    cur = conn.cursor()

    print('=== Vertex Finding Benchmark ===')
    
    # Test point (Berlin center)
    lon, lat = 13.405, 52.52

    # Old Query (Current problematic one)
    start = time.time()
    cur.execute(f"""
        SELECT v.id 
        FROM vector.custom_roads_vertices_pgr v
        JOIN vector.custom_roads r ON (r.source = v.id OR r.target = v.id)
        WHERE r.fclass = 'footway'
        ORDER BY v.the_geom <-> ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)
        LIMIT 1
    """)
    res = cur.fetchone()
    old_time = (time.time() - start) * 1000
    print(f"Old Query: {old_time:.1f}ms (Result: {res[0] if res else 'None'})")

    # New Proposed Query (Search edges first)
    start = time.time()
    cur.execute(f"""
        WITH nearest_edge AS (
            SELECT id, source, target, geometry,
                ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography) as edge_dist
            FROM vector.custom_roads
            WHERE fclass = 'footway'
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)
            LIMIT 1
        )
        SELECT 
            CASE 
                WHEN ST_Distance(ST_StartPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)) < 
                     ST_Distance(ST_EndPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326))
                THEN source
                ELSE target
            END as vertex_id,
            -- Get coordinates of the chosen vertex
            CASE 
                WHEN ST_Distance(ST_StartPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)) < 
                     ST_Distance(ST_EndPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326))
                THEN ST_X(ST_StartPoint(geometry))
                ELSE ST_X(ST_EndPoint(geometry))
            END as x,
            CASE 
                WHEN ST_Distance(ST_StartPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)) < 
                     ST_Distance(ST_EndPoint(geometry), ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326))
                THEN ST_Y(ST_StartPoint(geometry))
                ELSE ST_Y(ST_EndPoint(geometry))
            END as y,
            -- Use distance to the vertex, not just the edge
            LEAST(
                ST_Distance(ST_StartPoint(geometry)::geography, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography),
                ST_Distance(ST_EndPoint(geometry)::geography, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography)
            ) as distance_m
        FROM nearest_edge
    """)
    res = cur.fetchone()
    new_time = (time.time() - start) * 1000
    print(f"New Query: {new_time:.1f}ms (Result: {res[0] if res else 'None'})")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
