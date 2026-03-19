
import psycopg2
import sys

try:
    conn = psycopg2.connect(
        host='localhost',
        database='geoassist',
        user='geoassist',
        password='geoassist_password',
        port=5433
    )
    cur = conn.cursor()

    print('=== Footway Routing Diagnostics ===')

    # 1. Check if we can find ANY footway vertices
    cur.execute('''
        SELECT count(*) 
        FROM vector.custom_roads 
        WHERE fclass = 'footway'
    ''')
    count = cur.fetchone()[0]
    print(f"Total footway segments: {count:,}")
    
    if count == 0:
        print("CRITICAL: No footways found in database!")
        sys.exit(1)

    # 2. Check if vertices are properly shared (topology)
    cur.execute('''
        SELECT count(DISTINCT v.id)
        FROM vector.custom_roads_vertices_pgr v
        JOIN vector.custom_roads r ON (r.source = v.id OR r.target = v.id)
        WHERE r.fclass = 'footway'
    ''')
    v_count = cur.fetchone()[0]
    print(f"Vertices connected to footways: {v_count:,}")

    # 3. Test various paths to see connectivity rate
    print("\nTesting connectivity (100 random pairs)...")
    cur.execute('''
        WITH sample_vertices AS (
            SELECT v.id 
            FROM vector.custom_roads_vertices_pgr v
            JOIN vector.custom_roads r ON (r.source = v.id OR r.target = v.id)
            WHERE r.fclass = 'footway'
            GROUP BY v.id
            ORDER BY RANDOM()
            LIMIT 20
        )
        SELECT array_agg(id) FROM sample_vertices
    ''')
    vertices = cur.fetchone()[0]
    
    success = 0
    attempts = 0
    
    for i in range(len(vertices)):
        for j in range(i+1, len(vertices)):
            attempts += 1
            v1, v2 = vertices[i], vertices[j]
            try:
                cur.execute(f"""
                    SELECT count(*) FROM pgr_dijkstra(
                        'SELECT id, source, target, cost FROM vector.custom_roads WHERE source != target AND fclass = ''footway''',
                        {v1}, {v2}, FALSE
                    )
                """)
                if cur.fetchone()[0] > 0:
                    success += 1
            except Exception as e:
                print(f"Query Error on pair {v1}->{v2}: {e}")
                
    print(f"Connectivity Rate: {success}/{attempts} ({100*success/attempts if attempts else 0:.1f}%)")
    
    if success == 0:
        print("\nWARNING: Graph appears totally disconnected or query is failing everywhere.")
        # Try to debug the query error by running a single one and catching full error
        try:
            cur.execute(f"""
                SELECT * FROM pgr_dijkstra(
                    'SELECT id, source, target, cost FROM vector.custom_roads WHERE source != target AND fclass = ''footway''',
                    {vertices[0]}, {vertices[1]}, FALSE
                )
            """)
        except Exception as e:
            print(f"Detailed Query Error: {e}")

    # 4. Check if 'pedestrian' or 'path' acts as glue?
    print("\nChecking what connects footway components...")
    # Find edges that touch footway vertices but are NOT footways
    cur.execute('''
        SELECT r.fclass, COUNT(*) 
        FROM vector.custom_roads r
        JOIN vector.custom_roads r_foot ON (r.source = r_foot.source OR r.source = r_foot.target OR r.target = r_foot.source OR r.target = r_foot.target)
        WHERE r.fclass != 'footway' AND r_foot.fclass = 'footway'
        GROUP BY r.fclass
        ORDER BY COUNT(*) DESC
        LIMIT 5
    ''')
    print("Non-footway roads connected to footways:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    conn.close()
    
except Exception as e:
    print(f"Script Error: {e}")
