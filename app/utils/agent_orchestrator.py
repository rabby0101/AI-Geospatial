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
- geocode_location(name: str) → {lat, lon, display_name, geometry}
- create_buffer(geometry_or_coords: dict, radius_m: int) → GeoJSON Polygon
- get_schema_info() → compact catalog of ALL available tables with name, description, geometry_type, row_count
- get_table_columns(table_name: str) → list of {column, type, sample_values} for a table in the vector schema
- execute_sql(sql: str) → GeoJSON FeatureCollection from a PostGIS SQL query
- spatial_filter(features: GeoJSON, filter_geometry: GeoJSON, relation: "within"|"intersects") → GeoJSON FeatureCollection
- calculate_route(waypoints: list[{lat,lon,name}], mode: "driving"|"walking") → GeoJSON FeatureCollection
- walking_isochrone(location: {lat,lon}, minutes: int) → GeoJSON FeatureCollection
- analyze_satellite(bbox: dict, indices: list[str]) → GeoJSON FeatureCollection
- score_locations(features: GeoJSON, criteria: list[str]) → GeoJSON FeatureCollection with score property

Standard workflow for spatial queries:
1. get_schema_info — get the full table catalog, pick the tables relevant to the query
2. get_table_columns — inspect column names, types, and sample values before writing SQL
3. geocode_location — resolve any named place to coordinates (if needed)
4. create_buffer — if a distance/radius is involved
5. execute_sql — write and run a PostGIS SQL query using what you learned

execute_sql rules:
- Tables are in the 'vector' schema: FROM vector.<table_name>
  Temp tables (selected features) are in the 'temp' schema: FROM temp.<table_name>
- ALWAYS write: SELECT *, ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geometry
  - geom_25833 is THE geometry column in ALL tables — never use 'geometry' or 'geom'
  - SELECT * preserves all feature attributes in the result
  - ST_Transform(geom_25833, 4326) converts to WGS84 so the map can render it
- For spatial proximity (ST_DWithin) use geom_25833 directly (units = metres, no transform needed):
  ST_DWithin(a.geom_25833, b.geom_25833, <metres>)
- For spatial filter with a buffer polygon use:
  WHERE ST_Within(ST_Transform(geom_25833, 4326), ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json>'), 4326))
  or ST_Intersects for partial overlap
- Always add LIMIT 500

Spatial tips:
- GEOMETRY COLUMN: ALL tables use geom_25833 (EPSG:25833, units = metres).
  Always write ST_AsGeoJSON(ST_Transform(geom_25833, 4326)) AS geometry in your SELECT.
  get_table_columns will show it first in the column list.
- COMPUTE AREA: Use ST_Area(geom_25833) / 10000.0 for hectares (geom_25833 is already projected, no transform needed).
  Do NOT use text 'area' columns for numeric comparison — always compute with ST_Area().
- FILTER BY DISTRICT: Find the districts/bezirk table from get_schema_info, then use
  ST_Intersects to spatially join. Check column names with get_table_columns first.

Rules:
- The Final Answer MUST be a valid GeoJSON FeatureCollection
- When execute_sql returns a successful FeatureCollection, IMMEDIATELY produce the Final Answer.
  Do NOT re-run the same query. Use this exact format:
  Thought: Got N results. Returning them.
  Final Answer:
  {"use_last_result": true}
  Summary: <one sentence describing results>
  Layer: <snake_case_name>
  The system will substitute the full FeatureCollection from your last execute_sql.
- Never guess table names — always call get_schema_info first
- Never guess column names — always call get_table_columns before writing SQL
- Call tools one at a time; wait for each result before proceeding
- If a tool returns an error, adjust and retry with corrected arguments
"""


def _call_llm(messages: list, provider: str = "deepseek") -> str:
    """Call DeepSeek with a message list. Returns raw text."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set. Add it to your .env file.")

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _truncate_result(result: Any, max_chars: int = MAX_RESULT_CHARS) -> Any:
    """
    Trim large tool results so they fit in the LLM context window.
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


def _parse_llm_output(raw: str) -> Dict[str, Any]:
    """
    Parse the LLM's raw text output into a structured dict.

    Returns one of:
        {"type": "action", "thought": str, "tool": str, "args": dict}
        {"type": "final_answer", "thought": str, "geojson": dict, "summary": str, "layer": str}
        {"type": "retry", "raw": str}
    """
    raw = raw.strip()

    # Extract Thought (optional)
    thought = ""
    thought_match = re.search(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", raw, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Check for Final Answer
    if "Final Answer:" in raw:
        try:
            after_fa = raw.split("Final Answer:", 1)[1].strip()
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
                pass
        return {"type": "action", "thought": thought, "tool": tool_name, "args": args}

    return {"type": "retry", "raw": raw}


# ---------------------------------------------------------------------------
# Main ReAct loop
# ---------------------------------------------------------------------------

async def run_agent(
    question: str,
    llm_provider: str = "deepseek",
    max_iterations: int = 15,
    user_location: Optional[Dict] = None,
    drawn_geometry: Optional[Dict] = None,
    session_id: Optional[str] = None,
    selected_features: Optional[list] = None,
) -> AsyncGenerator[AgentStep, None]:
    """
    Async generator that runs the ReAct loop and yields AgentStep objects.

    The caller (SSE route) iterates this generator and streams each step.
    The final yielded step has tool_name="final_answer" with the GeoJSON result.
    """
    start_time = time.time()

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
                f"Use this table in SQL for spatial proximity queries involving the selected features."
            )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    last_sql_result = None  # Store full execute_sql result for use_last_result

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
            # If agent signals use_last_result, substitute the full execute_sql result
            if isinstance(geojson, dict) and geojson.get("use_last_result") and last_sql_result:
                geojson = last_sql_result
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
                observation = tool_fn(**tool_args) if isinstance(tool_args, dict) else {
                    "error": f"Args must be a JSON object, got: {type(tool_args)}"
                }
            except TypeError as e:
                observation = {"error": f"Tool called with wrong arguments: {e}"}
            except Exception as e:
                observation = {"error": str(e)}

        # Store full execute_sql result for use_last_result
        if tool_name == "execute_sql" and isinstance(observation, dict) and observation.get("type") == "FeatureCollection":
            last_sql_result = observation

        truncated_obs = _truncate_result(observation)
        obs_str = json.dumps(truncated_obs, ensure_ascii=False, default=str)

        yield AgentStep(
            type="tool_result",
            content=obs_str,
            tool_name=tool_name,
            tool_result=truncated_obs,
        )

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation: {obs_str}"})

    yield AgentStep(
        type="error",
        content=f"Agent reached max iterations ({max_iterations}) without a final answer. Try a simpler question.",
    )
