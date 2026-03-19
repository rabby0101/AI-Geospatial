"""
Script to repair the topology of vector.custom_roads for proper routing.

The issue: Many road endpoints are slightly off from each other, creating
disconnected network components. This script will:
1. Rebuild the topology with a larger tolerance to snap nearby vertices
2. Analyze and report on network connectivity
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import db_manager
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def repair_topology(tolerance: float = 0.0001):
    """
    Rebuild network topology with a larger tolerance.
    
    Args:
        tolerance: Tolerance in degrees for snapping vertices together.
                   0.0001 degrees ≈ 11 meters at Berlin's latitude
                   0.00005 degrees ≈ 5.5 meters
    """
    db_manager.initialize()
    
    logger.info(f"Starting topology repair with tolerance {tolerance} degrees (~{tolerance * 111000:.1f}m)")
    
    with db_manager.engine.connect() as conn:
        # Step 1: Drop existing topology
        logger.info("Step 1: Dropping existing vertices table...")
        conn.execute(text("DROP TABLE IF EXISTS vector.custom_roads_vertices_pgr CASCADE"))
        conn.commit()
        
        # Step 2: Reset source/target columns
        logger.info("Step 2: Resetting source/target columns...")
        conn.execute(text("""
            UPDATE vector.custom_roads 
            SET source = NULL, target = NULL
        """))
        conn.commit()
        
        # Step 3: Rebuild topology with larger tolerance
        logger.info(f"Step 3: Rebuilding topology (tolerance={tolerance})...")
        logger.info("This may take several minutes for 450k+ roads...")
        
        result = conn.execute(text(f"""
            SELECT pgr_createTopology(
                'vector.custom_roads',
                {tolerance},
                'geometry',
                'id',
                'source',
                'target',
                rows_where := 'true',
                clean := true
            )
        """))
        status = result.fetchone()[0]
        conn.commit()
        logger.info(f"Topology creation returned: {status}")
        
        # Step 4: Analyze the new topology
        logger.info("Step 4: Analyzing new topology...")
        
        # Count vertices
        result = conn.execute(text("SELECT COUNT(*) FROM vector.custom_roads_vertices_pgr"))
        vertex_count = result.fetchone()[0]
        logger.info(f"Total vertices: {vertex_count:,}")
        
        # Count edges with valid source/target
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM vector.custom_roads 
            WHERE source IS NOT NULL AND target IS NOT NULL
        """))
        connected_edges = result.fetchone()[0]
        logger.info(f"Connected edges: {connected_edges:,}")
        
        # Analyze vertex degrees
        result = conn.execute(text("""
            WITH edge_counts AS (
                SELECT v.id, COUNT(*) as edge_count
                FROM vector.custom_roads_vertices_pgr v
                JOIN vector.custom_roads r ON r.source = v.id OR r.target = v.id
                GROUP BY v.id
            )
            SELECT 
                SUM(CASE WHEN edge_count = 1 THEN 1 ELSE 0 END) as dead_ends,
                SUM(CASE WHEN edge_count = 2 THEN 1 ELSE 0 END) as degree_2,
                SUM(CASE WHEN edge_count >= 3 THEN 1 ELSE 0 END) as junctions
            FROM edge_counts
        """))
        row = result.fetchone()
        dead_ends = row[0] or 0
        degree_2 = row[1] or 0
        junctions = row[2] or 0
        
        logger.info(f"Dead ends (degree 1): {dead_ends:,} ({100*dead_ends/vertex_count:.1f}%)")
        logger.info(f"Degree 2 vertices: {degree_2:,} ({100*degree_2/vertex_count:.1f}%)")
        logger.info(f"Junctions (degree 3+): {junctions:,} ({100*junctions/vertex_count:.1f}%)")
        
        # Step 5: Test a sample route
        logger.info("Step 5: Testing sample route...")
        
        # Find two vertices that should be connected
        result = conn.execute(text("""
            SELECT v.id
            FROM vector.custom_roads_vertices_pgr v
            JOIN vector.custom_roads r ON r.source = v.id OR r.target = v.id
            GROUP BY v.id
            HAVING COUNT(*) >= 3
            LIMIT 2
        """))
        junction_vertices = [row[0] for row in result.fetchall()]
        
        if len(junction_vertices) >= 2:
            v1, v2 = junction_vertices[0], junction_vertices[1]
            logger.info(f"Testing route between junctions {v1} and {v2}...")
            
            result = conn.execute(text(f"""
                SELECT COUNT(*) FROM pgr_dijkstra(
                    'SELECT id, source, target, cost FROM vector.custom_roads',
                    {v1}, {v2}, FALSE
                )
            """))
            path_nodes = result.fetchone()[0]
            
            if path_nodes > 0:
                logger.info(f"✅ Route found with {path_nodes} nodes!")
            else:
                logger.warning("❌ No route found - network still fragmented")
        
        logger.info("Topology repair complete!")
        
        return {
            "vertices": vertex_count,
            "dead_ends": dead_ends,
            "junctions": junctions,
            "dead_end_percentage": 100 * dead_ends / vertex_count if vertex_count else 0
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Repair custom roads topology")
    parser.add_argument(
        "--tolerance", 
        type=float, 
        default=0.0001,
        help="Tolerance in degrees for snapping (0.0001 ≈ 11m, 0.00005 ≈ 5.5m)"
    )
    args = parser.parse_args()
    
    repair_topology(args.tolerance)
