"""
Automatic Table Discovery and Description Generation

Automatically discovers new tables added to the database and generates
rich metadata using the LLM (DeepSeek). Writes to both the JSON file
and the metadata.table_descriptions DB table.
"""

import json
import threading
from typing import Dict, List, Any, Optional
from pathlib import Path

from app.utils.database import db_manager
from app.utils.schema_discovery import schema_discovery

# Serializes JSON file writes to prevent races between SchemaWatcher and manual refresh
_DISCOVERY_LOCK = threading.Lock()


class AutoTableDiscovery:
    """Automatically discover new tables and generate rich descriptions"""

    DESCRIPTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "metadata" / "table_descriptions.json"

    @staticmethod
    def get_new_tables() -> List[str]:
        """
        Find tables in database that don't have descriptions yet.

        Returns:
            List of table names without descriptions
        """
        try:
            all_tables = db_manager.get_available_tables(schema="vector")
            existing_descriptions = schema_discovery.get_all_descriptions()
            return [t for t in all_tables if t not in existing_descriptions]
        except Exception as e:
            print(f"Error getting new tables: {e}")
            return []

    @staticmethod
    def get_table_structure(table_name: str) -> Dict[str, Any]:
        """
        Get table structure information for description generation.

        Args:
            table_name: Name of the table

        Returns:
            Dictionary with table structure info
        """
        try:
            info = db_manager.get_table_info(table_name, schema="vector")
            return {
                "table_name": table_name,
                "row_count": info.get("row_count", 0),
                "geometry_type": info.get("geometry_type", "UNKNOWN"),
                "columns": [col["name"] for col in info.get("columns", [])],
                "column_types": {col["name"]: col["type"] for col in info.get("columns", [])},
            }
        except Exception as e:
            print(f"Error getting table structure for {table_name}: {e}")
            return {}

    @staticmethod
    def get_sample_values(table_name: str) -> List[Dict[str, Any]]:
        """
        Fetch up to 3 sample rows (non-geometry columns) for richer LLM context.

        Args:
            table_name: Name of the table in the vector schema

        Returns:
            List of sample row dicts (may be empty on failure)
        """
        try:
            from sqlalchemy import text
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    text(f"""
                        SELECT * FROM vector.{table_name}
                        LIMIT 3
                    """)
                )
                rows = result.mappings().all()
                samples = []
                for row in rows:
                    sample = {}
                    for k, v in dict(row).items():
                        # Skip geometry-like columns (too large)
                        if k.lower() in ("geometry", "geom", "geom_25833", "wkb_geometry", "the_geom"):
                            continue
                        sample[k] = str(v)[:100] if v is not None else None
                    samples.append(sample)
                return samples
        except Exception as e:
            print(f"⚠️ Could not get sample values for {table_name}: {e}")
            return []

    @staticmethod
    def generate_description_from_structure(table_name: str, structure: Dict[str, Any]) -> str:
        """
        Generate a basic description from table structure without LLM.
        Fallback when LLM is unavailable.

        Args:
            table_name: Name of the table
            structure: Table structure information

        Returns:
            Generated description string
        """
        name = table_name.replace("osm_", "").replace("berlin_", "").replace("_", " ")
        name = name.title()

        geom_type = structure.get("geometry_type", "UNKNOWN")
        row_count = structure.get("row_count", 0)

        if geom_type == "POINT":
            desc = f"{name} point locations"
        elif geom_type in ["POLYGON", "MULTIPOLYGON"]:
            desc = f"{name} area boundaries"
        elif geom_type in ["LINESTRING", "MULTILINESTRING"]:
            desc = f"{name} linear features"
        else:
            desc = f"{name} geospatial data"

        if row_count > 0:
            desc += f" ({row_count:,} features)"

        return desc

    @staticmethod
    def generate_description_with_llm(table_name: str, structure: Dict[str, Any]) -> str:
        """
        Generate a plain description using DeepSeek LLM (legacy method).
        Kept for backward compatibility. Prefer generate_rich_metadata_with_llm().

        Args:
            table_name: Name of the table
            structure: Table structure information

        Returns:
            LLM-generated description string
        """
        metadata = AutoTableDiscovery.generate_rich_metadata_with_llm(table_name, structure)
        return metadata.get("description", AutoTableDiscovery.generate_description_from_structure(table_name, structure))

    @staticmethod
    def generate_rich_metadata_with_llm(table_name: str, structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate rich structured metadata using DeepSeek LLM.

        Requests a JSON response with:
        - description: 1 sentence, what this table contains
        - usage_hint: 1-2 sentences HOW to query it (common JOINs, WHERE clauses, typical filters)
        - key_columns: list of 3-6 most important non-geometry columns
        - related_tables: list of tables commonly used with this one
        - analysis_patterns: applicable tags from [proximity_analysis, routing, coverage,
          demographics, environmental, planning, emergency, lighting]

        Args:
            table_name: Name of the table
            structure: Table structure information

        Returns:
            Dict with rich metadata fields; falls back to basic description on failure
        """
        fallback = {
            "description": AutoTableDiscovery.generate_description_from_structure(table_name, structure),
            "usage_hint": "",
            "key_columns": structure.get("columns", [])[:6],
            "related_tables": [],
            "analysis_patterns": [],
        }

        try:
            import requests
            import os
            from dotenv import load_dotenv

            load_dotenv()
            DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
            DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

            if not DEEPSEEK_API_KEY:
                print("Warning: DEEPSEEK_API_KEY not found, using structural generation")
                return fallback

            columns = structure.get("columns", [])
            geom_type = structure.get("geometry_type", "UNKNOWN")
            row_count = structure.get("row_count", 0)

            # Get sample values for richer context
            samples = AutoTableDiscovery.get_sample_values(table_name)
            samples_str = json.dumps(samples, default=str)[:500] if samples else "none available"

            prompt = f"""You are a PostGIS database expert. Analyze this spatial database table and return ONLY a JSON object.

Table name: {table_name}
Geometry type: {geom_type}
Row count: {row_count:,}
Columns: {', '.join(columns[:20])}
Sample rows: {samples_str}

Return ONLY valid JSON (no markdown, no explanation) with exactly these keys:
{{
  "description": "1 sentence describing what this table contains",
  "usage_hint": "1-2 sentences on HOW to query it: common JOINs, WHERE clauses, typical filters",
  "key_columns": ["col1", "col2", "col3"],
  "related_tables": ["other_table1", "other_table2"],
  "analysis_patterns": ["tag1", "tag2"]
}}

For analysis_patterns, pick applicable tags from: proximity_analysis, routing, coverage, demographics, environmental, planning, emergency, lighting

Respond with ONLY the JSON object."""

            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300,
            }

            response = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=20,
            )

            if response.status_code == 200:
                raw = response.json()["choices"][0]["message"]["content"].strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                metadata = json.loads(raw)
                # Validate required keys
                for key in ("description", "usage_hint", "key_columns", "related_tables", "analysis_patterns"):
                    if key not in metadata:
                        metadata[key] = fallback[key]
                return metadata
            else:
                print(f"Warning: LLM request failed ({response.status_code}), using structural generation")
                return fallback

        except Exception as e:
            print(f"Warning: LLM rich metadata generation failed for {table_name}: {e}")
            return fallback

    @staticmethod
    def _write_to_db(table_name: str, metadata_dict: Dict[str, Any]) -> None:
        """
        Upsert rich metadata into metadata.table_descriptions DB table.

        Handles the new columns (usage_hint, key_columns, related_tables,
        analysis_patterns, updated_at) gracefully if they don't exist yet.

        Args:
            table_name: Name of the table
            metadata_dict: Rich metadata dict from generate_rich_metadata_with_llm()
        """
        try:
            from sqlalchemy import text

            description = metadata_dict.get("description", "")
            usage_hint = metadata_dict.get("usage_hint", "")
            key_columns = metadata_dict.get("key_columns", [])
            related_tables = metadata_dict.get("related_tables", [])
            analysis_patterns = metadata_dict.get("analysis_patterns", [])

            with db_manager.engine.begin() as conn:
                # Try upsert with new columns first
                try:
                    conn.execute(
                        text("""
                            INSERT INTO metadata.table_descriptions
                                (table_name, description, usage_hint, key_columns,
                                 related_tables, analysis_patterns, updated_at)
                            VALUES
                                (:table_name, :description, :usage_hint, :key_columns,
                                 :related_tables, :analysis_patterns, NOW())
                            ON CONFLICT (table_name) DO UPDATE SET
                                description = EXCLUDED.description,
                                usage_hint = EXCLUDED.usage_hint,
                                key_columns = EXCLUDED.key_columns,
                                related_tables = EXCLUDED.related_tables,
                                analysis_patterns = EXCLUDED.analysis_patterns,
                                updated_at = NOW()
                        """),
                        {
                            "table_name": table_name,
                            "description": description,
                            "usage_hint": usage_hint,
                            "key_columns": key_columns,
                            "related_tables": related_tables,
                            "analysis_patterns": analysis_patterns,
                        },
                    )
                except Exception:
                    # Fallback: upsert with just description (new columns not migrated yet)
                    conn.execute(
                        text("""
                            INSERT INTO metadata.table_descriptions (table_name, description)
                            VALUES (:table_name, :description)
                            ON CONFLICT (table_name) DO UPDATE SET
                                description = EXCLUDED.description
                        """),
                        {"table_name": table_name, "description": description},
                    )
            print(f"  ✅ DB upsert successful for {table_name}")
        except Exception as e:
            print(f"  ⚠️ DB upsert failed for {table_name}: {e}")

    @staticmethod
    def discover_single_table(table_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover and document a single table (called by SchemaWatcher for new tables).

        Generates rich metadata, writes to JSON file and DB table.

        Args:
            table_name: Name of the table to discover

        Returns:
            Metadata dict on success, None on failure
        """
        print(f"\n🔍 Discovering new table: {table_name}")

        structure = AutoTableDiscovery.get_table_structure(table_name)
        if not structure:
            print(f"  ⚠️ Could not get structure for {table_name}, skipping")
            return None

        print(f"  🧠 Generating rich metadata with AI...")
        metadata = AutoTableDiscovery.generate_rich_metadata_with_llm(table_name, structure)
        metadata["table_name"] = table_name
        metadata["row_count"] = structure.get("row_count")
        metadata["geometry_type"] = structure.get("geometry_type")

        # Write to JSON file (thread-safe)
        with _DISCOVERY_LOCK:
            try:
                existing = {}
                if AutoTableDiscovery.DESCRIPTIONS_FILE.exists():
                    with open(AutoTableDiscovery.DESCRIPTIONS_FILE, "r") as f:
                        existing = json.load(f)

                existing[table_name] = metadata["description"]
                existing = dict(sorted(existing.items()))

                AutoTableDiscovery.DESCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(AutoTableDiscovery.DESCRIPTIONS_FILE, "w") as f:
                    json.dump(existing, f, indent=2)
                print(f"  ✅ JSON file updated for {table_name}")
            except Exception as e:
                print(f"  ⚠️ JSON file write failed for {table_name}: {e}")

        # Write to DB
        AutoTableDiscovery._write_to_db(table_name, metadata)

        print(f"  ✅ Description: {metadata['description']}")
        if metadata.get("usage_hint"):
            print(f"  💡 Usage: {metadata['usage_hint']}")

        return metadata

    @staticmethod
    def backfill_rich_metadata() -> Dict[str, Any]:
        """
        Back-fill usage_hint and other rich metadata for tables that already have
        a basic description but are missing the new structured fields.

        Safe to run multiple times (uses ON CONFLICT DO UPDATE).

        Returns:
            Dictionary with back-fill results
        """
        print("\n" + "=" * 70)
        print("BACK-FILL RICH METADATA - Updating existing table descriptions...")
        print("=" * 70)

        try:
            from sqlalchemy import text
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT table_name FROM metadata.table_descriptions
                        WHERE usage_hint IS NULL OR usage_hint = ''
                        ORDER BY table_name
                    """)
                )
                tables_needing_update = [row[0] for row in result]
        except Exception as e:
            print(f"⚠️ Could not query for tables needing back-fill: {e}")
            return {"status": "error", "message": str(e)}

        if not tables_needing_update:
            print("✅ All tables already have rich metadata.")
            return {"status": "success", "updated": 0, "message": "All tables already have usage_hint"}

        print(f"\n🔍 Found {len(tables_needing_update)} tables needing rich metadata:")
        for t in tables_needing_update:
            print(f"  - {t}")

        updated = []
        failed = []
        for table_name in tables_needing_update:
            print(f"\n📊 Processing: {table_name}")
            structure = AutoTableDiscovery.get_table_structure(table_name)
            if not structure:
                print(f"  ⚠️ Could not get structure, skipping")
                failed.append(table_name)
                continue

            print(f"  🧠 Generating rich metadata with AI...")
            metadata = AutoTableDiscovery.generate_rich_metadata_with_llm(table_name, structure)
            AutoTableDiscovery._write_to_db(table_name, metadata)
            updated.append(table_name)

        print(f"\n✅ Back-fill complete. Updated: {len(updated)}, Failed: {len(failed)}")
        return {
            "status": "success",
            "updated": len(updated),
            "failed": failed,
            "message": f"Back-filled rich metadata for {len(updated)} tables",
        }

    @staticmethod
    def auto_discover_and_update() -> Dict[str, Any]:
        """
        Automatically discover new tables and update descriptions with rich metadata.

        Returns:
            Dictionary with discovery results
        """
        print("\n" + "=" * 70)
        print("AUTO TABLE DISCOVERY - Searching for new tables...")
        print("=" * 70)

        new_tables = AutoTableDiscovery.get_new_tables()

        if not new_tables:
            print("✅ No new tables found. System is up to date!")
            return {
                "status": "success",
                "new_tables_found": 0,
                "tables_added": [],
                "message": "No new tables to discover",
            }

        print(f"\n🔍 Found {len(new_tables)} new table(s):")
        for table in new_tables:
            print(f"  - {table}")

        added_tables = []
        for table_name in new_tables:
            metadata = AutoTableDiscovery.discover_single_table(table_name)
            if metadata:
                added_tables.append(metadata)

        if added_tables:
            # Refresh schema discovery cache
            schema_discovery.refresh_cache()
            print("✅ Schema cache refreshed")

            return {
                "status": "success",
                "new_tables_found": len(new_tables),
                "tables_added": added_tables,
                "message": f"Successfully discovered and added descriptions for {len(added_tables)} table(s)",
            }
        else:
            return {
                "status": "success",
                "new_tables_found": len(new_tables),
                "tables_added": [],
                "message": "Found new tables but could not generate descriptions",
            }


# Global instance
auto_discovery = AutoTableDiscovery()
