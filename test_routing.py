
import psycopg2

try:
    conn = psycopg2.connect(
        host='localhost',
        database='geoassist',
        user='geoassist',
        password='geoassist_password',
        port=5433
    )
    cur = conn.cursor()

    print('=== Testing Footway-only Routing ===')

    cur.execute('''
        SELECT v.id 
        FROM vector.custom_roads_vertices_pgr v
        JOIN vector.custom_roads r ON (r.source = v.id OR r.target = v.id)
        WHERE r.fclass = 'footway'
        GROUP BY v.id
        HAVING COUNT(*) >= 3
        LIMIT 20
    ''')
    vertices = [row[0] for row in cur.fetchall()]
    print(f'Test footway vertices: {vertices}')

    found = False
    for i in range(len(vertices)):
        if found: break
        for j in range(i+1, len(vertices)):
            v1, v2 = vertices[i], vertices[j]
            
            # Check if path exists
            cur.execute(f"""
                SELECT COUNT(*) FROM pgr_dijkstra(
                    'SELECT id, source, target, cost FROM vector.custom_roads WHERE source != target AND fclass = ''footway''',
                    {v1}, {v2}, FALSE
                )
            """)
            count = cur.fetchone()[0]
            
            if count > 0:
                print(f"✅ Route found between {v1} and {v2} ({count} segments)")
                
                # Analyze road types
                query = f"""
                    WITH dijkstra_result AS (
                        SELECT * FROM pgr_dijkstra(
                            'SELECT id, source, target, cost FROM vector.custom_roads WHERE source != target AND fclass = ''footway''',
                            {v1}, {v2}, FALSE
                        )
                    ),
                    path_segments AS (
                        SELECT r.fclass
                        FROM dijkstra_result d
                        JOIN vector.custom_roads r ON d.edge = r.id
                        WHERE d.edge > 0
                    )
                    SELECT fclass, COUNT(*) 
                    FROM path_segments 
                    GROUP BY fclass
                """
                
                cur.execute(query)
                print('Route segments used:')
                for row in cur.fetchall():
                    print(f'  {row[0]}: {row[1]}')
                
                found = True
                break
    
    if not found:
        print("❌ No route found between any of the test vertices (graph likely disconnected)")

    conn.close()
except Exception as e:
    print(f"Error: {e}")
