# Agentic Geospatial System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic LLM pipeline with a ReAct agent that calls discrete tools (geocode, buffer, query, route, etc.) one at a time, streaming each step to the frontend via SSE.

**Architecture:** A ReAct loop (Thought → Action → Observation) runs in `agent_orchestrator.py`. The LLM decides which tool to call next based on accumulated observations. Python executes each tool and feeds the result back to the LLM. The loop ends when the LLM outputs a Final Answer containing GeoJSON.

**Tech Stack:** FastAPI SSE via `StreamingResponse` (no new deps), PostGIS, Nominatim, existing `sql_generator.py` / `spatial_engine.py` / `location_resolver.py`, Gemini/DeepSeek LLMs.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `app/models/agent_model.py` | Pydantic models for agent request/response/steps |
| Create | `app/utils/agent_tools.py` | 9 tool functions wrapping existing utilities |
| Create | `app/utils/agent_orchestrator.py` | ReAct loop: LLM calls, parse, dispatch, stream |
| Create | `app/routes/agent.py` | `POST /api/agent/query` SSE endpoint |
| Create | `tests/test_agent_tools.py` | Unit tests for each tool |
| Create | `tests/test_agent_orchestrator.py` | Tests for orchestrator parsing logic |
| Modify | `app/main.py` | Import and register agent router |
| Modify | `frontend/index.html` | SSE client + collapsible agent progress panel |

---

## Task 1: Data Models

**Files:**
- Create: `app/models/agent_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_models.py
from app.models.agent_model import AgentRequest, AgentStep, AgentFinalAnswer

def test_agent_request_defaults():
    req = AgentRequest(question="Find parks near me")
    assert req.llm_provider == "gemini"
    assert req.max_iterations == 10

def test_agent_step_types():
    step = AgentStep(type="thought", content="I need to geocode this location")
    assert step.type == "thought"

def test_agent_final_answer():
    fa = AgentFinalAnswer(
        geojson={"type": "FeatureCollection", "features": []},
        summary="Found 3 parks",
        layer_name="parks_nearby",
        steps_taken=3,
        execution_time=1.5
    )
    assert fa.steps_taken == 3
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/skfazlarabby/Documents/GitHub/AI-Geospatial
python -m pytest tests/test_agent_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.models.agent_model'`

- [ ] **Step 3: Create `app/models/agent_model.py`**

```python
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


class AgentRequest(BaseModel):
    question: str
    llm_provider: Optional[str] = "gemini"
    user_location: Optional[Dict[str, float]] = None
    drawn_geometry: Optional[Dict[str, Any]] = None
    selected_feature: Optional[Dict[str, Any]] = None
    max_iterations: int = 10

    class Config:
        json_schema_extra = {
            "example": {
                "question": "How many playgrounds are within 500m of Neukölln Rathaus?",
                "llm_provider": "gemini"
            }
        }


class AgentStep(BaseModel):
    type: Literal["thought", "action", "tool_result", "error"]
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None


class AgentFinalAnswer(BaseModel):
    geojson: Dict[str, Any]
    summary: str
    layer_name: str
    steps_taken: int
    execution_time: float
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
python -m pytest tests/test_agent_models.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add app/models/agent_model.py tests/test_agent_models.py
git commit -m "feat(agent): add Pydantic models for agentic query system"
```

---

## Task 2: Agent Tools

**Files:**
- Create: `app/utils/agent_tools.py`
- Create: `tests/test_agent_tools.py`

Each tool returns a plain dict with either `result` key (success) or `error` key (failure). The orchestrator passes the full dict back to the LLM as an Observation.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_tools.py
import pytest
from unittest.mock import patch, MagicMock
from app.utils.agent_tools import (
    geocode_location,
    create_buffer,
    get_schema_info,
    TOOL_REGISTRY,
)


def test_geocode_location_returns_coords():
    mock_result = {
        "name": "Neukölln Rathaus",
        "geometry": "POINT(13.4352 52.4823)",
        "bbox": [13.42, 52.47, 13.45, 52.49],
    }
    with patch("app.utils.agent_tools.location_resolver.resolve_location", return_value=mock_result):
        result = geocode_location("Neukölln Rathaus")
    assert result["lat"] == pytest.approx(52.4823, abs=0.01)
    assert result["lon"] == pytest.approx(13.4352, abs=0.01)
    assert "error" not in result


def test_geocode_location_not_found():
    with patch("app.utils.agent_tools.location_resolver.resolve_location", return_value=None):
        result = geocode_location("NonExistentPlace99999")
    assert "error" in result


def test_create_buffer_from_coords():
    result = create_buffer({"lat": 52.48, "lon": 13.43}, 500)
    assert result.get("type") == "Polygon"
    assert "coordinates" in result


def test_create_buffer_from_geojson_point():
    point = {"type": "Point", "coordinates": [13.43, 52.48]}
    result = create_buffer(point, 200)
    assert result.get("type") == "Polygon"


def test_get_schema_info_returns_tables():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = [
            {"table_name": "osm_parks", "description": "Parks in Berlin", "geometry_type": "MultiPolygon"}
        ]
        result = get_schema_info(["parks", "green"])
    assert isinstance(result, list)


def test_tool_registry_has_all_tools():
    expected = {
        "geocode_location", "create_buffer", "query_features",
        "spatial_filter", "get_schema_info", "calculate_route",
        "walking_isochrone", "analyze_satellite", "score_locations",
    }
    assert expected == set(TOOL_REGISTRY.keys())
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_agent_tools.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.utils.agent_tools'`

- [ ] **Step 3: Create `app/utils/agent_tools.py`**

```python
"""
Agent tools — each function does one thing and returns a plain dict.
Success: dict with result data.
Failure: dict with "error" key.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Union

from shapely.geometry import Point, shape, mapping
from shapely.ops import transform
import pyproj

from app.utils.location_resolver import LocationResolver
from app.utils.database import db_manager

logger = logging.getLogger(__name__)
location_resolver = LocationResolver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wkt_point_to_coords(wkt: str) -> Optional[Dict[str, float]]:
    """Extract lon/lat from WKT POINT string."""
    try:
        from shapely import wkt as swkt
        geom = swkt.loads(wkt)
        return {"lon": geom.x, "lat": geom.y}
    except Exception:
        return None


def _buffer_geometry(geom_wgs84, radius_m: int) -> Dict[str, Any]:
    """Buffer a shapely geometry (in WGS84) by radius_m metres. Returns GeoJSON dict."""
    project_to = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True).transform
    project_back = pyproj.Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True).transform
    projected = transform(project_to, geom_wgs84)
    buffered = projected.buffer(radius_m)
    back = transform(project_back, buffered)
    return mapping(back)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def geocode_location(name: str) -> Dict[str, Any]:
    """
    Geocode a place name to coordinates.

    Returns:
        {"lat": float, "lon": float, "display_name": str, "geometry": GeoJSON Point}
        or {"error": str}
    """
    try:
        result = location_resolver.resolve_location(name)
        if not result:
            return {"error": f"Location not found: {name}"}

        geometry_wkt = result.get("geometry", "")
        coords = _wkt_point_to_coords(geometry_wkt) if geometry_wkt else None

        # Fall back to bbox centre if point extraction fails
        if not coords:
            bbox = result.get("bbox")
            if bbox:
                coords = {"lon": (bbox[0] + bbox[2]) / 2, "lat": (bbox[1] + bbox[3]) / 2}
            else:
                return {"error": f"Could not extract coordinates from location: {name}"}

        return {
            "lat": coords["lat"],
            "lon": coords["lon"],
            "display_name": result.get("name", name),
            "geometry": {
                "type": "Point",
                "coordinates": [coords["lon"], coords["lat"]],
            },
        }
    except Exception as e:
        logger.error(f"geocode_location error: {e}")
        return {"error": str(e)}


def create_buffer(geometry_or_coords: Union[Dict, Any], radius_m: int) -> Dict[str, Any]:
    """
    Create a buffer polygon around a point or geometry.

    Args:
        geometry_or_coords: GeoJSON geometry dict OR {"lat": float, "lon": float}
        radius_m: Buffer radius in metres

    Returns:
        GeoJSON Polygon dict or {"error": str}
    """
    try:
        if isinstance(geometry_or_coords, dict):
            if "lat" in geometry_or_coords and "lon" in geometry_or_coords:
                lat, lon = geometry_or_coords["lat"], geometry_or_coords["lon"]
                geom = Point(lon, lat)
            elif "type" in geometry_or_coords:
                geom = shape(geometry_or_coords)
            else:
                return {"error": "geometry_or_coords must have lat/lon keys or be a GeoJSON geometry"}
        else:
            return {"error": "geometry_or_coords must be a dict"}

        return _buffer_geometry(geom, radius_m)
    except Exception as e:
        logger.error(f"create_buffer error: {e}")
        return {"error": str(e)}


def get_schema_info(keywords: List[str]) -> Union[List[Dict], Dict]:
    """
    Return relevant table names and descriptions matching the given keywords.

    Returns:
        List of {"table_name": str, "description": str, "geometry_type": str}
        or {"error": str}
    """
    try:
        keyword_conditions = " OR ".join(
            f"(LOWER(table_name) LIKE '%{kw.lower()}%' OR LOWER(description) LIKE '%{kw.lower()}%')"
            for kw in keywords
        )
        sql = f"""
            SELECT table_name, description, geometry_type
            FROM vector.table_metadata
            WHERE {keyword_conditions}
            LIMIT 10
        """
        rows = db_manager.execute_query(sql)
        if rows is None:
            return {"error": "Database query failed"}
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_schema_info error: {e}")
        return {"error": str(e)}


def query_features(description: str, within_geometry: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Query the PostGIS database for features matching a natural language description,
    optionally filtered to within a GeoJSON geometry.

    Uses the existing LLM→SQL pipeline (sql_generator) to translate the description
    into SQL, then executes it.

    Returns:
        {"type": "FeatureCollection", "features": [...], "count": int}
        or {"error": str}
    """
    try:
        from app.utils.deepseek import parse_geospatial_query
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import NLQuery

        # Build the query, injecting the geometry as context if provided
        full_question = description
        if within_geometry:
            geom_str = json.dumps(within_geometry)
            full_question = f"{description}. Only return features within this geometry: {geom_str[:300]}"

        nl_query = NLQuery(
            question=full_question,
            drawn_geometry=within_geometry,
        )

        plan = parse_geospatial_query(
            nl_query.question,
            context=None,
            user_location=None,
            selected_feature=None,
            drawn_geometry=within_geometry,
        )

        engine = SpatialEngine()
        result = engine.execute_plan(plan)

        if result.get("success") is False:
            return {"error": result.get("error", "Query returned no results")}

        data = result.get("data", {})
        features = data.get("features", []) if isinstance(data, dict) else []
        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
        }
    except Exception as e:
        logger.error(f"query_features error: {e}")
        return {"error": str(e)}


def spatial_filter(
    features: Dict[str, Any],
    filter_geometry: Dict[str, Any],
    relation: str = "within",
) -> Dict[str, Any]:
    """
    Filter a GeoJSON FeatureCollection to only features that are within or
    intersect a given geometry.

    Args:
        features: GeoJSON FeatureCollection
        filter_geometry: GeoJSON geometry (e.g. a buffer polygon)
        relation: "within" or "intersects"

    Returns:
        {"type": "FeatureCollection", "features": [...], "count": int}
        or {"error": str}
    """
    try:
        filter_shape = shape(filter_geometry)
        result_features = []
        for feat in features.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            feat_shape = shape(geom)
            if relation == "within" and feat_shape.within(filter_shape):
                result_features.append(feat)
            elif relation == "intersects" and feat_shape.intersects(filter_shape):
                result_features.append(feat)
        return {
            "type": "FeatureCollection",
            "features": result_features,
            "count": len(result_features),
        }
    except Exception as e:
        logger.error(f"spatial_filter error: {e}")
        return {"error": str(e)}


def calculate_route(waypoints: List[Dict[str, float]], mode: str = "driving") -> Dict[str, Any]:
    """
    Calculate the optimal route between waypoints using pgRouting.

    Args:
        waypoints: List of {"lat": float, "lon": float, "name": str} dicts
        mode: "driving" or "walking"

    Returns:
        {"type": "FeatureCollection", "features": [LineString route], "distance_m": float, "duration_s": float}
        or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan, GeospatialOperation

        engine = SpatialEngine()
        op = GeospatialOperation(
            operation="routing",
            parameters={
                "waypoints": waypoints,
                "mode": mode,
            },
            description=f"Route between {len(waypoints)} waypoints",
        )
        plan = OperationPlan(operations=[op], reasoning="Agent-requested routing")
        result = engine._execute_routing_operation(op, plan)

        if not result.get("success"):
            return {"error": result.get("error", "Routing failed")}

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": result.get("geometry", {}),
                    "properties": {
                        "distance_m": result.get("total_distance_m", 0),
                        "duration_s": (result.get("total_time_minutes", 0) or 0) * 60,
                    },
                }
            ],
            "distance_m": result.get("total_distance_m", 0),
            "duration_s": (result.get("total_time_minutes", 0) or 0) * 60,
        }
    except Exception as e:
        logger.error(f"calculate_route error: {e}")
        return {"error": str(e)}


def walking_isochrone(location: Dict[str, float], minutes: int) -> Dict[str, Any]:
    """
    Calculate the area reachable by walking from a location within N minutes.

    Args:
        location: {"lat": float, "lon": float}
        minutes: Walking time in minutes

    Returns:
        {"type": "FeatureCollection", "features": [Polygon isochrone]}
        or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan, GeospatialOperation

        engine = SpatialEngine()
        op = GeospatialOperation(
            operation="walking_time",
            parameters={
                "origin": location,
                "time_minutes": minutes,
            },
            description=f"{minutes}-minute walking isochrone",
        )
        plan = OperationPlan(operations=[op], reasoning="Agent-requested isochrone")
        result = engine._execute_walking_time_operation(op, plan)

        if not result.get("success"):
            return {"error": result.get("error", "Isochrone failed")}

        return result.get("data", {"type": "FeatureCollection", "features": []})
    except Exception as e:
        logger.error(f"walking_isochrone error: {e}")
        return {"error": str(e)}


def analyze_satellite(
    bbox: Dict[str, Any],
    indices: List[str],
    date_range: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run satellite spectral analysis over a bounding box.

    Args:
        bbox: GeoJSON Polygon or {"min_lon", "min_lat", "max_lon", "max_lat"}
        indices: List of spectral indices, e.g. ["NDVI", "NDWI"]
        date_range: Optional {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

    Returns:
        {"type": "FeatureCollection", "features": [...], "stats": {...}}
        or {"error": str}
    """
    try:
        from app.utils.satellite_processor import SatelliteProcessor

        if isinstance(bbox, dict) and "type" in bbox:
            geom = shape(bbox)
            bounds = geom.bounds  # (min_lon, min_lat, max_lon, max_lat)
        elif all(k in bbox for k in ("min_lon", "min_lat", "max_lon", "max_lat")):
            bounds = (bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"])
        else:
            return {"error": "bbox must be a GeoJSON Polygon or dict with min_lon/min_lat/max_lon/max_lat"}

        processor = SatelliteProcessor()
        result = processor.analyze_area(
            bounds=bounds,
            indices=indices,
            date_range=date_range,
        )
        if result is None:
            return {"error": "No satellite data found for this area and time range"}
        return result
    except Exception as e:
        logger.error(f"analyze_satellite error: {e}")
        return {"error": str(e)}


def score_locations(features: Dict[str, Any], criteria: List[str]) -> Dict[str, Any]:
    """
    Score and rank GeoJSON features using MCDA (Multi-Criteria Decision Analysis).

    Args:
        features: GeoJSON FeatureCollection
        criteria: List of scoring criteria, e.g. ["near schools", "low noise", "high footfall"]

    Returns:
        GeoJSON FeatureCollection with added "score" property
        or {"error": str}
    """
    try:
        from app.utils.spatial_engine import SpatialEngine
        from app.models.query_model import OperationPlan
        import geopandas as gpd

        gdf = gpd.GeoDataFrame.from_features(features.get("features", []), crs="EPSG:4326")
        if gdf.empty:
            return {"error": "No features to score"}

        engine = SpatialEngine()
        query_str = ", ".join(criteria)
        plan = OperationPlan(operations=[], reasoning=query_str)
        scored_gdf = engine.apply_mcda_scoring(gdf, query_str, plan)

        return json.loads(scored_gdf.to_json())
    except Exception as e:
        logger.error(f"score_locations error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to callables for the orchestrator
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    "geocode_location": geocode_location,
    "create_buffer": create_buffer,
    "query_features": query_features,
    "spatial_filter": spatial_filter,
    "get_schema_info": get_schema_info,
    "calculate_route": calculate_route,
    "walking_isochrone": walking_isochrone,
    "analyze_satellite": analyze_satellite,
    "score_locations": score_locations,
}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_agent_tools.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): add 9 agent tools wrapping existing spatial utilities"
```

---

## Task 3: Agent Orchestrator

**Files:**
- Create: `app/utils/agent_orchestrator.py`
- Create: `tests/test_agent_orchestrator.py`

The orchestrator runs the ReAct loop, calling the LLM and dispatching tools. It is an **async generator** — it `yield`s `AgentStep` objects so the route can stream them as SSE.

- [ ] **Step 1: Write the failing tests (parsing only — no LLM/DB)**

```python
# tests/test_agent_orchestrator.py
import pytest
from app.utils.agent_orchestrator import (
    _parse_llm_output,
    _build_agent_system_prompt,
    _truncate_result,
)


def test_parse_thought_and_action():
    raw = """Thought: I need to geocode the location first.
Action: geocode_location
Args: {"name": "Neukölln Rathaus"}"""
    parsed = _parse_llm_output(raw)
    assert parsed["type"] == "action"
    assert parsed["thought"] == "I need to geocode the location first."
    assert parsed["tool"] == "geocode_location"
    assert parsed["args"] == {"name": "Neukölln Rathaus"}


def test_parse_final_answer():
    raw = """Thought: I have all the data I need.
Final Answer:
{"type": "FeatureCollection", "features": []}
Summary: Found 0 results.
Layer: test_layer"""
    parsed = _parse_llm_output(raw)
    assert parsed["type"] == "final_answer"
    assert parsed["geojson"]["type"] == "FeatureCollection"
    assert parsed["summary"] == "Found 0 results."
    assert parsed["layer"] == "test_layer"


def test_parse_final_answer_missing_features_key():
    """Final answer with a bare GeoJSON object should still parse."""
    raw = """Final Answer:
{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": null, "properties": {}}]}
Summary: One result.
Layer: my_layer"""
    parsed = _parse_llm_output(raw)
    assert parsed["type"] == "final_answer"
    assert len(parsed["geojson"]["features"]) == 1


def test_parse_unknown_returns_retry():
    raw = "I'm not sure what to do here."
    parsed = _parse_llm_output(raw)
    assert parsed["type"] == "retry"


def test_system_prompt_contains_all_tools():
    prompt = _build_agent_system_prompt()
    for tool in ["geocode_location", "create_buffer", "query_features",
                 "spatial_filter", "get_schema_info", "calculate_route",
                 "walking_isochrone", "analyze_satellite", "score_locations"]:
        assert tool in prompt


def test_truncate_result_long_dict():
    big = {"features": [{"id": i} for i in range(500)]}
    truncated = _truncate_result(big)
    assert len(str(truncated)) < 3000
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_agent_orchestrator.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `app/utils/agent_orchestrator.py`**

```python
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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


def _call_llm(messages: list, provider: str) -> str:
    """Call Gemini or DeepSeek with a message list. Returns raw text."""
    if provider == "gemini" and GEMINI_API_KEY:
        # Convert OpenAI-style messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    elif DEEPSEEK_API_KEY:
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

    raise RuntimeError("No LLM provider available. Set GEMINI_API_KEY or DEEPSEEK_API_KEY.")


def _truncate_result(result: Any, max_chars: int = MAX_RESULT_CHARS) -> Any:
    """
    If a tool result is too large to fit in the context window, trim it.
    For FeatureCollections, keep the first 5 features and add a count summary.
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
        {"type": "retry", "raw": str}   — unparseable; caller should nudge LLM
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
            # Extract JSON block (may be multi-line)
            json_match = re.search(r"(\{.*?\}|\[.*?\])", after_fa, re.DOTALL)
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
    args_match = re.search(r"Args:\s*(\{.*?\}|\[.*?\])", raw, re.DOTALL)

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
    The final item yielded has type "final_answer" with the GeoJSON result.
    """
    start_time = time.time()

    # Build initial message history
    system_prompt = _build_agent_system_prompt()
    user_content = question
    if user_location:
        user_content += f"\n\nUser location: lat={user_location['lat']}, lon={user_location['lon']}"
    if drawn_geometry:
        user_content += f"\n\nUser drew this geometry on the map (use as spatial context): {json.dumps(drawn_geometry)[:300]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    retry_count = 0
    max_retries = 2

    for iteration in range(max_iterations):
        # Call the LLM
        try:
            raw = _call_llm(messages, llm_provider)
        except Exception as e:
            yield AgentStep(type="error", content=f"LLM call failed: {e}")
            return

        parsed = _parse_llm_output(raw)

        if parsed["type"] == "retry":
            retry_count += 1
            if retry_count > max_retries:
                yield AgentStep(type="error", content="Agent could not produce a valid response. Please rephrase your question.")
                return
            # Nudge the LLM back on track
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Please respond using exactly the required format:\nThought: ...\nAction: ...\nArgs: {...}\n\nor if done:\nThought: ...\nFinal Answer:\n{GeoJSON}\nSummary: ...\nLayer: ..."
            })
            continue

        retry_count = 0  # Reset on successful parse

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

        # It's an action — execute the tool
        tool_name = parsed["tool"]
        tool_args = parsed.get("args", {})

        yield AgentStep(
            type="action",
            content=f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)[:200]})",
            tool_name=tool_name,
            tool_args=tool_args,
        )

        if tool_name not in TOOL_REGISTRY:
            observation = {"error": f"Unknown tool: {tool_name}. Available tools: {list(TOOL_REGISTRY.keys())}"}
        else:
            try:
                tool_fn = TOOL_REGISTRY[tool_name]
                # Tools are sync — run directly (they are fast DB/network calls)
                if isinstance(tool_args, dict):
                    observation = tool_fn(**tool_args)
                else:
                    observation = {"error": f"Args must be a JSON object, got: {type(tool_args)}"}
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

        # Append assistant action + observation to message history
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation: {obs_str}"})

    # Max iterations reached
    yield AgentStep(
        type="error",
        content=f"Agent reached max iterations ({max_iterations}) without a final answer. Try a simpler question.",
    )
```

- [ ] **Step 4: Run orchestrator tests**

```bash
python -m pytest tests/test_agent_orchestrator.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_orchestrator.py tests/test_agent_orchestrator.py
git commit -m "feat(agent): add ReAct orchestrator with LLM loop and parser"
```

---

## Task 4: Agent SSE Route

**Files:**
- Create: `app/routes/agent.py`
- Create: `tests/test_agent_route.py`

Uses FastAPI `StreamingResponse` with `text/event-stream`. No extra dependencies needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_route.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


def _mock_agent_steps():
    """Yield fake agent steps for mocking."""
    from app.models.agent_model import AgentStep, AgentFinalAnswer
    yield AgentStep(type="thought", content="I need to geocode.")
    yield AgentStep(type="action", content="geocode_location(...)", tool_name="geocode_location")
    yield AgentStep(
        type="tool_result",
        content="final_answer",
        tool_name="final_answer",
        tool_result=AgentFinalAnswer(
            geojson={"type": "FeatureCollection", "features": []},
            summary="Done",
            layer_name="test",
            steps_taken=1,
            execution_time=0.1,
        ).model_dump(),
    )


def test_agent_query_returns_sse_stream():
    """Route should return text/event-stream content type."""
    async def mock_run_agent(*args, **kwargs):
        for step in _mock_agent_steps():
            yield step

    with patch("app.routes.agent.run_agent", side_effect=mock_run_agent):
        client = TestClient(app)
        resp = client.post(
            "/api/agent/query",
            json={"question": "Find parks near me"},
            headers={"Accept": "text/event-stream"},
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_agent_query_rejects_empty_question():
    client = TestClient(app)
    resp = client.post("/api/agent/query", json={"question": ""})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_agent_route.py -v
```
Expected: route not found (404) or import error.

- [ ] **Step 3: Create `app/routes/agent.py`**

```python
"""
Agent route — POST /api/agent/query

Streams ReAct agent steps as Server-Sent Events (SSE).
Each SSE event is a JSON-encoded AgentStep.

Event format:
    data: {"type": "thought", "content": "...", ...}\n\n
    data: {"type": "action", "tool_name": "...", ...}\n\n
    data: {"type": "tool_result", "tool_name": "...", "tool_result": ...}\n\n
    data: {"type": "error", "content": "..."}\n\n
"""
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import validator

from app.models.agent_model import AgentRequest, AgentStep
from app.utils.agent_orchestrator import run_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


async def _sse_generator(request: AgentRequest) -> AsyncGenerator[str, None]:
    """Wrap the agent generator as SSE-formatted text chunks."""
    try:
        async for step in run_agent(
            question=request.question,
            llm_provider=request.llm_provider or "gemini",
            max_iterations=request.max_iterations,
            user_location=request.user_location,
            drawn_geometry=request.drawn_geometry,
        ):
            payload = step.model_dump()
            yield f"data: {json.dumps(payload, default=str)}\n\n"
    except Exception as e:
        logger.error(f"Agent SSE error: {e}")
        error_step = AgentStep(type="error", content=str(e))
        yield f"data: {json.dumps(error_step.model_dump())}\n\n"
    finally:
        yield "data: {\"type\": \"done\"}\n\n"


@router.post("/query")
async def agent_query(request: AgentRequest) -> StreamingResponse:
    """
    Process a natural language geospatial query using the ReAct agent.

    Streams Server-Sent Events. Each event is a JSON AgentStep.
    The final event with type="tool_result" and tool_name="final_answer"
    contains the GeoJSON FeatureCollection to render on the map.
    """
    if not request.question.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="question must not be empty")

    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Register the router in `app/main.py`**

Add these two lines to `app/main.py`:

After the existing imports block (around line 17), add:
```python
from app.routes.agent import router as agent_router
```

After `app.include_router(skills_router)` (around line 105), add:
```python
app.include_router(agent_router)           # Agentic query endpoint
```

- [ ] **Step 5: Run the route tests**

```bash
python -m pytest tests/test_agent_route.py -v
```
Expected: `2 passed`

- [ ] **Step 6: Smoke test the server**

```bash
uvicorn app.main:app --reload --port 8000
```

In a second terminal:
```bash
curl -N -X POST http://localhost:8000/api/agent/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Find all parks in Mitte"}' 
```
Expected: stream of `data: {...}` lines ending with `data: {"type": "done"}`.

- [ ] **Step 7: Commit**

```bash
git add app/routes/agent.py app/main.py tests/test_agent_route.py
git commit -m "feat(agent): add SSE streaming route POST /api/agent/query"
```

---

## Task 5: Frontend — Agent Progress Panel + SSE Client

**Files:**
- Modify: `frontend/index.html`

Add an agent panel and SSE client. The panel shows Thought/Action/Result in real-time. When the `final_answer` step arrives, render the GeoJSON on the map exactly as the existing `addLayer()` call does.

- [ ] **Step 1: Add the agent panel HTML**

Find the existing search bar in `frontend/index.html` (search for `id="search-input"` or the main query form). Add this panel directly after the search bar container:

```html
<!-- Agent Progress Panel -->
<div id="agent-panel" style="display:none; background:#0d0d1a; border:1px solid #333; border-radius:10px; margin-top:8px; font-size:13px; max-height:400px; overflow-y:auto;">
  <div style="padding:8px 12px; border-bottom:1px solid #222; display:flex; justify-content:space-between; align-items:center;">
    <span style="color:#888; font-size:11px; text-transform:uppercase; letter-spacing:1px;">Agent Reasoning</span>
    <span id="agent-panel-toggle" style="color:#555; cursor:pointer; font-size:11px;" onclick="toggleAgentPanel()">[ hide ]</span>
  </div>
  <div id="agent-steps" style="padding:10px 12px; display:flex; flex-direction:column; gap:8px;"></div>
</div>
```

- [ ] **Step 2: Add the CSS for agent step badges**

In the `<style>` block of `frontend/index.html`, add:

```css
.agent-step { display: flex; gap: 8px; align-items: flex-start; }
.agent-badge {
  font-size: 10px; padding: 2px 7px; border-radius: 4px;
  white-space: nowrap; margin-top: 2px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-thought { background: #2a1e3e; color: #8a70d9; }
.badge-action  { background: #1e3a1e; color: #60c060; }
.badge-result  { background: #2a1e0e; color: #d08050; }
.badge-error   { background: #3a1e1e; color: #e07070; }
.agent-content { color: #ccc; line-height: 1.5; word-break: break-word; }
```

- [ ] **Step 3: Add the SSE client JavaScript**

Find the closing `</script>` tag in `frontend/index.html` and add the following **before** it:

```javascript
// ─── Agent SSE Client ────────────────────────────────────────────────────────

let _agentPanelVisible = localStorage.getItem('agentPanelVisible') !== 'false';

function toggleAgentPanel() {
  _agentPanelVisible = !_agentPanelVisible;
  localStorage.setItem('agentPanelVisible', _agentPanelVisible);
  const steps = document.getElementById('agent-steps');
  const toggle = document.getElementById('agent-panel-toggle');
  if (steps) steps.style.display = _agentPanelVisible ? 'flex' : 'none';
  if (toggle) toggle.textContent = _agentPanelVisible ? '[ hide ]' : '[ show ]';
}

function _appendAgentStep(type, content) {
  const container = document.getElementById('agent-steps');
  if (!container) return;
  const badgeClass = { thought: 'badge-thought', action: 'badge-action',
                        tool_result: 'badge-result', error: 'badge-error' }[type] || 'badge-result';
  const label = { thought: 'Thought', action: 'Action',
                   tool_result: 'Result', error: 'Error' }[type] || type;
  const div = document.createElement('div');
  div.className = 'agent-step';
  div.innerHTML = `
    <span class="agent-badge ${badgeClass}">${label}</span>
    <span class="agent-content">${String(content).slice(0, 400)}</span>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

async function submitAgentQuery(question, llmProvider) {
  const panel = document.getElementById('agent-panel');
  const stepsContainer = document.getElementById('agent-steps');
  if (panel) panel.style.display = 'block';
  if (stepsContainer) stepsContainer.innerHTML = '';

  const payload = {
    question,
    llm_provider: llmProvider || 'gemini',
    max_iterations: 10,
  };

  // Include drawn geometry if present
  if (window._drawnGeometry) payload.drawn_geometry = window._drawnGeometry;
  if (window._userLocation) payload.user_location = window._userLocation;

  let finalAnswerHandled = false;

  try {
    const response = await fetch('/api/agent/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE lines
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;

        let step;
        try { step = JSON.parse(raw); } catch { continue; }

        if (step.type === 'done') break;

        if (step.type === 'thought') {
          _appendAgentStep('thought', step.content);
        } else if (step.type === 'action') {
          _appendAgentStep('action', step.content);
        } else if (step.type === 'tool_result' && step.tool_name !== 'final_answer') {
          const content = typeof step.tool_result === 'object'
            ? JSON.stringify(step.tool_result).slice(0, 300)
            : String(step.content).slice(0, 300);
          _appendAgentStep('tool_result', content);
        } else if (step.type === 'tool_result' && step.tool_name === 'final_answer') {
          const fa = step.tool_result;
          _appendAgentStep('tool_result',
            `✅ ${fa.summary} (${(fa.geojson.features || []).length} features · ${fa.execution_time}s)`);

          // Render on map using existing addLayer function
          if (fa.geojson && typeof addLayer === 'function') {
            addLayer(fa.layer_name, fa.geojson, question, [], fa.summary, [], {}, fa.execution_time);
          }
          finalAnswerHandled = true;
        } else if (step.type === 'error') {
          _appendAgentStep('error', step.content);
        }
      }
    }
  } catch (err) {
    _appendAgentStep('error', `Connection error: ${err.message}`);
  }
}
```

- [ ] **Step 4: Wire the agent toggle to the existing query form**

Find the existing query submit handler (search for `fetch('/api/query'` in `frontend/index.html`). Add an "Agent" mode toggle button next to the existing submit button:

```html
<button id="agent-mode-btn" onclick="window._useAgent = !window._useAgent; this.textContent = window._useAgent ? '🤖 Agent ON' : '🤖 Agent OFF'; this.style.background = window._useAgent ? '#2a5a2a' : '';" 
  style="background:#222; color:#aaa; border:1px solid #444; border-radius:6px; padding:6px 12px; cursor:pointer; font-size:12px;">
  🤖 Agent OFF
</button>
```

Then in the existing submit handler, add at the top:

```javascript
if (window._useAgent) {
  const provider = document.getElementById('llm-provider-select')?.value || 'gemini';
  submitAgentQuery(question, provider);
  return;
}
// ... rest of existing handler continues unchanged
```

- [ ] **Step 5: Test in browser**

1. Start the server: `uvicorn app.main:app --reload`
2. Open `http://localhost:8000`
3. Click the "🤖 Agent OFF" button to toggle to "🤖 Agent ON"
4. Type: "Show me all parks within 1 km of Brandenburg Gate"
5. Observe the agent panel appear with streaming Thought → Action → Result steps
6. Verify the final GeoJSON appears on the Leaflet map
7. Toggle "🤖 Agent OFF" — next query uses the old `/api/query` endpoint

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(agent): add SSE client and agent progress panel to frontend"
```

---

## Task 6: Integration Smoke Test

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/test_agent_models.py tests/test_agent_tools.py tests/test_agent_orchestrator.py tests/test_agent_route.py -v
```
Expected: all tests pass.

- [ ] **Step 2: End-to-end agent test via curl**

```bash
curl -N -X POST http://localhost:8000/api/agent/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How many playgrounds are within 500 meters of the Neukölln Rathaus?"}' \
  2>/dev/null | grep "^data:" | head -30
```

Expected output (order may vary):
```
data: {"type": "thought", "content": "I need to geocode Neukölln Rathaus first..."}
data: {"type": "action", "content": "geocode_location({\"name\": \"Neukölln Rathaus\"})", ...}
data: {"type": "tool_result", "tool_name": "geocode_location", ...}
data: {"type": "thought", "content": "Now I'll create a 500m buffer..."}
data: {"type": "action", "content": "create_buffer(...)", ...}
data: {"type": "tool_result", "tool_name": "create_buffer", ...}
data: {"type": "action", "content": "query_features(...)", ...}
data: {"type": "tool_result", "tool_name": "final_answer", ...}
data: {"type": "done"}
```

- [ ] **Step 3: Verify the final GeoJSON renders on the map**

Open `http://localhost:8000` in browser, enable agent mode, submit the same query. Confirm playground features appear as map layer.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat(agent): complete agentic geospatial system with ReAct loop and SSE streaming"
```

---

## Self-Review

**Spec coverage:**
- ✅ ReAct loop (Thought→Action→Observation) — `agent_orchestrator.py`
- ✅ SSE streaming — `agent.py` + `StreamingResponse`
- ✅ Real-time progress (debug mode) — frontend panel
- ✅ Final output always GeoJSON on map — `submitAgentQuery` calls `addLayer()`
- ✅ All 9 tools — `agent_tools.py` with TOOL_REGISTRY
- ✅ Old `/api/query` untouched — still available via Agent OFF toggle
- ✅ Max iterations limit (10) — prevents infinite loops
- ✅ Error recovery — each tool returns `{"error": ...}` which LLM can react to

**Placeholder scan:** No TBDs or TODOs found.

**Type consistency:**
- `AgentStep.type` literals match badge rendering in frontend
- `AgentFinalAnswer.model_dump()` produces dict consumed by frontend `fa.geojson`, `fa.summary`, `fa.layer_name`
- `TOOL_REGISTRY` keys match the tool names in the system prompt exactly
- `run_agent()` is async generator — `_sse_generator()` uses `async for` correctly
