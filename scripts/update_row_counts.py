"""
One-off script: populate row_count in metadata.table_descriptions with actual counts.

The LLM uses row_count to compare table granularities (more rows = finer geography).
All values were NULL, preventing the agent from distinguishing e.g. a 12-row
district table from a 448-row Planungsraum table.

Run once, then re-run whenever large bulk imports add/remove rows.
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")

CONNECTION_STRING = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def main():
    engine = create_engine(CONNECTION_STRING)

    with engine.connect() as conn:
        # Get all table names tracked in metadata
        rows = conn.execute(
            text("SELECT table_name FROM metadata.table_descriptions ORDER BY table_name")
        ).fetchall()

        table_names = [r[0] for r in rows]
        print(f"Found {len(table_names)} tables in metadata.table_descriptions\n")

        updated = 0
        skipped = 0

        for table_name in table_names:
            # Only count tables that exist in the vector schema
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'vector' AND table_name = :t"
                ),
                {"t": table_name},
            ).fetchone()

            if not exists:
                print(f"  SKIP {table_name} (not in vector schema)")
                skipped += 1
                continue

            try:
                count = conn.execute(
                    text(f'SELECT COUNT(*) FROM vector."{table_name}"')
                ).scalar()

                conn.execute(
                    text(
                        "UPDATE metadata.table_descriptions "
                        "SET row_count = :n WHERE table_name = :t"
                    ),
                    {"n": count, "t": table_name},
                )
                print(f"  OK  {table_name}: {count} rows")
                updated += 1
            except Exception as e:
                print(f"  ERR {table_name}: {e}")
                skipped += 1

        conn.commit()

    print(f"\nDone. Updated: {updated}, Skipped/errors: {skipped}")


if __name__ == "__main__":
    main()
