"""
One-time migration: populate app/ontology/table_graph.ttl from metadata.table_descriptions.

Run this once after setting up the knowledge graph system. After that, the graph
is kept current automatically by AutoTableDiscovery (new tables) and SchemaWatcher
(deleted tables). Re-running this script is safe — it rebuilds the table graph
from scratch (ontology triples are preserved, only table nodes are refreshed).

Usage:
    python scripts/migrate_db_to_graph.py
"""

import os
import sys
import json
from pathlib import Path

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")
CONNECTION_STRING = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def main():
    print("🔗 Connecting to database...")
    engine = create_engine(CONNECTION_STRING)

    print("📖 Reading metadata.table_descriptions...")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_name, description, geometry_type, row_count,
                   analysis_patterns, related_tables, key_columns
            FROM metadata.table_descriptions
            ORDER BY table_name
        """)).fetchall()

    print(f"   Found {len(rows)} tables")

    print("🧠 Loading semantic layer...")
    from app.utils.semantic_layer import get_semantic_layer
    sl = get_semantic_layer()

    # Remove all existing table node triples (leave ontology class triples intact)
    # Table nodes have geo:GeoDataset type — remove those subjects only
    from rdflib.namespace import RDF
    from app.utils.semantic_layer import GEO

    existing_tables = list(sl.graph.subjects(RDF.type, GEO.GeoDataset))
    for uri in existing_tables:
        sl.graph.remove((uri, None, None))
    print(f"   Cleared {len(existing_tables)} existing table nodes from graph")

    print("✍️  Writing RDF triples for each table...")
    written = 0
    skipped = 0

    for row in rows:
        table_name = row[0]
        try:
            # Parse JSON arrays stored in DB
            analysis_patterns = row[4] if isinstance(row[4], list) else (
                json.loads(row[4]) if row[4] else []
            )
            related_tables = row[5] if isinstance(row[5], list) else (
                json.loads(row[5]) if row[5] else []
            )
            key_columns = row[6] if isinstance(row[6], list) else (
                json.loads(row[6]) if row[6] else []
            )

            metadata = {
                "description": row[1] or "",
                "geometry_type": row[2] or "",
                "row_count": row[3],
                "analysis_patterns": analysis_patterns,
                "related_tables": related_tables,
                "key_columns": key_columns,
            }

            sl.add_table_triples(table_name, metadata)
            print(f"   ✅ {table_name} — patterns: {analysis_patterns}")
            written += 1

        except Exception as e:
            print(f"   ⚠️  {table_name}: {e}")
            skipped += 1

    out_path = sl.ontology_dir / "table_graph.ttl"
    print(f"\n✅ Done. Written: {written}, Skipped: {skipped}")
    print(f"📄 Graph saved to: {out_path}")
    print(f"   Total triples in graph: {len(sl.graph)}")


if __name__ == "__main__":
    main()
