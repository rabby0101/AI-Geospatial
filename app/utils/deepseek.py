import os
import json
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from app.models.query_model import OperationPlan, GeospatialOperation
from app.utils.prompts import SYSTEM_PROMPT

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Use deepseek-chat for cleaner JSON responses (faster and more reliable parsing)
# DO NOT use deepseek-reasoner as it produces verbose thinking output that breaks JSON parsing
DEEPSEEK_MODEL = "deepseek-chat"  # Force chat model for reliable JSON output
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Ollama (Local LLM) Configuration
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_MODEL_SMALL = os.getenv("OLLAMA_MODEL_SMALL", "qwen3.5:4b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

# Simple in-memory cache (max 100 entries)
_query_cache: Dict[str, str] = {}
_MAX_CACHE_SIZE = 100


# System prompt is imported from prompts.py (single source of truth)


def _get_location_filter_column(location_name: str) -> str:
    """
    Determine if a location is a main district (Bezirk) or subdivision (Ortsteil).
    Returns the appropriate column name to use in SQL WHERE clause.

    Args:
        location_name: Name of the location (e.g., 'Mitte', 'Kladow', 'Spandau')

    Returns:
        'bezirk' if it's a main district, 'name' if it's a subdivision
    """
    # Main districts (Bezirke) - 12 total
    main_districts = {
        'mitte', 'friedrichshain-kreuzberg', 'pankow', 'charlottenburg-wilmersdorf',
        'spandau', 'steglitz-zehlendorf', 'tempelhof-schöneberg', 'neukölln',
        'treptow-köpenick', 'marzahn-hellersdorf', 'lichtenberg', 'reinickendorf'
    }

    location_lower = location_name.lower().strip()
    if location_lower in main_districts:
        return 'bezirk'
    else:
        # It's likely a subdivision (Ortsteil)
        return 'name'


def _hash_selected_feature(selected_feature: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Create a hash of selected feature (excluding the large WKT geometry).
    This prevents cache keys from becoming too large.
    """
    if not selected_feature:
        return None

    import hashlib
    # Only hash the feature name and type, not the massive geometry
    feature_summary = {
        'name': selected_feature.get('name'),
        'geometry_type': selected_feature.get('geometry_type')
    }
    feature_str = json.dumps(feature_summary, sort_keys=True)
    return hashlib.md5(feature_str.encode()).hexdigest()


def _generate_cache_key(prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Generate a unique cache key for a query."""
    cache_str = prompt.lower().strip()
    if context:
        cache_str += json.dumps(context, sort_keys=True)
    return cache_str


def _select_tables_with_llm(user_query: str, tables_data: list) -> list:
    """
    Pass 1: Ask the LLM which tables are needed for this query.
    Returns a filtered list of table names. Falls back to all on any failure.
    """
    if not tables_data or not user_query.strip():
        return [t["table"] for t in tables_data]

    all_table_names = {t["table"] for t in tables_data}

    # Build compact catalog — one line per table, no full column lists
    catalog_lines = []
    for t in sorted(tables_data, key=lambda x: x["table"]):
        name = t["table"]
        desc = (t.get("description") or "")[:100]
        rows = t.get("row_count", 0)
        geom = t.get("geometry", "NONE")
        # First 4 non-geometry column names as key hints
        skip = {"geometry", "geom", "geom_25833"}
        cols = []
        for c in t.get("columns", []):
            col_name = c.get("name", "") if isinstance(c, dict) else c
            if col_name not in skip:
                cols.append(col_name)
            if len(cols) == 4:
                break
        key_str = ", ".join(cols) if cols else "—"
        catalog_lines.append(f"{name} ({rows:,} rows, {geom}) — {desc} | key: {key_str}")

    catalog_text = "\n".join(catalog_lines)

    print(f"\n{'='*70}")
    print(f"[Pass1] USER QUERY: {user_query}")
    print(f"[Pass1] COMPACT CATALOG ({len(catalog_text)} chars, {len(catalog_lines)} tables):")
    print(catalog_text)
    print(f"{'='*70}\n")

    selection_prompt = (
        "You are a PostGIS database expert and urban planning analyst. Given this table catalog "
        "and a user question, determine which tables are needed to answer comprehensively.\n\n"
        "Think about:\n"
        "- Direct data: tables containing the features mentioned in the question\n"
        "- Regulatory/zoning: for business location or development queries, include zoning/land-use plan tables\n"
        "- Context: boundary tables for district filtering, demographic data for demand analysis\n"
        "- Competition: tables with similar existing business types for competitive analysis\n\n"
        "Return ONLY a JSON array of 3-12 table names. No explanation, no markdown, no code fences.\n\n"
        f"TABLE CATALOG:\n{catalog_text}\n\n"
        f"USER QUESTION: {user_query}"
    )

    try:
        selected_names = None

        # Try Gemini first
        if GEMINI_API_KEY and selected_names is None:
            try:
                payload = {
                    "contents": [{"parts": [{"text": selection_prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256},
                }
                resp = requests.post(
                    f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                    json=payload,
                    timeout=40,
                )
                if resp.status_code == 200:
                    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if raw.startswith("```"):
                        raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
                    selected_names = json.loads(raw)
                    print(f"[Pass1] RAW LLM RESPONSE (Gemini): {raw}")
            except Exception as gemini_err:
                print(f"[Pass1] Gemini failed ({gemini_err}) — trying DeepSeek fallback")

        # Fall back to DeepSeek if Gemini unavailable or failed
        if DEEPSEEK_API_KEY and selected_names is None:
            try:
                payload = {
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": selection_prompt}],
                    "temperature": 0.1,
                    "max_tokens": 256,
                }
                resp = requests.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=40,
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"].strip()
                    if raw.startswith("```"):
                        raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
                    selected_names = json.loads(raw)
                    print(f"[Pass1] RAW LLM RESPONSE (DeepSeek): {raw}")
            except Exception as ds_err:
                print(f"[Pass1] DeepSeek also failed ({ds_err})")

        if selected_names and isinstance(selected_names, list):
            valid = [n for n in selected_names if n in all_table_names]
            if valid:
                print(f"[SchemaContext] Pass1 selected {len(valid)}/{len(tables_data)} tables: {valid}")
                return valid

    except Exception as e:
        print(f"⚠️ Pass1 table selection failed ({e}) — falling back to all tables")

    return [t["table"] for t in tables_data]


def _get_database_schema_for_llm(user_query: str = "", _return_selected_tables: bool = False):
    """
    Get the LIVE database schema from PostGIS.

    If user_query is provided, runs Pass 1: asks the LLM to select only the
    relevant tables, then returns full detail for those tables only (Pass 2).
    Columns are capped at 20 per table to prevent context explosion from
    Overpass-imported tables with 100–250 OSM tag columns.

    Args:
        user_query: Natural language question (triggers Phase 1 table selection)
        _return_selected_tables: If True, returns (schema_text, selected_names_list)
            instead of just schema_text. Used internally by parse_geospatial_query()
            to avoid a second schema fetch for Phase 3 query planning.

    Returns:
        str: schema text (default)
        tuple[str, list]: (schema_text, selected_table_names) when _return_selected_tables=True
    """
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text

        # Fetch live schema from database (vector schema)
        tables_data = db_manager.get_schema_with_descriptions()

        if not tables_data:
            tables_data = []

        # Pass 1: select only relevant tables when a user query is available
        selected_names_list = [t["table"] for t in tables_data]
        if user_query.strip():
            selected_names_list = _select_tables_with_llm(user_query, tables_data)
            selected_names = set(selected_names_list)
            tables_data = [t for t in tables_data if t["table"] in selected_names]

        # Format for LLM
        schema_text = "**Available Tables in Database:**\n\n"

        # Add vector schema tables
        schema_text += "**SCHEMA: vector (main spatial data)**\n"
        schema_text += "-" * 60 + "\n"

        # Dynamic column cap: max actual columns among selected tables, hard-capped at 60.
        # 60 covers all non-OSM tables (max ~32 cols) and key regulatory tables like
        # wfs_bplan_b_bp_fs (32 cols). The 60 ceiling prevents Overpass-imported OSM
        # tables (up to 251 cols) from flooding the LLM context.
        col_cap = min(
            max((len(t.get("columns", [])) for t in tables_data), default=20),
            60
        )
        print(f"[Pass2] Column cap: {col_cap} (dynamic: max cols of selected tables, ceiling 60)")

        for table_info in sorted(tables_data, key=lambda x: x["table"]):
            table_name = table_info["table"]
            description = table_info["description"]
            usage_hint = table_info.get("usage_hint", "")
            row_count = table_info.get("row_count", 0)
            geometry = table_info.get("geometry", "NONE")

            # key_columns always appear first so they survive the cap regardless of ordinal position
            all_cols = table_info.get("columns", [])
            key_col_names = set(table_info.get("key_columns", []))
            priority_cols = [c for c in all_cols
                             if (c.get("name") if isinstance(c, dict) else c) in key_col_names]
            other_cols = [c for c in all_cols
                          if (c.get("name") if isinstance(c, dict) else c) not in key_col_names]
            columns = priority_cols + other_cols[:max(0, col_cap - len(priority_cols))]

            # Format table entry
            schema_text += f"**{table_name}**\n"
            schema_text += f"  Description: {description}\n"
            if usage_hint:
                schema_text += f"  Usage: {usage_hint}\n"
            if geometry == "NONE":
                schema_text += f"  Records: {row_count} | Geometry: NONE ⚠️ NO GEOMETRY COLUMNS — do NOT use geometry/geom_25833/ST_* on this table\n"
            else:
                schema_text += f"  Records: {row_count} | Geometry: {geometry}\n"
            schema_text += "  Columns:\n"

            # Format each column with its metadata
            for col in columns:
                if isinstance(col, dict):
                    col_name = col.get("name", "")
                    col_type = col.get("type", "")
                    col_desc = col.get("description", "")
                    col_examples = col.get("example_values", "")

                    line = f"    - {col_name} ({col_type})"
                    if col_desc:
                        line += f": {col_desc}"
                    if col_examples:
                        # If example_value looks like a comma-separated list of actual values
                        # (stored by _compute_column_top_values), display first 8 for LLM context
                        ex_str = str(col_examples).strip()
                        if "," in ex_str and len(ex_str) > 30:
                            vals = [v.strip() for v in ex_str.split(",")][:8]
                            line += f" [values: {' | '.join(vals)}]"
                        else:
                            line += f" e.g., {ex_str}"
                    schema_text += line + "\n"
                else:
                    # Fallback if somehow just a string
                    schema_text += f"    - {col}\n"

            schema_text += "\n"

        # Check for temporary selected feature layers
        try:
            temp_tables = []
            with db_manager.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'temp' AND table_name LIKE 'temp_selected_%'
                    ORDER BY table_name
                """))
                temp_tables = [row[0] for row in result]

            if temp_tables:
                schema_text += "\n**SCHEMA: temp (selected feature layers)**\n"
                schema_text += "-" * 60 + "\n"

                for temp_table in temp_tables:
                    # Get info about temp table using a fresh connection
                    try:
                        with db_manager.engine.connect() as conn2:
                            result = conn2.execute(text(f"""
                                SELECT COUNT(*) as count,
                                       ST_GeometryType((array_agg(geometry))[1]) as geom_type
                                FROM temp.{temp_table}
                            """))
                            row = result.first()
                            count = row[0] if row else 0
                            geom_type = row[1] if row else "Unknown"

                            schema_text += f"**{temp_table}**\n"
                            schema_text += f"  Description: Temporary layer from selected feature\n"
                            schema_text += f"  Records: {count} | Geometry: {geom_type}\n"
                            schema_text += f"  Columns: id, geometry\n\n"
                    except Exception as table_error:
                        print(f"⚠️ Could not get info for temp table {temp_table}: {table_error}")
                        # Still list the temp table even if we can't get info
                        schema_text += f"**{temp_table}**\n"
                        schema_text += f"  Description: Temporary layer from selected feature\n"
                        schema_text += f"  Columns: id, geometry\n\n"
        except Exception as e:
            print(f"⚠️ Note: Could not query temp schema: {e}")

        print(f"\n[Pass2] SCHEMA TEXT: {len(schema_text)} chars, {len(schema_text.splitlines())} lines")
        print(f"[Pass2] SCHEMA PREVIEW (first 3000 chars):\n{schema_text[:3000]}")
        print(f"[Pass2] SCHEMA TAIL (last 500 chars):\n...{schema_text[-500:]}\n")
        if _return_selected_tables:
            return schema_text, selected_names_list
        return schema_text

    except Exception as e:
        print(f"⚠️ Error getting database schema: {e}")
        if _return_selected_tables:
            return "Unable to fetch live schema from database", []
        return "Unable to fetch live schema from database"


def _should_run_query_planning(selected_tables: list, schema_text: str) -> bool:
    """
    Decide whether Phase 3 (query planning LLM call) is needed.

    Runs for complex queries: 2+ tables selected, or the schema contains rich
    column value hints (indicating regulatory/complex data). Skips for simple
    single-table queries to keep latency low (2 LLM calls instead of 3).
    """
    if len(selected_tables) >= 2:
        return True
    # If schema includes many [values: ...] hints, the data is complex enough to plan
    if schema_text.count("[values:") >= 2:
        return True
    return False


def _plan_query_with_llm(user_query: str, schema_text: str) -> Dict[str, Any]:
    """
    Phase 3: Given the rich schema (with real column values), ask the LLM to produce
    a validated query plan BEFORE writing SQL.

    The plan includes confirmed tables and exact filter values derived from actual DB data,
    preventing hallucinated WHERE clauses. Injected into the Phase 4 system prompt.

    Returns dict: {confirmed_tables, filter_plan: {table: {filters, notes}}, reasoning}
    Falls back to {} on any error (Phase 4 then runs without a plan — graceful degradation).
    """
    plan_prompt = f"""You are a PostGIS SQL expert. Before writing any SQL, analyze the table schemas
and their REAL column values, then produce a concise query plan.

USER QUESTION:
{user_query}

AVAILABLE TABLES WITH REAL DATA:
{schema_text}

Return ONLY a JSON object (no markdown, no explanation):
{{
  "confirmed_tables": ["only tables truly needed to answer the question"],
  "filter_plan": {{
    "<table_name>": {{
      "key_columns": ["most relevant columns for this query"],
      "filters": [
        {{"column": "<col>", "operator": "= | ILIKE | IN | > | <", "value": "<exact value from the data shown above>"}}
      ],
      "notes": "<special handling if needed, e.g. ST_MakeValid, geometry column to use, join key>"
    }}
  }},
  "reasoning": "One sentence: why these tables and filters answer the question"
}}

CRITICAL: Use ONLY filter values that appear in the [values: ...] lists shown above.
Never invent column values — if unsure, omit the filter."""

    # Reuse Gemini first, DeepSeek as fallback (same pattern as Phase 1)
    raw = None
    if GEMINI_API_KEY:
        try:
            payload = {
                "contents": [{"parts": [{"text": plan_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800},
            }
            resp = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload,
                timeout=40,
            )
            if resp.status_code == 200:
                parts = resp.json()["candidates"][0]["content"]["parts"]
                for part in reversed(parts):
                    if "text" in part and "thought" not in part:
                        raw = part["text"].strip()
                        break
                if raw is None:
                    raw = parts[-1].get("text", "").strip()
        except Exception as e:
            print(f"[Phase3] Gemini failed: {e}")

    if raw is None and DEEPSEEK_API_KEY:
        try:
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": plan_prompt}],
                "temperature": 0.1,
                "max_tokens": 800,
            }
            resp = requests.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=40,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[Phase3] DeepSeek failed: {e}")

    if not raw:
        print("[Phase3] Skipped — no LLM available")
        return {}

    # Clean and parse JSON
    try:
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        plan = json.loads(raw)
        print(f"[Phase3] Query plan: tables={plan.get('confirmed_tables')} reasoning={plan.get('reasoning','')}")
        return plan
    except Exception as e:
        print(f"[Phase3] JSON parse failed ({e}) — proceeding without plan")
        return {}


def _build_dynamic_system_prompt(user_query: str, precomputed_schema: str = None, query_plan: Dict[str, Any] = None, business_profile_section: str = "") -> str:
    """
    Build a system prompt with LIVE table descriptions from the database.
    Enhanced with ontology awareness for semantic query understanding.

    Single source of truth: descriptions are stored in vector.table_metadata
    Ontology provides analytical purposes and dataset relationships.

    Args:
        user_query: The user's natural language question

    Returns:
        Complete system prompt with live database schema information
    """
    try:
        # Get the base prompt (core instructions, rules, examples)
        base_prompt = SYSTEM_PROMPT

        # Get LIVE schema — use pre-fetched schema if provided (avoids double Phase 1 LLM call)
        schema_section = precomputed_schema if precomputed_schema else _get_database_schema_for_llm(user_query)

        # Get ONTOLOGY context for semantic enhancement
        ontology_section = _get_ontology_context_for_llm(user_query)

        # Combine into final prompt
        final_prompt = base_prompt + "\n\n" + schema_section

        # Add ontology section if relevant
        if ontology_section:
            final_prompt += "\n" + ontology_section

        # Inject business profile when available (Phase 0 data)
        if business_profile_section:
            final_prompt += business_profile_section

        # Inject Phase 3 query plan when available (validated filters from real data)
        if query_plan and query_plan.get("filter_plan"):
            plan_lines = ["\n\n## CONFIRMED QUERY PLAN (validated against real DB data — follow these filters exactly)"]
            confirmed = query_plan.get("confirmed_tables", [])
            if confirmed:
                plan_lines.append(f"Confirmed tables: {confirmed}")
            for tbl, info in query_plan["filter_plan"].items():
                plan_lines.append(f"\n{tbl}:")
                for f in info.get("filters", []):
                    plan_lines.append(f"  WHERE {f.get('column')} {f.get('operator')} {f.get('value')}")
                if info.get("notes"):
                    plan_lines.append(f"  Note: {info['notes']}")
            reasoning = query_plan.get("reasoning", "")
            if reasoning:
                plan_lines.append(f"\nReasoning: {reasoning}")
            final_prompt += "\n".join(plan_lines)

        print(f"\n[FinalPrompt] Total: {len(final_prompt)} chars (~{len(final_prompt)//4} tokens)")
        print(f"[FinalPrompt] Breakdown — base: {len(base_prompt)} | schema: {len(schema_section)} | ontology: {len(ontology_section)} | plan: {len(str(query_plan or {}))}\n")
        return final_prompt

    except Exception as e:
        print(f"⚠️ Error building dynamic prompt: {e}")
        # Gracefully fall back to static prompt on any error
        return SYSTEM_PROMPT


def _get_ontology_context_for_llm(user_query: str) -> str:
    """
    Get relevant ontology context based on user query for enhanced semantic understanding.
    
    Detects analytical intent from keywords and returns relevant dataset recommendations
    from the knowledge graph.
    
    Args:
        user_query: The user's natural language question
        
    Returns:
        Formatted ontology context string, or empty string if not relevant
    """
    try:
        from app.utils.semantic_layer import create_semantic_layer
        
        query_lower = user_query.lower()
        
        # Define keyword-to-purpose mappings for semantic enhancement
        purpose_keywords = {
            'AccessibilityAnalysis': [
                'accessibility', 'accessible', 'wheelchair', 'disability', 'disabled',
                'mobility', 'barrier-free', 'reachable', 'reach', 'access to',
                'healthcare access', 'service access', 'public transport access',
                'walking distance', 'how far', 'nearest', 'closest'
            ],
            'EmergencyPlanning': [
                'emergency', 'evacuation', 'disaster', 'fire station', 'fire fighting',
                'police', 'ambulance', 'hospital', 'emergency services', 'safety',
                'response time', 'crisis', 'rescue', 'first responder'
            ],
            'UrbanPlanning': [
                'urban planning', 'city planning', 'zoning', 'land use', 'landuse', 'development',
                'infrastructure', 'housing', 'residential', 'commercial', 'mixed use',
                'density', 'urban growth', 'smart city', 'sustainable', 'best area',
                'best district', 'ideal location', 'suitable for', 'open a', 'build a'
            ],
            'EnvironmentalMonitoring': [
                'environment', 'environmental', 'pollution', 'air quality', 'water quality',
                'vegetation', 'ndvi', 'green', 'greenery', 'trees', 'forest',
                'climate', 'carbon', 'sustainability', 'ecological', 'biodiversity',
                'nature', 'natural', 'green space', 'parks'
            ],
            'ChangeDetection': [
                'change', 'changes', 'temporal', 'time series', 'over time',
                'comparison', 'difference', 'evolution', 'growth', 'decline',
                'before and after', 'trend', 'historical'
            ],
            'ProximityAnalysis': [
                'near', 'nearby', 'close to', 'within', 'distance', 'proximity',
                'around', 'surrounding', 'neighborhood', 'radius', 'buffer',
                'walking distance', 'km from', 'meters from', 'minutes from'
            ]
        }
        
        # Detect which purposes are relevant for this query
        detected_purposes = []
        for purpose, keywords in purpose_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_purposes.append(purpose)
        
        if not detected_purposes:
            return ""  # No semantic enhancement needed
        
        # Get the semantic layer
        semantic_layer = create_semantic_layer()
        
        # Build ontology context section
        context_lines = [
            "\n**🧠 SEMANTIC CONTEXT (from Knowledge Graph):**",
            "Based on the query intent, these datasets are semantically relevant:\n"
        ]
        
        all_relevant_datasets = set()
        
        for purpose in detected_purposes:
            datasets = semantic_layer.get_datasets_by_purpose(purpose)
            if datasets:
                # Format purpose name nicely
                purpose_name = purpose.replace('Analysis', ' Analysis').replace('Planning', ' Planning').replace('Monitoring', ' Monitoring').replace('Detection', ' Detection')
                context_lines.append(f"**For {purpose_name}:**")
                
                for ds in datasets[:5]:  # Limit to top 5 per purpose
                    title = ds.get('title', 'Unknown')
                    table = ds.get('table', '')
                    
                    # Extract table name from URI if present
                    if not table and 'dataset' in ds:
                        dataset_uri = ds.get('dataset', '')
                        if '#' in dataset_uri:
                            table = dataset_uri.split('#')[-1]
                    
                    if table:
                        # Convert ontology ID to actual table name
                        table_name = _ontology_id_to_table_name(table)
                        if table_name:
                            all_relevant_datasets.add(table_name)
                            context_lines.append(f"  - {title} → table: `vector.{table_name}`")
                        else:
                            context_lines.append(f"  - {title}")
                    else:
                        context_lines.append(f"  - {title}")
                
                context_lines.append("")
        
        # Add semantic recommendation
        if all_relevant_datasets:
            tables_list = ', '.join([f"vector.{t}" for t in sorted(all_relevant_datasets)])
            context_lines.append(f"**Recommended tables for this query:** {tables_list}")
            context_lines.append("\nConsider using these tables in your SQL query based on their semantic relevance.")
        
        return '\n'.join(context_lines)
        
    except ImportError:
        print("⚠️ Semantic layer not available for ontology context")
        return ""
    except Exception as e:
        print(f"⚠️ Error getting ontology context: {e}")
        return ""


def _ontology_id_to_table_name(ontology_id: str) -> str:
    """
    Convert an ontology dataset ID to the actual PostGIS table name.
    
    Args:
        ontology_id: The ID from the ontology (e.g., 'osm_hospitals', 'berlin_ndvi_2024')
        
    Returns:
        The actual table name without schema prefix, or empty string if unknown
    """
    # Direct mapping for known ontology IDs to table names
    # These match the instances defined in geo_ontology.ttl
    id_to_table = {
        'osm_hospitals': 'osm_hospitals',
        'osm_pharmacies': 'osm_pharmacies',
        'osm_doctors': 'osm_doctors',
        'osm_parks': 'osm_parks',
        'osm_fire_stations': 'osm_fire_stations',
        'osm_police_stations': 'osm_police_stations',
        'osm_transport_stops': 'osm_transport_stops',
        'osm_kindergartens': 'osm_kindergartens',
        'osm_forests': 'osm_forests',
        'osm_water_bodies': 'osm_water_bodies',
        'berlin_districts': 'berlin_districts',
        'berlin_ndvi_2018': None,  # Raster - no table
        'berlin_ndvi_2024': None,  # Raster - no table
        'berlin_ndvi_change': None,  # Raster - no table
    }
    
    return id_to_table.get(ontology_id, ontology_id if ontology_id.startswith('osm_') else '')


def query_deepseek(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, drawn_geometry: Dict[str, Any] = None, query_plan: Dict[str, Any] = None, precomputed_schema: str = None, business_profile_section: str = "") -> Dict[str, str]:
    """
    Query DeepSeek API with a prompt, using simple in-memory cache.
    Dynamically builds prompts with only relevant tables for the query.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster') to guide LLM response format
        selected_feature: Optional selected feature from map for context-aware queries
        drawn_geometry: Optional geometry drawn by user (GeoJSON format) - used as spatial context

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

    # Check cache first (include user_location, query_type, drawn_geometry, and session_id in cache key)
    # session_id is included because queries depend on temp.temp_selected_{session_id} tables
    session_id = context.get("session_id") if context else None
    cache_context = {
        **(context or {}), 
        **({"user_location": user_location} if user_location else {}), 
        **({"query_type": query_type} if query_type else {}), 
        **({"drawn_geometry": drawn_geometry} if drawn_geometry else {})
    }
    cache_key = _generate_cache_key(prompt, cache_context if cache_context else None)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached response")
        return _query_cache[cache_key]  # Returns dict with content, system_prompt, user_prompt

    # Build dynamic system prompt — pass precomputed schema, query plan, and business profile
    system_prompt = _build_dynamic_system_prompt(
        prompt,
        precomputed_schema=precomputed_schema,
        query_plan=query_plan,
        business_profile_section=business_profile_section,
    )

    # Build the full prompt with context and user_location if provided
    full_prompt = prompt

    # Add query type hint to prompt if specified
    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    # Add user location to prompt if available
    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    # Add drawn geometry to prompt if available - provides spatial context for queries
    if drawn_geometry:
        geometry_type = drawn_geometry.get('type', 'Unknown')
        coordinates_str = json.dumps(drawn_geometry.get('coordinates', []))[:200]  # Truncate long coordinate lists
        full_prompt = f"{full_prompt}\n\ndrawn_geometry: User has drawn a {geometry_type} on the map. Use this as spatial context for queries mentioning 'here', 'this area', 'drawn area', or location references. Geometry: {coordinates_str}..."

    # Add additional context if provided
    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Note: selected_feature is now handled via temp database layers
    # The schema automatically includes temp_selected_* tables that the LLM can query

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0,  # Zero temperature for deterministic SQL generation
        "max_tokens": 4000  # Sufficient for complex multi-criteria SQL with window functions and LATERAL joins
    }

    try:
        print(f"🧠 Querying DeepSeek API ({DEEPSEEK_MODEL})...")
        print("\n" + "="*80)
        print("📤 DEEPSEEK SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 DEEPSEEK USER PROMPT:")
        print("="*80)
        print(full_prompt)
        print("="*80 + "\n")
        response = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60  # Increased for selected features with large geometries
        )
        response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Create response dict with all three components
        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        # Cache the response (limit cache size)
        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()  # Simple cache eviction
        _query_cache[cache_key] = response_dict

        print(f"✅ DeepSeek response received ({len(content)} chars)")
        return response_dict

    except requests.exceptions.Timeout:
        raise Exception("DeepSeek API timeout. Please try a simpler query.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"DeepSeek API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from DeepSeek: {str(e)}")


def query_gemini(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, drawn_geometry: Dict[str, Any] = None, query_plan: Dict[str, Any] = None, precomputed_schema: str = None) -> Dict[str, str]:
    """
    Query Google Gemini API with a prompt, using simple in-memory cache.
    Uses the same dynamic prompt building as DeepSeek for consistency.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster')
        selected_feature: Optional selected feature from map
        drawn_geometry: Optional geometry drawn by user (GeoJSON format)

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Get a free key at https://aistudio.google.com/apikey")

    # Check cache first
    session_id = context.get("session_id") if context else None
    cache_context = {
        **(context or {}),
        **({  "user_location": user_location} if user_location else {}),
        **({"query_type": query_type} if query_type else {}),
        **({"drawn_geometry": drawn_geometry} if drawn_geometry else {}),
        "provider": "gemini"  # Separate cache namespace from DeepSeek
    }
    cache_key = _generate_cache_key(prompt, cache_context if cache_context else None)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached Gemini response")
        return _query_cache[cache_key]

    # Build dynamic system prompt — pass precomputed schema and query plan if available
    system_prompt = _build_dynamic_system_prompt(prompt, precomputed_schema=precomputed_schema, query_plan=query_plan)

    # Build the full prompt with context and user_location
    full_prompt = prompt

    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    if drawn_geometry:
        geometry_type = drawn_geometry.get('type', 'Unknown')
        coordinates_str = json.dumps(drawn_geometry.get('coordinates', []))[:200]
        full_prompt = f"{full_prompt}\n\ndrawn_geometry: User has drawn a {geometry_type} on the map. Use this as spatial context for queries mentioning 'here', 'this area', 'drawn area', or location references. Geometry: {coordinates_str}..."

    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Gemini API payload format
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": full_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 65536,
            "thinkingConfig": {
                "thinkingBudget": 2048
            }
        }
    }

    try:
        print(f"✨ Querying Gemini API ({GEMINI_MODEL})...")
        print("\n" + "="*80)
        print("📤 GEMINI SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 GEMINI USER PROMPT:")
        print("="*80)
        print(full_prompt)
        print("="*80 + "\n")

        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        response.raise_for_status()

        result = response.json()

        # Gemini 2.5 Flash returns multiple parts: a "thought" part (reasoning) + the actual text
        # We need to find the actual text part, not the thinking
        parts = result["candidates"][0]["content"]["parts"]
        content = None
        for part in reversed(parts):  # Last text part is the actual response
            if "text" in part and "thought" not in part:
                content = part["text"]
                break
        if content is None:
            # Fallback: just get any text part
            for part in parts:
                if "text" in part:
                    content = part["text"]
                    break
        if content is None:
            raise Exception("No text content found in Gemini response")

        print(f"✅ Gemini response received ({len(content)} chars)")
        print(f"📝 Gemini raw response (first 500 chars): {content[:500]}")

        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        # Cache the response
        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()
        _query_cache[cache_key] = response_dict

        print(f"✅ Gemini response cached")
        return response_dict

    except requests.exceptions.Timeout:
        raise Exception("Gemini API timeout. Please try a simpler query.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Gemini API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from Gemini: {str(e)}")


def query_ollama(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, drawn_geometry: Dict[str, Any] = None, model_override: str = None, num_ctx: int = 100000, num_predict: int = 2048, disable_thinking: bool = False) -> Dict[str, str]:
    """
    Query local Ollama API with a prompt, using simple in-memory cache.
    Uses the same dynamic prompt building as DeepSeek/Gemini for consistency.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats')
        selected_feature: Optional selected feature from map
        drawn_geometry: Optional geometry drawn by user (GeoJSON format)

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    # Check cache first
    cache_context = {
        **(context or {}),
        **({"user_location": user_location} if user_location else {}),
        **({"query_type": query_type} if query_type else {}),
        **({"drawn_geometry": drawn_geometry} if drawn_geometry else {}),
        "provider": "ollama"
    }
    cache_key = _generate_cache_key(prompt, cache_context)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached Ollama response")
        return _query_cache[cache_key]

    # Build dynamic system prompt with relevant tables
    system_prompt = _build_dynamic_system_prompt(prompt)

    # Build the full prompt
    full_prompt = prompt

    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    if drawn_geometry:
        geometry_type = drawn_geometry.get('type', 'Unknown')
        coordinates_str = json.dumps(drawn_geometry.get('coordinates', []))[:200]
        full_prompt = f"{full_prompt}\n\ndrawn_geometry: User has drawn a {geometry_type} on the map. Use this as spatial context for queries mentioning 'here', 'this area', 'drawn area', or location references. Geometry: {coordinates_str}..."

    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Append a hard reminder at the end of the user prompt — small local models
    # often ignore long system prompts; this reinforces the JSON-only contract.
    base_reminder = "\n\n[IMPORTANT] Output ONLY the JSON object. Start with { and end with }. No thinking tags, no explanation, no markdown."
    # Extra constraint for tiny models: they struggle with multi-operation arrays
    # and produce malformed JSON when generating multiple operations.
    small_model_reminder = " Use EXACTLY ONE operation in the operations array. Keep the JSON short and valid."
    enforced_prompt = full_prompt + base_reminder + (small_model_reminder if model_override else "")

    model = model_override or OLLAMA_MODEL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enforced_prompt}
        ],
        # think: True (default) — Qwen3 9b needs its reasoning chain to follow the
        # complex geospatial system prompt. Thinking goes into result["message"]["thinking"]
        # (a separate field), NOT into result["message"]["content"], so the JSON we
        # extract is always clean.
        # For tiny models (0.8b): thinking consumes all num_predict tokens and
        # leaves content empty. Disable thinking so the model writes JSON directly.
        "think": not disable_thinking,
        "temperature": 0,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict
        }
    }

    try:
        print(f"🦙 Querying Ollama ({model})...")
        print("\n" + "="*80)
        print("📤 OLLAMA SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 OLLAMA USER PROMPT:")
        print("="*80)
        print(enforced_prompt)
        print("="*80 + "\n")

        response = requests.post(
            f"{OLLAMA_API_URL}/api/chat",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()

        result = response.json()
        raw = result["message"]["content"]

        # Strip <think>...</think> blocks that Qwen3 may embed in content
        # (older Ollama versions embed thinking inline; newer put it in result["message"]["thinking"])
        import re as _re
        content = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()

        print(f"✅ Ollama response received ({len(content)} chars)")
        print(f"📝 Ollama raw response (first 500 chars): {content[:500]}")

        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()
        _query_cache[cache_key] = response_dict

        return response_dict

    except requests.exceptions.Timeout:
        raise Exception(f"Ollama request timed out after {OLLAMA_TIMEOUT}s. The model may be loading or the query is too complex.")
    except requests.exceptions.ConnectionError:
        raise Exception(f"Cannot connect to Ollama at {OLLAMA_API_URL}. Make sure Ollama is running (`ollama serve`).")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Ollama API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from Ollama: {str(e)}")


# ─── Phase 0: Business Intelligence ──────────────────────────────────────────

_BUSINESS_KEYWORDS: dict = {
    # Sorted by length (longest first) for greedy matching
    "fitness studio": "gym", "charging station": "ev_charging",
    "ev charging": "ev_charging", "ladestation": "ev_charging",
    "nail salon": "nail_salon", "nagelstudio": "nail_salon",
    "gas station": "fuel_station", "fuel station": "fuel_station",
    "coffee shop": "cafe", "fast food": "fast_food",
    "bank branch": "bank_branch", "dental practice": "dental_practice",
    "tierarztpraxis": "veterinary_clinic", "vet clinic": "veterinary_clinic",
    "zahnarztpraxis": "dental_practice",
    "veterinary": "veterinary_clinic", "tierarzt": "veterinary_clinic",
    "apotheke": "pharmacy", "pharmacy": "pharmacy",
    "zahnarzt": "dental_practice", "dentist": "dental_practice",
    "supermarket": "supermarket", "lebensmittel": "supermarket",
    "grocery": "supermarket", "kindergarten": "kindergarten",
    "kita": "kindergarten", "daycare": "kindergarten",
    "restaurant": "restaurant", "fitness": "gym",
    "tankstelle": "fuel_station", "cinema": "cinema",
    "fastfood": "fast_food", "hostel": "hostel",
    "hotel": "hotel", "kneipe": "bar",
    "café": "cafe", "cafe": "cafe", "kino": "cinema",
    "bank": "bank_branch", "bar": "bar", "pub": "bar",
    "gym": "gym",
}


def _detect_business_type(question: str) -> Optional[str]:
    """Extract business type from a natural-language question via keyword matching."""
    q = question.lower()
    for kw in sorted(_BUSINESS_KEYWORDS, key=len, reverse=True):
        if kw in q:
            return _BUSINESS_KEYWORDS[kw]
    return None


def _get_business_profile(business_type: str) -> Optional[Dict[str, Any]]:
    """Look up a business profile from vector.business_profiles."""
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text as sa_text
        with db_manager.engine.connect() as conn:
            row = conn.execute(sa_text("""
                SELECT business_type, display_name, legal_zones, suitable_bezgfk,
                       avoid_bezgfk, competitor_table, competitor_filter,
                       competitor_radius_m, min_area_sqm, parking_radius_m,
                       transport_radius_m, min_residential_buildings,
                       residential_radius_m, weight_residential,
                       weight_competitor, weight_access, bonus_tables, notes
                FROM vector.business_profiles WHERE business_type = :bt
            """), {"bt": business_type}).fetchone()
            if row:
                d = dict(row._mapping)
                for k in ("legal_zones", "suitable_bezgfk", "avoid_bezgfk", "bonus_tables"):
                    if d.get(k) is not None and not isinstance(d[k], list):
                        d[k] = list(d[k])
                return d
    except Exception as e:
        print(f"[Phase0] Profile lookup error: {e}")
    return None


def _get_kg_facts(business_type: str) -> Dict[str, Any]:
    """Query the knowledge graph for legal zones and data mappings."""
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text as sa_text
        with db_manager.engine.connect() as conn:
            rows = conn.execute(sa_text("""
                SELECT predicate, object, condition, law_ref, weight
                FROM metadata.knowledge_graph
                WHERE subject = :bt
                ORDER BY predicate, weight DESC
            """), {"bt": business_type}).fetchall()
            result: Dict[str, Any] = {
                "permitted": [], "prohibited": [], "conditional": [],
                "data_in": [], "demand_from": [],
            }
            for row in rows:
                pred, obj, cond, law, wt = row
                entry = {"zone": obj, "condition": cond, "law": law,
                         "weight": float(wt) if wt else 1.0}
                if pred == "permitted_in":
                    result["permitted"].append(entry)
                elif pred == "prohibited_in":
                    result["prohibited"].append(entry)
                elif pred == "conditionally_permitted_in":
                    result["conditional"].append(entry)
                elif pred == "data_in":
                    result["data_in"].append({"table": obj, "filter": cond})
                elif pred == "demand_from":
                    result["demand_from"].append(
                        {"table": obj, "radius_m": cond, "weight": float(wt) if wt else 1.0}
                    )
            return result
    except Exception as e:
        print(f"[Phase0] KG lookup error: {e}")
    return {}


def _generate_business_profile_with_llm(
    business_type: str, question: str
) -> Optional[Dict[str, Any]]:
    """Auto-generate and persist a profile for an unknown business type."""
    if not DEEPSEEK_API_KEY:
        return None
    print(f"[Phase0] Generating profile for new business type: {business_type}")
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text as sa_text
        with db_manager.engine.connect() as conn:
            tables = conn.execute(sa_text(
                "SELECT table_name, description FROM metadata.table_descriptions ORDER BY table_name"
            )).fetchall()
            tables_str = "\n".join(f"  - {r[0]}: {r[1]}" for r in tables)
            bezgfk_vals = [
                r[0] for r in conn.execute(sa_text(
                    "SELECT DISTINCT bezgfk FROM vector.alkis_buildings "
                    "WHERE bezgfk IS NOT NULL LIMIT 30"
                )).fetchall() if r[0]
            ]
            inhalt_parts = list({
                part.strip()
                for row in conn.execute(sa_text(
                    "SELECT DISTINCT inhalt FROM vector.wfs_bplan_b_bp_fs "
                    "WHERE bp_rechtsstand='In Kraft getreten' AND inhalt IS NOT NULL LIMIT 30"
                )).fetchall()
                for part in (row[0] or "").split(",")
                if part.strip()
            })[:20]

        prompt = (
            f"You are a German urban planning and business location expert.\n"
            f"Generate site selection criteria for: {business_type} "
            f"(extracted from: \"{question}\")\n\n"
            f"Available database tables:\n{tables_str}\n\n"
            f"Available bezgfk values in the database:\n{', '.join(bezgfk_vals[:20])}\n\n"
            f"Available B-Plan inhalt patterns:\n{', '.join(inhalt_parts)}\n\n"
            f"Return ONLY valid JSON (no markdown):\n"
            f'{{\n'
            f'  "display_name": "English name (German name)",\n'
            f'  "legal_zones": ["zone1", "zone2"],\n'
            f'  "suitable_bezgfk": ["bezgfk1"],\n'
            f'  "avoid_bezgfk": ["bezgfk2"],\n'
            f'  "competitor_table": "table_name_or_null",\n'
            f'  "competitor_filter": "SQL WHERE fragment or null",\n'
            f'  "competitor_radius_m": 500,\n'
            f'  "min_area_sqm": 100,\n'
            f'  "parking_radius_m": 300,\n'
            f'  "transport_radius_m": 400,\n'
            f'  "min_residential_buildings": 300,\n'
            f'  "residential_radius_m": 800,\n'
            f'  "weight_residential": 0.40,\n'
            f'  "weight_competitor": 0.30,\n'
            f'  "weight_access": 0.30,\n'
            f'  "bonus_tables": [],\n'
            f'  "notes": "brief explanation"\n'
            f'}}\n\n'
            f"Use ONLY table names and bezgfk/inhalt values that exist above. "
            f"Base legal_zones on BauNVO regulations for this business type."
        )
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1, "max_tokens": 600},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        profile = json.loads(raw.strip())
        profile["business_type"] = business_type
        # Persist so future queries skip generation
        from app.utils.database import db_manager
        from sqlalchemy import text as sa_text
        with db_manager.engine.begin() as conn:
            conn.execute(sa_text("""
                INSERT INTO vector.business_profiles (
                    business_type, display_name, legal_zones, suitable_bezgfk,
                    avoid_bezgfk, competitor_table, competitor_filter,
                    competitor_radius_m, min_area_sqm, parking_radius_m,
                    transport_radius_m, min_residential_buildings,
                    residential_radius_m, weight_residential, weight_competitor,
                    weight_access, bonus_tables, notes
                ) VALUES (
                    :bt, :dn, :lz, :sb, :ab, :ct, :cf, :cr, :ma, :pr, :tr,
                    :mrb, :rr, :wr, :wc, :wa, :bonus, :notes
                ) ON CONFLICT (business_type) DO NOTHING
            """), {
                "bt": business_type,
                "dn": profile.get("display_name", business_type),
                "lz": profile.get("legal_zones", []),
                "sb": profile.get("suitable_bezgfk", []),
                "ab": profile.get("avoid_bezgfk", []),
                "ct": profile.get("competitor_table"),
                "cf": profile.get("competitor_filter"),
                "cr": profile.get("competitor_radius_m", 500),
                "ma": profile.get("min_area_sqm", 100),
                "pr": profile.get("parking_radius_m", 300),
                "tr": profile.get("transport_radius_m", 400),
                "mrb": profile.get("min_residential_buildings", 300),
                "rr": profile.get("residential_radius_m", 800),
                "wr": profile.get("weight_residential", 0.40),
                "wc": profile.get("weight_competitor", 0.30),
                "wa": profile.get("weight_access", 0.30),
                "bonus": profile.get("bonus_tables", []),
                "notes": profile.get("notes", ""),
            })
        print(f"[Phase0] Saved new profile: {profile.get('display_name')}")
        return profile
    except Exception as e:
        print(f"[Phase0] Profile generation failed: {e}")
    return None


def _format_business_profile_for_prompt(
    profile: Optional[Dict[str, Any]],
    kg_facts: Dict[str, Any],
    business_type: str,
) -> str:
    """Render a business profile + KG facts as a system-prompt section."""
    if not profile and not kg_facts:
        return ""
    lines = [
        "\n\n## BUSINESS SITE SELECTION PROFILE",
        f"Business: {profile.get('display_name', business_type) if profile else business_type}",
        "=" * 64,
    ]
    # Legal zones — KG is authoritative; profile is fallback
    permitted  = [e["zone"] for e in kg_facts.get("permitted", [])]
    prohibited = [e["zone"] for e in kg_facts.get("prohibited", [])]
    conditional = kg_facts.get("conditional", [])
    if not permitted and profile:
        permitted = profile.get("legal_zones", [])
    if permitted:
        lines.append("LEGAL ZONES (use for inhalt filter on wfs_bplan_b_bp_fs):")
        lines.append(f"  Permitted   : {', '.join(permitted)}")
    if prohibited:
        lines.append(f"  Prohibited  : {', '.join(e['zone'] for e in kg_facts.get('prohibited', []))}")
    if conditional:
        cond_strs = [f"{e['zone']} ({e['condition']})" for e in conditional if e.get("condition")]
        if cond_strs:
            lines.append(f"  Conditional : {', '.join(cond_strs)}")
    if profile:
        if profile.get("suitable_bezgfk"):
            lines.append("BUILDING TYPE (bezgfk must contain one of):")
            lines.append(f"  Suitable : {', '.join(profile['suitable_bezgfk'])}")
        if profile.get("avoid_bezgfk"):
            lines.append(f"  EXCLUDE  : {', '.join(profile['avoid_bezgfk'])}")
        if profile.get("competitor_table"):
            comp = profile["competitor_table"]
            if profile.get("competitor_filter"):
                comp += f" WHERE {profile['competitor_filter']}"
            lines.append(f"COMPETITOR  : {comp} — exclude within {profile['competitor_radius_m']}m")
        lines.append("PHYSICAL REQUIREMENTS:")
        lines.append(f"  Min area  : {profile['min_area_sqm']} sqm  (shape_area > {profile['min_area_sqm']})")
        lines.append(f"  Parking   : within {profile['parking_radius_m']}m")
        lines.append(f"  Transport : within {profile['transport_radius_m']}m")
        lines.append(f"  Demand    : {profile['min_residential_buildings']}+ residential buildings "
                     f"within {profile['residential_radius_m']}m")
        lines.append("SCORING WEIGHTS (use exactly):")
        lines.append(f"  Residential demand : {int(float(profile['weight_residential'])*100)}%")
        lines.append(f"  Competitor distance: {int(float(profile['weight_competitor'])*100)}%")
        lines.append(f"  Access (park+transit): {int(float(profile['weight_access'])*100)}%")
        bonuses = profile.get("bonus_tables") or []
        if bonuses:
            bonus_strs = [
                f"{str(b).split(':')[0]} within {str(b).split(':')[1]}m"
                if ":" in str(b) else str(b)
                for b in bonuses
            ]
            lines.append(f"BONUS       : {', '.join(bonus_strs)}")
        if profile.get("notes"):
            lines.append(f"NOTE        : {profile['notes']}")
    lines += [
        "=" * 64,
        "INSTRUCTION: Apply ALL values above as spatial filters, building type filters,",
        "competitor exclusion, scoring weights, and bonus factors. Do not guess — use profile values exactly.",
    ]
    return "\n".join(lines)


def _evaluate_results(
    results: list,
    profile: Optional[Dict[str, Any]],
    business_type: str,
) -> Dict[str, Any]:
    """
    Phase 5 — Rule-based result quality evaluation (no LLM call).
    Detects: empty results, geographic clustering, unsuitable building types.
    Returns {pass: bool, issues: list, warnings: list}
    """
    issues: list = []
    warnings: list = []

    if not results:
        issues.append("No results returned — constraints may be too strict")
        return {"pass": False, "issues": issues, "warnings": warnings}

    if len(results) < 3:
        warnings.append(f"Only {len(results)} result(s) — consider relaxing constraints")

    # Geographic clustering: all within ~300m?
    lats = [r.get("lat") or r.get("latitude") for r in results
            if r.get("lat") or r.get("latitude")]
    lons = [r.get("lon") or r.get("longitude") for r in results
            if r.get("lon") or r.get("longitude")]
    if len(lats) >= 3:
        if (max(lats) - min(lats)) < 0.003 and (max(lons) - min(lons)) < 0.003:
            warnings.append(
                f"All {len(results)} results cluster within ~300m — likely the same block. "
                "Add minimum distance between candidates for geographic diversity."
            )

    # Building type mismatch
    if profile and profile.get("avoid_bezgfk"):
        avoid_lower = [a.lower() for a in profile["avoid_bezgfk"]]
        bad_funcs = []
        for r in results:
            func = (
                r.get("bezgfk") or r.get("building_function") or
                r.get("building_type") or ""
            ).lower()
            if any(a in func for a in avoid_lower):
                bad_funcs.append(func)
        if bad_funcs:
            issues.append(
                f"Results include unsuitable building types: {', '.join(set(bad_funcs[:3]))}. "
                f"Add bezgfk exclusion: {', '.join(profile['avoid_bezgfk'])}"
            )

    return {"pass": len(issues) == 0, "issues": issues, "warnings": warnings}


# ─── End Phase 0 ──────────────────────────────────────────────────────────────


def parse_geospatial_query(question: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, selected_features: List[Dict[str, Any]] = None, drawn_geometry: Dict[str, Any] = None, llm_provider: str = None) -> OperationPlan:
    """
    Parse a natural language geospatial query into structured operations.
    Uses DeepSeek API to convert natural language to SQL.

    Args:
        question: Natural language query
        context: Optional context (city, timeframe, etc.)
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster', 'routing') to guide response format
        selected_feature: Optional selected feature from map for context-aware queries
        selected_features: Optional list of multiple selected features (for routing)
        drawn_geometry: Optional geometry drawn by user (GeoJSON format) - used as spatial context

    Returns:
        OperationPlan with structured operations
    """
    # Check for routing keywords when multiple features are selected
    routing_keywords = ['route', 'directions', 'navigate', 'routing', 'path', 'journey', 'tour', 'visit', 'loop', 'best route', 'find route']
    is_routing_query = any(keyword in question.lower() for keyword in routing_keywords)

    # If routing query with 2+ selected features, create routing operation directly
    if is_routing_query and selected_features and len(selected_features) >= 2:
        print(f"🛣️  Detected routing query with {len(selected_features)} selected features")

        # Extract geometries and names from selected features
        geometries = []
        feature_names = []

        for feature in selected_features:
            if isinstance(feature, dict):
                if 'geometry' in feature:
                    geometries.append(feature['geometry'])
                if 'properties' in feature and 'name' in feature['properties']:
                    feature_names.append(feature['properties']['name'])
                elif 'name' in feature:
                    feature_names.append(feature['name'])
                else:
                    feature_names.append(f"Point {len(feature_names) + 1}")

        if geometries and len(geometries) >= 2:
            return OperationPlan(
                operations=[
                    GeospatialOperation(
                        operation="routing",
                        parameters={
                            "geometries": geometries,
                            "feature_names": feature_names,
                            "mode": "optimal_tour"
                        },
                        description="Find optimal tour connecting selected features"
                    )
                ],
                reasoning="Computing optimal route through all selected locations using Nearest Neighbor TSP algorithm",
                datasets_required=["routing.ways", "routing.ways_vertices_pgr"],
                layer_name="optimal_route"
            )

    # ── Phase 0: Business Intelligence ──────────────────────────────────────
    business_profile: Optional[Dict[str, Any]] = None
    business_profile_section = ""
    business_type = _detect_business_type(question)
    if business_type:
        print(f"[Phase0] Business type detected: {business_type}")
        business_profile = _get_business_profile(business_type)
        if business_profile:
            print(f"[Phase0] Profile found: {business_profile['display_name']}")
        else:
            print(f"[Phase0] No profile found — generating with LLM...")
            business_profile = _generate_business_profile_with_llm(business_type, question)
        kg_facts = _get_kg_facts(business_type)
        n_perm = len(kg_facts.get("permitted", []))
        n_prohib = len(kg_facts.get("prohibited", []))
        print(f"[Phase0] KG: {n_perm} permitted zones, {n_prohib} prohibited zones")
        business_profile_section = _format_business_profile_for_prompt(
            business_profile, kg_facts, business_type
        )
    else:
        print(f"[Phase0] No business type detected — skipping profile lookup")
    # ── End Phase 0 ──────────────────────────────────────────────────────────

    # Route to appropriate LLM provider
    effective_query_type = query_type if not is_routing_query else "routing"
    provider = (llm_provider or "gemini").lower()

    # Phase 2 + 3: Fetch schema once (avoids double LLM call), then run query planning if needed
    precomputed_schema = None
    query_plan = {}
    try:
        schema_text, selected_tables = _get_database_schema_for_llm(question, _return_selected_tables=True)
        precomputed_schema = schema_text
        if _should_run_query_planning(selected_tables, schema_text):
            print(f"[Phase3] Running query planning ({len(selected_tables)} tables selected)")
            query_plan = _plan_query_with_llm(question, schema_text)
        else:
            print(f"[Phase3] Skipped — simple query ({len(selected_tables)} table(s))")
    except Exception as phase_err:
        print(f"⚠️ Phase 2/3 failed ({phase_err}) — Phase 4 will fetch schema independently")

    try:
        if provider == "gemini":
            print("✨ Using Gemini API")
            response_dict = query_gemini(question, context, user_location, effective_query_type, selected_feature, drawn_geometry, query_plan=query_plan, precomputed_schema=precomputed_schema)
        elif provider == "ollama":
            print("🦙 Using Ollama (local)")
            response_dict = query_ollama(question, context, user_location, effective_query_type, selected_feature, drawn_geometry)
        elif provider == "ollama_small":
            print("🦙 Using Ollama Small (local)")
            response_dict = query_ollama(question, context, user_location, effective_query_type, selected_feature, drawn_geometry, model_override=OLLAMA_MODEL_SMALL, num_ctx=64000, num_predict=2048)
        else:
            print("🧠 Using DeepSeek API")
            response_dict = query_deepseek(question, context, user_location, effective_query_type, selected_feature, drawn_geometry, query_plan=query_plan, precomputed_schema=precomputed_schema, business_profile_section=business_profile_section)
    except Exception as api_err:
        print(f"❌ API Error: {api_err}")
        import traceback
        traceback.print_exc()
        return OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={"error": str(api_err)},
                    description=f"AI Provider Error: {provider}"
                )
            ],
            reasoning=f"Error querying {provider}: {str(api_err)}",
            datasets_required=[],
            system_prompt="",
            user_prompt=question
        )

    # Extract the content, system_prompt, and user_prompt from the dict
    raw_content = response_dict.get("content", "")
    system_prompt = response_dict.get("system_prompt", "")
    user_prompt = response_dict.get("user_prompt", "")

    # Try to parse the JSON response
    try:
        # Clean the response - sometimes LLMs wrap JSON in markdown
        cleaned_response = raw_content.strip()

        # Strip <think>...</think> blocks that some local models embed in content
        import re as _re2
        cleaned_response = _re2.sub(r"<think>.*?</think>", "", cleaned_response, flags=_re2.DOTALL).strip()

        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Last resort: extract the outermost {...} block when the model wraps
        # JSON in natural language text (common with small local models)
        if not cleaned_response.startswith("{"):
            import re as _re3
            match = _re3.search(r"\{.*\}", cleaned_response, _re3.DOTALL)
            if match:
                cleaned_response = match.group(0)

        # Attempt to parse JSON - with retry logic for common escaping issues
        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as first_error:
            # Try fixing common JSON escaping issues (unescaped quotes in SQL strings)
            import re

            # Look for SQL strings with unescaped quotes and try to fix them
            # Pattern: "sql": "SELECT ... " where " inside should be \"
            fixed_response = cleaned_response

            # Fix unescaped quotes within SQL strings
            # This is a heuristic approach - look for "sql": "...SELECT..." patterns
            pattern = r'"sql"\s*:\s*"((?:[^"\\]|\\.)*?(?:SELECT|INSERT|UPDATE|DELETE|WITH)[^"]*?)"'

            def escape_sql_string(match):
                sql_content = match.group(1)
                # Escape any unescaped quotes in the SQL
                # Don't escape quotes that are already escaped
                escaped = sql_content.replace('"', '\\"').replace('\\"\\', '\\"')
                return f'"sql": "{escaped}"'

            fixed_response = re.sub(pattern, escape_sql_string, fixed_response, flags=re.IGNORECASE | re.DOTALL)

            # Try parsing again with fixed response
            try:
                parsed = json.loads(fixed_response)
                print("✅ JSON parsing fixed with escape handling")
            except json.JSONDecodeError as second_error:
                # If still failing, log and raise original error
                print(f"❌ JSON parsing still failed after escape fix: {second_error}")
                raise first_error

        # Convert to OperationPlan
        operations = [
            GeospatialOperation(**op) for op in parsed.get("operations", [])
        ]

        # Inject session_id from context into operations that need it
        # This ensures selected features work even if DeepSeek doesn't include session_id
        session_id = context.get("session_id") if context else None
        if session_id:
            ops_needing_session = ["walking_time", "nearest_by_road"]
            for op in operations:
                # Handle both string and enum operation types
                op_name = op.operation.value if hasattr(op.operation, 'value') else str(op.operation)
                if op_name in ops_needing_session:
                    if "session_id" not in op.parameters:
                        op.parameters["session_id"] = session_id
                        print(f"💉 Injected session_id '{session_id}' into {op_name} operation")

        return OperationPlan(
            operations=operations,
            layer_name=parsed.get("layer_name"),
            reasoning=parsed.get("reasoning"),
            datasets_required=parsed.get("datasets_required", []),
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

    except json.JSONDecodeError as e:
        # If JSON parsing fails, create a simple fallback plan
        print(f"Failed to parse DeepSeek response as JSON: {e}")
        print(f"Raw response: {raw_content}")

        # Return a basic error plan
        return OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={"error": "Failed to parse query"},
                    description=f"Could not parse: {question}"
                )
            ],
            reasoning=f"Error parsing response: {raw_content}",
            datasets_required=[],
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )


def clear_query_cache() -> None:
    """
    Clear the in-memory query cache.
    Useful for testing or resetting the system.
    """
    global _query_cache
    _query_cache.clear()
    print("✅ Query cache cleared")


def invalidate_query_cache() -> None:
    """
    Invalidate (clear) the in-memory query cache.
    Called by SchemaWatcher when the database schema changes so stale
    cached responses referencing dropped or newly added tables are evicted.
    """
    global _query_cache
    _query_cache.clear()
    print("✅ Query cache invalidated (schema change detected)")


def get_available_datasets() -> List[Dict[str, Any]]:
    """
    Return list of available datasets from PostGIS.
    Queries actual database tables.
    """
    from app.utils.database import db_manager

    try:
        # Get tables from PostGIS
        tables = db_manager.get_available_tables(schema="vector")

        datasets = []
        for table in tables:
            try:
                info = db_manager.get_table_info(table, schema="vector")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": f"{info['geometry_type']} - {info['row_count']} features",
                    "schema": "vector",
                    "row_count": info['row_count'],
                    "geometry_type": info['geometry_type'],
                    "columns": [col['name'] for col in info['columns']]
                })
            except Exception as e:
                print(f"Could not get info for table {table}: {e}")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": "PostGIS table",
                    "schema": "vector"
                })

        return datasets

    except Exception as e:
        print(f"Could not query database for datasets: {e}")
        # Fallback to known Berlin OSM tables
        return [
            {"name": "osm_hospitals", "type": "vector", "description": "Hospital locations in Berlin (59 features)", "schema": "vector"},
            {"name": "osm_toilets", "type": "vector", "description": "Public toilets in Berlin (1,160 features)", "schema": "vector"},
            {"name": "osm_pharmacies", "type": "vector", "description": "Pharmacy locations in Berlin (768 features)", "schema": "vector"},
            {"name": "osm_fire_stations", "type": "vector", "description": "Fire stations in Berlin (179 features)", "schema": "vector"},
            {"name": "osm_police_stations", "type": "vector", "description": "Police stations in Berlin (81 features)", "schema": "vector"},
            {"name": "osm_parks", "type": "vector", "description": "Parks in Berlin (2,785 features)", "schema": "vector"},
            {"name": "osm_schools", "type": "vector", "description": "Schools in Berlin (1,195 features)", "schema": "vector"},
            {"name": "osm_restaurants", "type": "vector", "description": "Restaurants in Berlin (5,013 features)", "schema": "vector"},
            {"name": "osm_transport_stops", "type": "vector", "description": "Transport stops in Berlin (14,899 features)", "schema": "vector"},
        ]
