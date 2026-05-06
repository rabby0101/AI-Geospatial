"""
ReAct Agent Orchestrator

Runs a Thought → Action → Observation loop using an LLM and the TOOL_REGISTRY.
Implemented as an async generator that yields AgentStep objects for SSE streaming.
"""
import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, Optional

import requests

from app.models.agent_model import AgentStep, AgentFinalAnswer
from app.utils.agent_tools import TOOL_REGISTRY
from app.utils.lmstudio_client import query_lmstudio

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

MAX_RESULT_CHARS = 12000  # Max characters of a tool result to feed back to LLM


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _build_agent_system_prompt() -> str:
    return """You are a geospatial AI agent that answers questions by calling tools one at a time.

For each step output EXACTLY this format:
Thought: <your reasoning>
Action: <tool_name>
Args: <JSON object with arguments>

When you have the final result, output EXACTLY:
Thought: <brief conclusion>
Final Answer:
<valid GeoJSON FeatureCollection as compact JSON — no markdown, no code fences>
Summary: <one sentence>
Layer: <snake_case_layer_name>

Available tools:
- find_tables_by_concept(concepts: list[str]) → {tables: [{table_name, description, analysis_patterns, related_tables}], count, matched_tags}
- geocode_location(name: str) → {lat, lon, display_name, geometry}
- create_buffer(geometry_or_coords: dict, radius_m: int) → GeoJSON Polygon
- get_schema_info() → compact catalog of ALL available tables with name, description, geometry_type, row_count
- get_table_columns(table_name: str) → list of {column, type, sample_values} for a table in the vector schema
- execute_sql(sql: str) → GeoJSON FeatureCollection from a PostGIS SQL query
- spatial_filter(features: GeoJSON, filter_geometry: GeoJSON, relation: "within"|"intersects") → GeoJSON FeatureCollection
- calculate_route(waypoints: list[{lat,lon,name}], mode: "walking"|"cycling"|"driving") → GeoJSON FeatureCollection with road-network route
- walking_isochrone(location: {lat,lon}, minutes: int, mode: "walking"|"cycling"|"driving") → GeoJSON FeatureCollection with reachable area polygon
- compute_spectral_index(index="NDVI", date=None, geometry=None, boundary_sql=None, bbox=None, polygons_sql=None, area_label="area") → GeoJSON FeatureCollection with {index}_mean per polygon + choropleth metadata. Computes a spectral index (NDVI/EVI/SAVI/NDWI/NDBI) over ANY area using attached satellite tiles. Supply exactly one geometry source: geometry (GeoJSON Polygon drawn on map), boundary_sql (SQL returning a geometry column — any name, any CRS, auto-handled), or bbox ({min_lon, min_lat, max_lon, max_lat}). Optional polygons_sql: SQL returning rows with an id/name column and a geometry column (any name, any CRS) for per-polygon zonal stats at any granularity — e.g. for Flurstücke in Mitte: boundary_sql="SELECT geom_25833 FROM vector.wfs_alkis_bezirke_bezirksgrenzen WHERE namgem='Mitte'" and polygons_sql="SELECT uuid AS id, geom_25833 FROM vector.wfs_alkis_flurstuecke_flurstuecke WHERE ST_Intersects(geom_25833, (SELECT geom_25833 FROM vector.wfs_alkis_bezirke_bezirksgrenzen WHERE namgem='Mitte'))". Do NOT pre-transform geometries — pass them as-is from the table.
- read_pdf_attachment(ref_id: str, pages: list[int]=None, max_chars: int=8000) → {ref_id, filename, n_pages, pages_read, text, truncated} — read text from an attached PDF. ref_id comes from the attachments block.
- read_tabular_attachment(ref_id: str, sheet: str=None, head_rows: int=50, as_records: bool=True) → {ref_id, filename, sheet, columns, dtypes, n_rows_total, rows, truncated} — read rows from an attached Excel/CSV file.
- score_locations(features: GeoJSON, criteria: list[str]) → GeoJSON FeatureCollection with score property
- generate_voronoi(table: str, id_col: str="id", clip_table: str=None) → saves Voronoi polygons to temp_layers, returns {saved, table, feature_count, geojson}
- generate_hexgrid(bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float) → GeoJSON FeatureCollection of hex cells (not saved — pass to other tools)
- generate_convex_hull(table: str) → GeoJSON FeatureCollection with single bounding Polygon
- generate_corridor(linestring_geojson: GeoJSON LineString, width_m: float) → GeoJSON FeatureCollection with corridor Polygon
- find_coverage_gaps(service_table: str, radius_m: float, clip_bbox: {min_lon,min_lat,max_lon,max_lat}) → saves gap polygons to temp_layers, returns {saved, table, feature_count, geojson}
- compute_site_suitability(bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float, criteria: [{table,weight,direction:"near"|"far"}]) → saves scored hex grid to temp_layers
- compute_kernel_density(table: str, bbox: {min_lon,min_lat,max_lon,max_lat}, cell_size_m: float=500) → saves density-scored hex grid to temp_layers
- compute_equity_gaps(service_table: str, district_table: str, service_col: str, population_col: str=None) → saves district equity scores to temp_layers
- add_hypothetical_feature(scenario_name: str, geometry: GeoJSON, properties: dict={}) → saves hypothetical feature to temp_layers scenario layer
- compare_scenarios(baseline_table: str, scenario_table: str, radius_m: float, clip_bbox: dict) → saves improved/unchanged gap diff to temp_layers
- save_generated_layer(geojson: FeatureCollection, layer_name: str, description: str="") → saves any FeatureCollection to temp_layers, returns {saved, table, feature_count}

Standard workflow for spatial queries (SQL-based):
1. find_tables_by_concept — ALWAYS call this first. Extract the key domain concepts from
   the user's question (e.g. "zoning plan", "elderly population", "pharmacy", "B-Plan",
   "residential building") and pass them as a list. Works in any language — German or English.
   This uses the knowledge graph to return exactly the right tables, regardless of their
   technical names (e.g. "wfs_bplan_a_bp_iv" for "B-Pläne").
   Example: find_tables_by_concept({"concepts": ["zoning plan", "B-Plan", "residential building"]})
2. get_table_columns — inspect column names and sample values for the tables returned in step 1
3. get_schema_info — only if find_tables_by_concept returned no results for an unusual query
2. get_table_columns — inspect column names, types, and sample values before writing SQL
3. geocode_location — resolve any named place to coordinates (if needed)
4. create_buffer — if a distance/radius is involved
5. execute_sql — write and run a PostGIS SQL query using what you learned

Routing workflow (route from A to B):
1. geocode_location — resolve each named place to {lat, lon}
2. If one end is "nearest X": execute_sql — find the nearest matching feature and extract its coordinates
3. calculate_route — pass the resolved waypoints with the correct mode ("walking"/"cycling"/"driving")

Isochrone workflow (area reachable within N minutes):
⚠️ TRIGGER RULE: If the query mentions ANY time duration (e.g. "5 minutes", "10 min", "half an hour") alongside walking, travel, or reachability — ALWAYS use walking_isochrone. Never use create_buffer or ST_DWithin as a substitute.
Origin from a named place:
1. geocode_location — resolve the origin place to {lat, lon}
2. walking_isochrone — pass the coordinates, minutes, and mode ("walking"/"cycling"/"driving")
3. If the question also asks about POIs within the area: spatial_filter or execute_sql using the isochrone polygon
Origin from a selected feature (temp table available):
1. execute_sql — extract the centroid: SELECT ST_Y(ST_Transform(ST_Centroid(geom_25833),4326)) AS lat, ST_X(ST_Transform(ST_Centroid(geom_25833),4326)) AS lon FROM temp.temp_selected_<session_id> LIMIT 1
2. walking_isochrone — pass {lat, lon} from step 1, minutes, and mode
3. execute_sql or spatial_filter — find POIs within the isochrone polygon

Accessibility density workflow (which areas have fewest X within N minutes?):
1. get_schema_info — find the neighborhood/district table and the POI table
2. get_table_columns — check column names for both tables
3. execute_sql — for each district, count POIs within a walking-distance proxy using ST_DWithin on geom_25833, then ORDER BY count ASC

execute_sql rules:
- Tables are in the 'vector' schema: FROM vector.<table_name>
  Temp tables (selected features) are in the 'temp' schema: FROM temp.<table_name>
- ALWAYS write: SELECT *, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom
  - geom_25833 is THE geometry column in ALL tables — always use geom_25833, never 'geometry'
  - Use alias 'geom' (not 'geometry') — some tables already have a 'geometry' column
  - SELECT * preserves all feature attributes in the result
  - ST_Transform(geom_25833, 4326) converts to WGS84 so the map can render it
- NEVER use SELECT COUNT(*) alone — always SELECT the full features with geometry.
  For "how many X" questions: select the actual features (SELECT *, ST_AsGeoJSON(...) AS geom),
  then report the count in the Summary. The map requires real geometries to display results.
- For spatial proximity (ST_DWithin) use geom_25833 directly (units = metres, no transform needed):
  ST_DWithin(a.geom_25833, b.geom_25833, <metres>)
- For spatial filter with a buffer polygon use:
  WHERE ST_Within(ST_Transform(geom_25833, 4326), ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json>'), 4326))
  or ST_Intersects for partial overlap
- COMPUTED METRICS IN SQL: Any derived metric you reason about (ratios, rates,
  per-capita values, percentages, densities, scores) MUST be expressed as an
  explicit SQL expression in the SELECT clause — not just mentioned in the Summary.
  This makes every computed field available as a GeoJSON property, which the map
  exposes in the gradient dropdown for visualization.
  Pattern (adapt column names to the actual query):
    CAST(count_col AS FLOAT) / NULLIF(base_col, 0) AS ratio_name
    CAST(count_col AS FLOAT) / NULLIF(base_col / 1000.0, 0) AS per_1000_name
    ST_Area(geom_25833) / NULLIF(count_col, 0) AS area_per_unit
  Always use NULLIF to guard against division by zero.
  Rule: if you would mention a computed number in the Summary, include it as a
  named SQL column too.
- DATA GRANULARITY — always go deepest by default: When get_schema_info shows
  multiple tables covering the same topic at different geographic scales, always
  pick the most granular (finest) one unless the user explicitly asks for a
  coarser level (e.g. "by district", "by Bezirk").
  How to identify granularity:
    row_count: more rows = finer geography (prefer higher)
    description keywords fine: "Planungsraum", "PLZ", "block", "subdivision"
    description keywords coarse: "district", "Bezirk", "region", "city-wide"
  Rationale: coarse tables hide concentration hotspots that only appear in
  fine-grained data. Default to maximum available detail.

Spatial tips:
- GEOMETRY COLUMN: ALL tables use geom_25833 (EPSG:25833, units = metres).
  Always write ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom in your SELECT.
  Never use 'geometry' as an alias — some tables already have a raw 'geometry' column.
  get_table_columns will show geom_25833 first in the column list.
- COMPUTE AREA: Use ST_Area(geom_25833) / 10000.0 for hectares (geom_25833 is already projected, no transform needed).
  Do NOT use text 'area' columns for numeric comparison — always compute with ST_Area().
- FILTER BY DISTRICT: Find the districts/bezirk table from get_schema_info, then use
  ST_Intersects to spatially join. Check column names with get_table_columns first.

CORRECT format examples (follow these exactly):

Example 1 — inspect a table's columns:
Thought: I need to check the columns of the osm_parks table.
Action: get_table_columns
Args: {"table_name": "osm_parks"}

Example 2 — run a SQL query:
Thought: I will find parks larger than 5 hectares in Neukölln.
Action: execute_sql
Args: {"sql": "SELECT *, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM vector.osm_parks p JOIN vector.wfs_alkis_bezirk b ON ST_Intersects(p.geom_25833, b.geom_25833) WHERE b.namgem = 'Neukölln' AND ST_Area(p.geom_25833) / 10000.0 > 5"}

Example 3 — return the result immediately after a successful SQL call:
Thought: Got result. Returning it.
Final Answer:
{"use_last_result": true}
Summary: Found 3 parks in Neukölln larger than 5 hectares.
Layer: large_parks_neukoelln

Rules:
- Args MUST always contain ALL required parameters — NEVER use empty Args: {}
- The Final Answer MUST be a valid GeoJSON FeatureCollection
- When execute_sql, calculate_route, walking_isochrone, compute_spectral_index, or compute_temporal_analysis returns a successful FeatureCollection,
  IMMEDIATELY produce the Final Answer using this exact format:
  Thought: Got result. Returning it.
  Final Answer:
  {"use_last_result": true}
  Summary: <one sentence describing results>
  Layer: <snake_case_name>
  The system will substitute the full FeatureCollection from the last successful tool call.
  Do NOT try to echo the geometry coordinates — always use {"use_last_result": true}.
- Never guess table names — always call get_schema_info first
- Never guess column names — always call get_table_columns before writing SQL
- After inspecting the schema, proceed directly to execute_sql. Only call get_schema_info
  a second time if you could not identify the table needed for the query on the first pass.
- Call tools one at a time; wait for each result before proceeding
- If a tool returns an error, adjust and retry with corrected arguments

- If the user provides ONLY a location/address with no question:
  → geocode_location to resolve it
  → Return a GeoJSON FeatureCollection with the point geometry as-is

Geometry generation workflow:
- "Generate Voronoi zones for all hospitals" → generate_voronoi(table="public.osm_hospitals")
- "Show the convex hull of all schools" → generate_convex_hull(table="public.osm_schools")
- "Create a 200m corridor along [route]" → calculate_route first, then generate_corridor(linestring, width_m=200)
- "Generate a 500m hex grid over Berlin" → generate_hexgrid(bbox={min_lon:13.088,min_lat:52.338,max_lon:13.761,max_lat:52.675}, cell_size_m=500)

Coverage and suitability workflow:
- "Find areas more than 1km from a pharmacy" → geocode_location to get bbox, then find_coverage_gaps(service_table="public.osm_pharmacies", radius_m=1000, clip_bbox=...)
- "Best locations for a new clinic near transport, far from existing clinics" → compute_site_suitability(bbox=..., cell_size_m=500, criteria=[{table:"public.osm_transport_stops",weight:0.5,direction:"near"},{table:"public.osm_hospitals",weight:0.5,direction:"far"}])

Analytical surface workflow:
- "Show density of restaurants across Berlin" → compute_kernel_density(table="public.osm_restaurants", bbox={...berlin bbox...})
- "Which districts have worst hospital coverage?" → compute_equity_gaps(service_table="public.osm_hospitals", district_table="vector.wfs_schulen_schulen", service_col="hospital_count")

Scenario planning workflow:
1. add_hypothetical_feature(scenario_name="new_hospital", geometry={...point...}, properties={type:"hospital"})
2. compare_scenarios(baseline_table="public.osm_hospitals", scenario_table="temp_layers.layer_scenario_new_hospital_...", radius_m=1000, clip_bbox=...)

Satellite / multi-date change workflow:
- "Calculate NDVI/EVI/NDWI/… change" or "compare satellite images" → compute_temporal_analysis(index="NDVI", boundary_sql=...) — handles any number of attached dates automatically, returns per-polygon change columns.

Generated layer rule: when a spatial generation tool returns {saved: true, table: "temp_layers.X", geojson: ...},
use {"use_last_result": true} as the Final Answer — the frontend renders the geojson from the result directly.

Chat attachments workflow:
If the user message contains an "Attached files" block, the user uploaded PDFs / Excel / satellite tiles.
Each entry has a ref_id you MUST use to access the content.
- [satellite] attachment + question about a Berlin district (e.g. "NDVI of Mitte", "greenness of Neukölln"):
  → call ndvi_by_district(district_name="Mitte", index="NDVI")  (satellite files are already staged in the session)
  → it returns a FeatureCollection clipped to the district with ndvi_mean per polygon — produce Final Answer with {"use_last_result": true}
- [pdf] attachment + question about the document ("summarize", "what does it say about X"):
  → call read_pdf_attachment(ref_id="att_xxx")  and base your Summary on the returned text
- [tabular] attachment + question about the spreadsheet ("which column has highest average", "how many rows"):
  → call read_tabular_attachment(ref_id="att_xxx", sheet=<name>, head_rows=50)  and compute the answer from rows
For pure-text answers (PDF/Excel questions that don't produce a map layer), use this Final Answer shape:
  Final Answer:
  {"type":"FeatureCollection","features":[]}
  Summary: <one or two sentences derived from the attachment>
  Layer: <snake_case_name>
"""


def _call_llm(messages: list, provider: str = "deepseek") -> str:
    """Route to the appropriate LLM provider and return raw text."""
    print(f"[_call_llm] provider={provider}, messages_count={len(messages)}")
    if provider == "lmstudio":
        print(f"[_call_llm] calling query_lmstudio")
        result = query_lmstudio(messages)
        print(f"[_call_llm] query_lmstudio returned: {result[:50]}")
        return result

    # Default: DeepSeek
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set. Add it to your .env file.")
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _truncate_result(result: Any, max_chars: int = MAX_RESULT_CHARS) -> Any:
    """
    Trim large tool results for frontend display.
    For FeatureCollections with geometry, keeps the first 3 features.
    For FeatureCollections without geometry (e.g. SELECT DISTINCT), keeps up to 30.
    """
    if isinstance(result, dict) and result.get("type") == "FeatureCollection":
        features = result.get("features", [])
        count = len(features)
        # Check if features have geometry (spatial results vs tabular results)
        has_geometry = any(f.get("geometry") for f in features[:3])
        limit = 3 if has_geometry else 30
        if count > limit:
            return {
                "type": "FeatureCollection",
                "features": features[:limit],
                "count": count,
                "_note": f"Showing {limit} of {count}. Full result is stored — use Final Answer: {{\"use_last_result\": true}} to return it.",
            }

    result_str = json.dumps(result)
    if len(result_str) > max_chars:
        return result_str[:max_chars] + "... [truncated]"

    return result


def _prepare_obs_for_llm(tool_name: str, result: Any, max_chars: int = MAX_RESULT_CHARS) -> Any:
    """
    Prepare tool result for LLM context — geometry-aware stripping.

    - execute_sql with real geometry: strip geometry coordinates, keep only properties.
      The LLM reasons about feature attributes, not raw coordinate arrays.
    - walking_isochrone / calculate_route: keep geometry intact — the LLM needs the
      polygon/line to use in the next ST_GeomFromGeoJSON(...) SQL call.
    - Null-geometry results (e.g. centroid extraction returning lat/lon in properties):
      keep as-is — the LLM must see the actual values to pass to the next tool.
    - All other results: apply character cap as fallback.
    """
    if not (isinstance(result, dict) and result.get("type") == "FeatureCollection"):
        result_str = json.dumps(result)
        if len(result_str) > max_chars:
            return result_str[:max_chars] + "... [truncated]"
        return result

    features = result.get("features", [])
    total = len(features)
    has_geometry = any(f.get("geometry") for f in features[:3])

    # Null-geometry result (e.g. centroid lat/lon in properties) — keep in full
    if not has_geometry:
        result_str = json.dumps(result)
        if len(result_str) > max_chars:
            return result_str[:max_chars] + "... [truncated]"
        return result

    # execute_sql: return plain metadata — deliberately NOT a FeatureCollection.
    # If we return a FeatureCollection with geometry:null, the LLM may echo it directly
    # as Final Answer, causing the map to receive null geometries and render nothing.
    # A plain dict forces the LLM to use {"use_last_result": true}, which substitutes
    # last_result (the full geometry-intact observation) into the final answer.
    if tool_name == "execute_sql":
        MAX_SAMPLE = 5
        sample_props = []
        for f in features[:MAX_SAMPLE]:
            props = dict(f.get("properties") or {})
            props.pop("geom", None)
            props.pop("geometry", None)
            sample_props.append(props)
        return {
            "status": "success",
            "total_features": total,
            "sample_properties": sample_props,
            "_note": (
                f"Query returned {total} features with geometry. "
                "Full spatial result is stored — use "
                "{\"use_last_result\": true} in your Final Answer to return it to the map."
            ),
        }

    # compute_spectral_index / compute_temporal_analysis: strip geometry from features
    # but preserve top-level saved_table and metadata so the LLM can reference the
    # persisted table name in a subsequent SQL join.
    if tool_name in ("compute_spectral_index", "compute_temporal_analysis"):
        MAX_SAMPLE = 5
        sample_props = []
        for f in features[:MAX_SAMPLE]:
            props = dict(f.get("properties") or {})
            props.pop("geom", None)
            sample_props.append(props)
        return {
            "status": "success",
            "total_features": total,
            "sample_properties": sample_props,
            "saved_table": result.get("saved_table"),
            "metadata": result.get("metadata"),
            "_note": (
                f"Spectral index computed for {total} polygon(s). "
                "Full result stored — use {\"use_last_result\": true} in Final Answer. "
                "If further processing is needed, reference saved_table for SQL joins."
            ),
        }

    # walking_isochrone / calculate_route: keep geometry (needed for next SQL step)
    # but still apply the character cap
    result_str = json.dumps(result)
    if len(result_str) > max_chars:
        return result_str[:max_chars] + "... [truncated]"
    return result


def _parse_llm_output(raw: str) -> Dict[str, Any]:
    """
    Parse the LLM's raw text output into a structured dict.

    Returns one of:
        {"type": "action", "thought": str, "tool": str, "args": dict}
        {"type": "final_answer", "thought": str, "geojson": dict, "summary": str, "layer": str}
        {"type": "retry", "raw": str}
    """
    raw = raw.strip()

    # Fix 4: Strip markdown code fences that smaller models (e.g. Gemma4) often add
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)

    # Extract Thought (optional)
    thought = ""
    thought_match = re.search(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", raw, re.DOTALL | re.IGNORECASE)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Fix 2: Case-insensitive Final Answer detection (Gemma4 may output "final answer:")
    fa_match = re.search(r"Final Answer:", raw, re.IGNORECASE)
    if fa_match:
        try:
            after_fa = raw[fa_match.end():].strip()
            # Extract JSON block (greedy match from first { to last })
            json_match = re.search(r"(\{.*\})", after_fa, re.DOTALL)
            if not json_match:
                return {"type": "retry", "raw": raw}
            geojson = json.loads(json_match.group(0))

            summary_match = re.search(r"Summary:\s*(.+)", after_fa)
            layer_match = re.search(r"Layer:\s*(\S+)", after_fa)

            return {
                "type": "final_answer",
                "thought": thought,
                "geojson": geojson,
                "summary": summary_match.group(1).strip() if summary_match else "Done.",
                "layer": layer_match.group(1).strip() if layer_match else "agent_result",
            }
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse Final Answer: {e}")
            return {"type": "retry", "raw": raw}

    # Check for Action
    action_match = re.search(r"Action:\s*(\w+)", raw)
    args_match = re.search(r"Args:\s*(\{.*\}|\[.*\])", raw, re.DOTALL)

    if action_match:
        tool_name = action_match.group(1).strip()
        args = {}
        if args_match:
            try:
                args = json.loads(args_match.group(1))
            except json.JSONDecodeError:
                # Fix 3: Malformed Args JSON → retry with format correction instead of silently using {}
                return {"type": "retry", "raw": raw}
        return {"type": "action", "thought": thought, "tool": tool_name, "args": args}

    return {"type": "retry", "raw": raw}


# ---------------------------------------------------------------------------
# Main ReAct loop
# ---------------------------------------------------------------------------

async def run_agent(
    question: str,
    llm_provider: str = "deepseek",
    max_iterations: int = 40,
    user_location: Optional[Dict] = None,
    drawn_geometry: Optional[Dict] = None,
    session_id: Optional[str] = None,
    selected_features: Optional[list] = None,
    attachments: Optional[list] = None,
) -> AsyncGenerator[AgentStep, None]:
    """
    Async generator that runs the ReAct loop and yields AgentStep objects.

    The caller (SSE route) iterates this generator and streams each step.
    The final yielded step has tool_name="final_answer" with the GeoJSON result.
    """
    start_time = time.time()

    # Make the active session_id visible to attachment-reading tools via contextvar.
    if session_id:
        try:
            from app.utils.attachment_store import current_session_id
            current_session_id.set(session_id)
        except Exception:
            pass

    system_prompt = _build_agent_system_prompt()
    user_content = question
    if user_location:
        user_content += f"\n\nUser location: lat={user_location['lat']}, lon={user_location['lon']}"
    if drawn_geometry:
        user_content += (
            f"\n\nUser drew this geometry on the map (use as spatial context): "
            f"{json.dumps(drawn_geometry)[:300]}"
        )

    if selected_features:
        lines = []
        for i, feat in enumerate(selected_features[:10]):
            props = feat.get("properties") or {}
            name = feat.get("name") or props.get("name") or f"Feature {i + 1}"
            props_str = json.dumps(props, ensure_ascii=False)[:300]
            lines.append(f"  {i + 1}. {name}: {props_str}")
        user_content += (
            f"\n\nUser has selected {len(selected_features)} feature(s) on the map:\n"
            + "\n".join(lines)
        )
        if session_id:
            user_content += (
                f"\n\nSelected features' geometries are stored in PostGIS: "
                f"temp.temp_selected_{session_id} (columns: id, geom_25833). "
                f"For plain distance queries use ST_DWithin with this table. "
                f"For time-based walking queries (e.g. 'within X minutes') follow the isochrone workflow: "
                f"extract {'{'}lat,lon{'}'} from the temp table via execute_sql, then call walking_isochrone."
            )

    # Attachment context — only injected when the session has a manifest and
    # the frontend forwarded an attachments array (cheap sanity check).
    if session_id and attachments:
        try:
            from app.utils.attachment_store import AttachmentStore
            store = AttachmentStore(session_id)
            block = store.get_context_block()
            if block:
                user_content += block
        except Exception as e:
            logger.warning(f"Attachment context injection failed: {e}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    last_result = None  # Store full tool result for use_last_result (execute_sql, calculate_route, walking_isochrone)
    seen_calls: set = set()  # Track repeated tool calls to break loops

    retry_count = 0
    max_retries = 2

    for iteration in range(max_iterations):
        try:
            raw = _call_llm(messages, llm_provider)
        except Exception as e:
            yield AgentStep(type="error", content=f"LLM call failed: {e}")
            return

        parsed = _parse_llm_output(raw)

        if parsed["type"] == "retry":
            retry_count += 1
            if retry_count > max_retries:
                yield AgentStep(
                    type="error",
                    content="Agent could not produce a valid response. Please rephrase your question.",
                )
                return
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "Please respond using exactly the required format:\n"
                    "Thought: ...\nAction: ...\nArgs: {...}\n\n"
                    "or if done:\nThought: ...\nFinal Answer:\n{GeoJSON}\nSummary: ...\nLayer: ..."
                ),
            })
            continue

        retry_count = 0

        if parsed["thought"]:
            yield AgentStep(type="thought", content=parsed["thought"])

        if parsed["type"] == "final_answer":
            geojson = parsed["geojson"]

            # Always prefer last_result over whatever the LLM echoed.
            # last_result is the full geometry-intact FeatureCollection from the most recent
            # successful spatial tool call. The LLM's parsed geojson may be
            # {"use_last_result": true}, a stripped FC with null geometries, or a COUNT
            # result — none of which render correctly on the map.
            if last_result:
                geojson = last_result

            # Safety check: if we still have no renderable geometry (e.g. LLM wrote a
            # COUNT(*) query and no prior spatial call stored a last_result), loop back
            # and ask the agent to re-run with full features instead of a count.
            _final_features = geojson.get("features", []) if isinstance(geojson, dict) else []
            _has_render_geometry = any(f.get("geometry") for f in _final_features[:3])

            if not _has_render_geometry:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your answer contains no geometry and cannot be displayed on the map. "
                        "This usually happens when SELECT COUNT(*) was used instead of selecting features. "
                        "Please run execute_sql again using:\n"
                        "SELECT *, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geom FROM vector.<table> ...\n"
                        "Retrieve the actual features so they can be rendered. "
                        "Report the count in your Summary — do not use SELECT COUNT(*)."
                    ),
                })
                continue

            elapsed = round(time.time() - start_time, 2)
            yield AgentStep(
                type="tool_result",
                content="final_answer",
                tool_name="final_answer",
                tool_result=AgentFinalAnswer(
                    geojson=geojson,
                    summary=parsed["summary"],
                    layer_name=parsed["layer"],
                    steps_taken=iteration + 1,
                    execution_time=elapsed,
                ).model_dump(),
            )
            return

        # Execute tool
        tool_name = parsed["tool"]
        tool_args = parsed.get("args", {})

        # Fix 1: Loop detection extended to ALL tools (not just schema tools).
        # Smaller models (e.g. Gemma4) can repeat any tool indefinitely.
        call_key = (tool_name, json.dumps(tool_args, sort_keys=True))
        if call_key in seen_calls:
            messages.append({"role": "assistant", "content": raw})
            if tool_name in ("get_schema_info", "get_table_columns"):
                nudge = (
                    f"You already called {tool_name}({json.dumps(tool_args)}) earlier and have the result in this conversation. "
                    "Do NOT call it again. You have all the schema and column information you need. "
                    "Proceed directly to execute_sql with your PostGIS SQL query now."
                )
            else:
                nudge = (
                    f"You already called {tool_name}({json.dumps(tool_args)}) with these exact arguments "
                    "and the result is already in this conversation. Do NOT call it again. "
                    "Use the results you already have to produce your Final Answer now."
                )
            messages.append({"role": "user", "content": nudge})
            continue
        seen_calls.add(call_key)

        yield AgentStep(
            type="action",
            content=f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)[:200]})",
            tool_name=tool_name,
            tool_args=tool_args,
        )

        if tool_name not in TOOL_REGISTRY:
            observation = {
                "error": f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}"
            }
        else:
            try:
                tool_fn = TOOL_REGISTRY[tool_name]
                # Substitute last_result when save_generated_layer is called with the
                # {"use_last_result": true} sentinel — mirrors the final_answer path.
                if (
                    tool_name == "save_generated_layer"
                    and isinstance(tool_args.get("geojson"), dict)
                    and tool_args["geojson"].get("use_last_result")
                    and last_result
                ):
                    tool_args = {**tool_args, "geojson": last_result}
                observation = tool_fn(**tool_args) if isinstance(tool_args, dict) else {
                    "error": f"Args must be a JSON object, got: {type(tool_args)}"
                }
            except TypeError as e:
                observation = {"error": f"Tool called with wrong arguments: {e}"}
            except Exception as e:
                observation = {"error": str(e)}

        # Store full result for use_last_result (routing/isochrone tools return large geometries the LLM can't echo)
        # Only treat as "got spatial result" when features have actual geometry — null-geometry results
        # (e.g. a centroid extraction returning lat/lon in properties) are intermediate data that the
        # LLM must see in full to use in the next tool call.
        _obs_features = observation.get("features", []) if isinstance(observation, dict) else []
        _has_real_geometry = any(f.get("geometry") for f in _obs_features[:3])
        got_feature_collection = (
            tool_name in ("execute_sql", "calculate_route", "walking_isochrone", "compute_spectral_index", "compute_temporal_analysis")
            and isinstance(observation, dict)
            and observation.get("type") == "FeatureCollection"
            and _has_real_geometry
        )
        if got_feature_collection:
            last_result = observation

        # Frontend display: truncated but with geometry (for map rendering)
        truncated_obs = _truncate_result(observation)
        obs_str = json.dumps(truncated_obs, ensure_ascii=False, default=str)

        # LLM context: geometry stripped from SQL results to keep context small
        llm_obs = _prepare_obs_for_llm(tool_name, observation)
        llm_obs_str = json.dumps(llm_obs, ensure_ascii=False, default=str)

        yield AgentStep(
            type="tool_result",
            content=obs_str,
            tool_name=tool_name,
            tool_result=truncated_obs,
        )

        messages.append({"role": "assistant", "content": raw})

        if got_feature_collection:
            feature_count = len(observation.get("features", []))
            messages.append({
                "role": "user",
                "content": (
                    f"Observation: {llm_obs_str}\n\n"
                    f"The {tool_name} call returned a successful FeatureCollection with {feature_count} feature(s). "
                    "If this result directly and completely answers the user's original question, produce the Final Answer now using exactly this format:\n"
                    "Thought: Got result. Returning it.\n"
                    "Final Answer:\n"
                    '{"use_last_result": true}\n'
                    "Summary: <one sentence describing the results>\n"
                    "Layer: <snake_case_layer_name>\n\n"
                    "If this is an intermediate step (e.g., you still need to call execute_sql, "
                    "score_locations, or spatial_filter to complete the workflow), "
                    "continue with the next step now. When writing SQL that needs this polygon, "
                    "use: WHERE ST_Within(ST_Transform(geom_25833, 4326), "
                    "ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json_from_observation>'), 4326))"
                ),
            })
        else:
            messages.append({"role": "user", "content": f"Observation: {llm_obs_str}"})


    yield AgentStep(
        type="error",
        content=f"Agent reached max iterations ({max_iterations}) without a final answer. Try a simpler question.",
    )
