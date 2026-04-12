"""
Automatic Table Discovery and Description Generation

Automatically discovers new tables added to the database and generates
rich metadata using the LLM (DeepSeek). Writes to both the JSON file
and the metadata.table_descriptions DB table.
"""

import json
import re
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
    def _compute_column_top_values(
        table_name: str,
        columns: List[str],
        column_types: Dict[str, str],
    ) -> Dict[str, str]:
        """
        For every text/varchar column, fetch the top-20 most frequent distinct values
        and return them as comma-separated strings (max 250 chars each).

        Uses pg_stats (free — already computed by PostgreSQL ANALYZE) with a GROUP BY
        fallback. Called once at table discovery time; results stored in
        metadata.column_descriptions.example_value so queries pay zero extra DB cost.

        Returns: {column_name: "val1, val2, val3, ..."} for qualifying string columns.
        """
        _SKIP_COLS = {"geometry", "geom", "geom_25833", "wkb_geometry", "the_geom"}
        _ID_RE = re.compile(r"(^id$|_id$|^fid$|^gid$|^osm_id$|^ogc_fid$)", re.IGNORECASE)
        _SKIP_KW = ("url", "www", "scan", "href", "http")

        result: Dict[str, str] = {}
        try:
            from sqlalchemy import text as sa_text

            with db_manager.engine.connect() as conn:
                for col in columns:
                    if col.lower() in _SKIP_COLS:
                        continue
                    if _ID_RE.search(col):
                        continue
                    if any(kw in col.lower() for kw in _SKIP_KW):
                        continue
                    ctype = column_types.get(col, "").lower()
                    if not any(t in ctype for t in ("text", "varchar", "char")):
                        continue

                    vals: List[str] = []

                    # Try pg_stats first — instant, no table scan required
                    try:
                        pg_row = conn.execute(sa_text(
                            "SELECT most_common_vals FROM pg_stats "
                            "WHERE schemaname='vector' AND tablename=:t AND attname=:c"
                        ), {"t": table_name, "c": col}).fetchone()
                        if pg_row and pg_row[0]:
                            raw = str(pg_row[0]).strip("{}")
                            vals = [v.strip().strip('"') for v in raw.split(",") if v.strip()][:20]
                    except Exception:
                        pass

                    # Fallback: GROUP BY (acceptable once at discovery time)
                    if not vals:
                        try:
                            rows = conn.execute(sa_text(
                                f'SELECT "{col}", COUNT(*) AS cnt FROM vector.{table_name} '
                                f'WHERE "{col}" IS NOT NULL AND "{col}" != \'\' '
                                f'GROUP BY "{col}" ORDER BY cnt DESC LIMIT 20'
                            )).fetchall()
                            vals = [str(r[0])[:60] for r in rows if r[0]]
                        except Exception:
                            continue

                    if vals:
                        # Store as compact comma-separated string, max 250 chars
                        joined = ", ".join(vals)
                        result[col] = joined[:250]
        except Exception as e:
            print(f"⚠️ Could not compute column top values for {table_name}: {e}")
        return result

    @staticmethod
    def _compute_column_stats(
        table_name: str,
        columns: List[str],
        column_types: Dict[str, str],
        top_values: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Compute per-column statistics (null rate, unique count, min/max, top values)
        and format as text for the LLM metadata generation prompt.

        Uses pg_stats for zero-cost stats where available, with SQL fallbacks.

        Args:
            table_name: Name of the table in the vector schema
            columns: List of column names
            column_types: Dict of {column_name: sql_type}
            top_values: Optional pre-computed top values from _compute_column_top_values()

        Returns:
            Formatted string with column statistics for LLM context
        """
        _SKIP_COLS = {"geometry", "geom", "geom_25833", "wkb_geometry", "the_geom"}
        _ID_RE = re.compile(r"(^id$|_id$|^fid$|^gid$|^osm_id$|^ogc_fid$)", re.IGNORECASE)
        top_values = top_values or {}

        stats_lines = []
        try:
            from sqlalchemy import text as sa_text

            with db_manager.engine.connect() as conn:
                # Get row count for null % calculation
                row_count_row = conn.execute(
                    sa_text(f"SELECT COUNT(*) FROM vector.\"{table_name}\"")
                ).fetchone()
                total_rows = row_count_row[0] if row_count_row else 0
                if total_rows == 0:
                    return ""

                for col in columns[:20]:
                    if col.lower() in _SKIP_COLS:
                        continue
                    if _ID_RE.search(col):
                        continue

                    ctype = column_types.get(col, "").lower()
                    parts = [f"  {col} ({column_types.get(col, 'text')})"]

                    # Get null_frac and n_distinct from pg_stats (free)
                    try:
                        pg_row = conn.execute(sa_text(
                            "SELECT null_frac, n_distinct FROM pg_stats "
                            "WHERE schemaname='vector' AND tablename=:t AND attname=:c"
                        ), {"t": table_name, "c": col}).fetchone()
                        if pg_row:
                            null_pct = round(pg_row[0] * 100, 1) if pg_row[0] else 0
                            n_distinct = pg_row[1] if pg_row[1] else 0
                            # n_distinct > 0 = exact count, < 0 = fraction of rows
                            if n_distinct < 0:
                                unique_est = int(abs(n_distinct) * total_rows)
                            else:
                                unique_est = int(n_distinct)
                            parts.append(f"null: {null_pct}%")
                            parts.append(f"unique: ~{unique_est:,}")
                    except Exception:
                        pass

                    # Add min/max for numeric columns
                    if any(t in ctype for t in ("int", "float", "numeric", "double", "real")):
                        try:
                            minmax = conn.execute(sa_text(
                                f'SELECT MIN("{col}"), MAX("{col}") FROM vector."{table_name}" '
                                f'WHERE "{col}" IS NOT NULL'
                            )).fetchone()
                            if minmax and minmax[0] is not None:
                                parts.append(f"range: {minmax[0]}..{minmax[1]}")
                        except Exception:
                            pass

                    # Add top values if available
                    if col in top_values:
                        vals_str = top_values[col][:150]
                        parts.append(f"top values: [{vals_str}]")

                    stats_lines.append(" | ".join(parts))

        except Exception as e:
            print(f"⚠️ Could not compute column stats for {table_name}: {e}")
            return ""

        if stats_lines:
            return "\nColumn statistics:\n" + "\n".join(stats_lines)
        return ""

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

    # Columns that look like IDs — excluded from categorical detection
    _ID_PATTERN = re.compile(r"(^id$|_id$|^fid$|^gid$|^osm_id$|^ogc_fid$)", re.IGNORECASE)
    # Geometry-like column names to skip
    _GEOM_COLS = {"geometry", "geom", "geom_25833", "wkb_geometry", "the_geom"}

    @staticmethod
    def detect_categorical_columns(df) -> List[Dict[str, Any]]:
        """
        Detect categorical columns using a multi-signal approach:
        1. Type filter: only string/object and integer columns (skip float, datetime, geometry)
        2. Cardinality gate: unique/total < 5% OR unique <= 50
        3. Frequency coverage: top 10 values cover >= 70% of non-null rows

        Boolean columns always qualify. ID-like columns are excluded.

        For large DataFrames (>100k rows), samples 50k rows for estimation.

        Args:
            df: pandas/geopandas DataFrame

        Returns:
            List of dicts with column, unique_count, total_rows, top_values, coverage_pct
        """
        import pandas as pd

        total_rows = len(df)
        if total_rows == 0:
            return []

        # Sample for large DataFrames
        analysis_df = df.sample(n=50_000, random_state=42) if total_rows > 100_000 else df

        results = []

        for col in df.columns:
            # Skip geometry columns
            if col.lower() in AutoTableDiscovery._GEOM_COLS:
                continue

            # Skip ID-like columns
            if AutoTableDiscovery._ID_PATTERN.search(col):
                continue

            dtype = df[col].dtype

            # Boolean columns always qualify
            if pd.api.types.is_bool_dtype(dtype):
                non_null = analysis_df[col].dropna()
                unique_vals = sorted(str(v) for v in non_null.unique())
                results.append({
                    "column": col,
                    "unique_count": len(unique_vals),
                    "total_rows": total_rows,
                    "top_values": unique_vals,
                    "coverage_pct": 100.0,
                })
                continue

            # Type filter: only string/object and integer types
            if not (pd.api.types.is_string_dtype(dtype)
                    or pd.api.types.is_object_dtype(dtype)
                    or pd.api.types.is_integer_dtype(dtype)):
                continue

            non_null = analysis_df[col].dropna()
            if len(non_null) == 0:
                continue

            unique_count = non_null.nunique()

            # Cardinality gate: unique/total < 5% OR unique <= 50
            cardinality_ratio = unique_count / len(non_null) if len(non_null) > 0 else 1.0
            if not (cardinality_ratio < 0.05 or unique_count <= 50):
                continue

            # Frequency coverage: top 10 values must cover >= 70% of non-null rows
            value_counts = non_null.value_counts()
            top_n = min(10, len(value_counts))
            top_coverage = value_counts.iloc[:top_n].sum() / len(non_null) * 100

            if top_coverage < 70.0:
                continue

            # Collect all unique values (sorted, truncated strings)
            all_values = sorted(str(v)[:50] for v in non_null.unique())
            # Cap the values list at 50 entries for storage
            top_values = all_values[:50]

            results.append({
                "column": col,
                "unique_count": unique_count,
                "total_rows": total_rows,
                "top_values": top_values,
                "coverage_pct": round(top_coverage, 1),
            })

        return results

    @staticmethod
    def format_categorical_for_hint(categorical_columns: List[Dict[str, Any]]) -> str:
        """
        Format categorical column info as text suitable for appending to usage_hint.

        Args:
            categorical_columns: Output from detect_categorical_columns()

        Returns:
            Formatted string, or empty string if no categorical columns
        """
        if not categorical_columns:
            return ""

        parts = []
        for cat in categorical_columns:
            col = cat["column"]
            count = cat["unique_count"]
            coverage = cat["coverage_pct"]
            values = cat["top_values"]
            # Show up to 10 values in the hint text
            shown = ", ".join(values[:10])
            suffix = ", ..." if len(values) > 10 else ""
            parts.append(f"{col} ({count} values, {coverage}% coverage: {shown}{suffix})")

        return "Categorical columns: " + "; ".join(parts)

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
    def generate_rich_metadata_with_llm(
        table_name: str,
        structure: Dict[str, Any],
        categorical_columns: Optional[List[Dict[str, Any]]] = None,
        column_stats: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate rich structured metadata using DeepSeek LLM.

        Requests a JSON response with:
        - description: 1-2 sentences, what this table contains AND what analyses it enables
        - usage_hint: 3-5 sentences on HOW and WHEN to query it
        - key_columns: list of 3-6 most important non-geometry columns
        - related_tables: list of tables commonly used with this one
        - analysis_patterns: applicable tags

        Args:
            table_name: Name of the table
            structure: Table structure information
            categorical_columns: Optional pre-detected categorical columns from detect_categorical_columns()
            column_stats: Optional pre-computed column statistics text from _compute_column_stats()

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
            column_types = structure.get("column_types", {})
            geom_type = structure.get("geometry_type", "UNKNOWN")
            row_count = structure.get("row_count", 0)

            # Get sample values for richer context
            samples = AutoTableDiscovery.get_sample_values(table_name)
            samples_str = json.dumps(samples, default=str)[:1000] if samples else "none available"

            # Build categorical context for the LLM
            cat_context = ""
            if categorical_columns:
                cat_parts = []
                for cat in categorical_columns:
                    vals = ", ".join(cat["top_values"][:10])
                    cat_parts.append(f"  - {cat['column']}: {cat['unique_count']} unique values ({vals})")
                cat_context = "\nCategorical columns (use these for WHERE/filter guidance in usage_hint):\n" + "\n".join(cat_parts)

            # Add column stats if available
            stats_context = ""
            if column_stats:
                stats_context = column_stats

            # Build column list with types (helps LLM understand what columns contain)
            col_with_types = [
                f"{c} ({column_types.get(c, 'text')})" for c in columns[:20]
            ]

            prompt = f"""You are a PostGIS database expert and urban data analyst. Analyze this spatial database table — its structure, column statistics, and sample data — then return ONLY a JSON object.

Table name: {table_name}
Geometry type: {geom_type}
Row count: {row_count:,}
Columns: {', '.join(col_with_types)}
Sample rows: {samples_str}{cat_context}{stats_context}

Study the column statistics carefully — null rates, unique counts, value distributions, and top values reveal what this table actually contains and how it can be used. Use this evidence to write accurate, specific descriptions.

Return ONLY valid JSON (no markdown, no explanation) with exactly these keys:
{{
  "description": "Max 150 chars. What this table contains AND what decisions or analyses it enables. Focus on real-world use cases, not just technical content. Good: 'Berlin zoning plans (B-Pläne) defining legally permitted land uses per area — essential for site selection and development queries.' Bad: 'Berlin zoning plans with legal status and procedural details.'",
  "usage_hint": "3-5 sentences: (1) Primary filter columns with their key values from the statistics above. (2) WHEN to use this table — what types of user questions make it relevant (e.g., site selection, accessibility analysis, competition analysis). (3) Common JOINs with other spatial tables. (4) Any regulatory, legal, or classification significance of the data. Be specific — name columns and show real filter values from the stats.",
  "key_columns": ["col1", "col2", "col3"],
  "related_tables": ["other_table1", "other_table2"],
  "analysis_patterns": ["tag1", "tag2"]
}}

For analysis_patterns, pick applicable tags from: proximity_analysis, routing, coverage, demographics, environmental, planning, emergency, lighting, site_selection, zoning, land_use, business_location, regulatory

Respond with ONLY the JSON object."""

            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1000,
            }

            response = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
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
                # Enforce description length cap — LLMs often ignore the 150-char instruction
                if metadata.get("description"):
                    desc = metadata["description"].strip().rstrip(".")
                    if len(desc) > 180:
                        desc = desc[:180].rsplit(" ", 1)[0]
                    metadata["description"] = desc + "."
                return metadata
            else:
                print(f"Warning: LLM request failed ({response.status_code}), using structural generation")
                return fallback

        except Exception as e:
            print(f"Warning: LLM rich metadata generation failed for {table_name}: {e}")
            return fallback

    @staticmethod
    def _write_to_db(
        table_name: str,
        metadata_dict: Dict[str, Any],
        categorical_columns: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Upsert rich metadata into metadata.table_descriptions DB table.

        Handles the new columns (usage_hint, key_columns, related_tables,
        analysis_patterns, updated_at) gracefully if they don't exist yet.

        Args:
            table_name: Name of the table
            metadata_dict: Rich metadata dict from generate_rich_metadata_with_llm()
            categorical_columns: Optional categorical column info to append to usage_hint
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

        # Detect categorical columns from live DB data
        categorical = []
        try:
            import pandas as pd
            from sqlalchemy import text as sa_text
            with db_manager.engine.connect() as conn:
                df = pd.read_sql(sa_text(f'SELECT * FROM vector."{table_name}" LIMIT 50000'), conn)
            categorical = AutoTableDiscovery.detect_categorical_columns(df)
        except Exception as e:
            print(f"  ⚠️ Categorical detection failed for {table_name}: {e}")

        # Compute column top values BEFORE the LLM call so the LLM can see them
        print(f"  📊 Computing column statistics...")
        col_top_vals = {}
        try:
            col_top_vals = AutoTableDiscovery._compute_column_top_values(
                table_name,
                structure.get("columns", []),
                structure.get("column_types", {}),
            )
        except Exception as e:
            print(f"  ⚠️ Column top-value computation failed for {table_name}: {e}")

        # Compute per-column stats (null rates, unique counts, min/max, top values)
        col_stats_text = ""
        try:
            col_stats_text = AutoTableDiscovery._compute_column_stats(
                table_name,
                structure.get("columns", []),
                structure.get("column_types", {}),
                top_values=col_top_vals,
            )
        except Exception as e:
            print(f"  ⚠️ Column stats computation failed for {table_name}: {e}")

        print(f"  🧠 Generating rich metadata with AI...")
        metadata = AutoTableDiscovery.generate_rich_metadata_with_llm(
            table_name, structure,
            categorical_columns=categorical,
            column_stats=col_stats_text,
        )
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
        AutoTableDiscovery._write_to_db(table_name, metadata, categorical_columns=categorical)

        # Store top column values in DB for zero-cost LLM context at query time
        if col_top_vals:
            try:
                from sqlalchemy import text as sa_text
                with db_manager.engine.begin() as conn:
                    for col_name, vals_str in col_top_vals.items():
                        conn.execute(sa_text("""
                            INSERT INTO metadata.column_descriptions
                                (table_name, column_name, example_value, updated_at)
                            VALUES (:t, :c, :v, NOW())
                            ON CONFLICT (table_name, column_name) DO UPDATE SET
                                example_value = EXCLUDED.example_value,
                                updated_at = NOW()
                        """), {"t": table_name, "c": col_name, "v": vals_str})
                print(f"  📊 Stored top values for {len(col_top_vals)} columns in {table_name}")
            except Exception as e:
                print(f"  ⚠️ Column top-value storage failed for {table_name}: {e}")

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

            # Compute column stats before LLM call
            col_top_vals = AutoTableDiscovery._compute_column_top_values(
                table_name,
                structure.get("columns", []),
                structure.get("column_types", {}),
            )
            col_stats_text = AutoTableDiscovery._compute_column_stats(
                table_name,
                structure.get("columns", []),
                structure.get("column_types", {}),
                top_values=col_top_vals,
            )

            print(f"  🧠 Generating rich metadata with AI...")
            metadata = AutoTableDiscovery.generate_rich_metadata_with_llm(
                table_name, structure, column_stats=col_stats_text,
            )
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
