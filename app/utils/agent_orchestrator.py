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

MAX_RESULT_CHARS = 2000  # Max characters of a tool result to feed back to LLM


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _build_agent_system_prompt() -> str:
    return """You are a geospatial AI agent. You answer questions by calling tools one at a time.

For each step output EXACTLY this format (no extra text before or after):
Thought: <your reasoning>
Action: <tool_name>
Args: <JSON object with arguments>

When you have enough information to give the final answer, output EXACTLY:
Thought: <brief conclusion>
Final Answer:
<valid GeoJSON FeatureCollection as compact JSON — no markdown, no code fences>
Summary: <one sentence describing the result>
Layer: <snake_case layer name, e.g. playgrounds_500m_neukoelln>

Available tools:
- geocode_location(name: str) → {lat, lon, display_name, geometry}
- create_buffer(geometry_or_coords: dict, radius_m: int) → GeoJSON Polygon
- query_features(description: str, within_geometry?: GeoJSON) → GeoJSON FeatureCollection
- spatial_filter(features: GeoJSON, filter_geometry: GeoJSON, relation: "within"|"intersects") → GeoJSON FeatureCollection
- get_schema_info(keywords: list[str]) → list of matching tables
- calculate_route(waypoints: list[{lat,lon,name}], mode: "driving"|"walking") → GeoJSON FeatureCollection
- walking_isochrone(location: {lat,lon}, minutes: int) → GeoJSON FeatureCollection
- analyze_satellite(bbox: GeoJSON|{min_lon,min_lat,max_lon,max_lat}, indices: list[str], date_range?: {start,end}) → GeoJSON FeatureCollection
- score_locations(features: GeoJSON, criteria: list[str]) → GeoJSON FeatureCollection with score property

Rules:
- ALWAYS call geocode_location before using a named place in any other tool
- The Final Answer MUST contain a valid GeoJSON FeatureCollection
- Never guess coordinates — always geocode named places
- Call tools one at a time; wait for the result before continuing
- If a tool returns an error, try an alternative approach or a different tool
- Do not apologise or add commentary outside the required format
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
    For FeatureCollections, keeps the first 5 features and adds a count note.
    """
    if isinstance(result, dict) and result.get("type") == "FeatureCollection":
        features = result.get("features", [])
        count = len(features)
        if count > 5:
            return {
                "type": "FeatureCollection",
                "features": features[:5],
                "count": count,
                "_truncated": f"Showing 5 of {count} features. Use the full result for Final Answer.",
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
    llm_provider: str = "gemini",
    max_iterations: int = 10,
    user_location: Optional[Dict] = None,
    drawn_geometry: Optional[Dict] = None,
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

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

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
            elapsed = round(time.time() - start_time, 2)
            yield AgentStep(
                type="tool_result",
                content="final_answer",
                tool_name="final_answer",
                tool_result=AgentFinalAnswer(
                    geojson=parsed["geojson"],
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
