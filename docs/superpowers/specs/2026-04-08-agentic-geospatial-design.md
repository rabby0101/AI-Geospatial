# Agentic Geospatial System Design

**Date:** 2026-04-08  
**Status:** Approved for implementation

---

## Context

The current app uses a monolithic 5-phase LLM pipeline that generates SQL for the entire problem in a single call. This approach breaks on complex multi-step questions (e.g., "How many playgrounds are within 500m of Neukölln Rathaus?") because the LLM must simultaneously geocode a location, build a spatial buffer, and count features — producing SQL that is hallucination-prone and difficult to debug.

The goal is to replace this with a **ReAct agent** (Reason + Act) that breaks queries into discrete tool calls, each doing one thing reliably, with real-time streaming progress to the frontend.

---

## Architecture

### Core Pattern: ReAct Loop

The agent runs a loop of:

```
Thought → Action → Observation → (repeat) → Final Answer
```

1. LLM receives the user question and the full conversation history (thoughts + observations so far)
2. LLM outputs either:
   - A **Thought** (reasoning text) + **Action** (tool name + JSON args)
   - A **Final Answer** (GeoJSON FeatureCollection + summary text)
3. Python parses the action, executes the tool, appends the **Observation** (tool result) to context
4. Loop repeats until Final Answer is produced
5. Final Answer GeoJSON is rendered on the map

### Endpoints

- **New:** `POST /api/agent/query` — SSE streaming endpoint for the ReAct agent
- **Keep:** `POST /api/query` — existing pipeline untouched; used as fallback during agent maturation

The frontend will have a toggle to switch between the two.

### SSE Event Types

Each event is streamed as `data: <json>\n\n`:

| Event type | Payload | When emitted |
|---|---|---|
| `thought` | `{ text }` | LLM reasoning step |
| `action` | `{ tool, args }` | LLM calls a tool |
| `tool_result` | `{ tool, result, error? }` | Tool execution completes |
| `final_answer` | `{ geojson, summary, layer_name, steps_taken }` | Agent is done |
| `error` | `{ message }` | Unrecoverable failure |

---

## Tools

All tools return structured JSON. Tools that produce geometry always include it as GeoJSON.

| Tool | Input | Output | Backend |
|---|---|---|---|
| `geocode_location` | `name: str` | `{ lat, lon, display_name, geometry }` | Nominatim (existing `location_resolver.py`) |
| `create_buffer` | `geometry_or_coords, radius_m: int` | `{ geojson: Polygon }` | PostGIS ST_Buffer |
| `query_features` | `description: str, within_geometry?: GeoJSON` | `{ geojson: FeatureCollection, count }` | LLM→SQL→PostGIS (reuses `sql_generator.py`) |
| `spatial_filter` | `features: GeoJSON, filter_geometry: GeoJSON, relation: within\|intersects` | `{ geojson: FeatureCollection, count }` | PostGIS |
| `get_schema_info` | `keywords: list[str]` | `{ tables: [...] }` | DB metadata (reuses existing schema fetch) |
| `calculate_route` | `waypoints: list[coords], mode: driving\|walking` | `{ geojson: LineString, distance_m, duration_s }` | pgRouting (reuses `spatial_engine.py`) |
| `walking_isochrone` | `location: coords, minutes: int` | `{ geojson: Polygon }` | Valhalla (reuses `spatial_engine.py`) |
| `analyze_satellite` | `bbox: GeoJSON, indices: list[str], date_range?` | `{ geojson: FeatureCollection, stats }` | Sentinel-2 (reuses `satellite_processor.py`) |
| `score_locations` | `features: GeoJSON, criteria: list[str]` | `{ geojson: FeatureCollection }` — with score property | MCDA (reuses `spatial_engine.py`) |

Tools are implemented as plain Python functions in `agent_tools.py`. Each wraps existing utility code — no new spatial logic is written.

---

## LLM Prompt Design

### System Prompt (sent once)

```
You are a geospatial AI agent. You answer questions by calling tools one at a time.

For each step, output exactly:
Thought: <your reasoning>
Action: <tool_name>
Args: <json args>

When you have enough information to answer, output:
Final Answer:
<GeoJSON FeatureCollection as JSON>
Summary: <one sentence>
Layer: <snake_case layer name>

Available tools:
- geocode_location(name) → coordinates
- create_buffer(geometry_or_coords, radius_m) → polygon
- query_features(description, within_geometry?) → features
- spatial_filter(features, filter_geometry, relation) → features
- get_schema_info(keywords) → table info
- calculate_route(waypoints, mode) → route
- walking_isochrone(location, minutes) → polygon
- analyze_satellite(bbox, indices, date_range?) → stats
- score_locations(features, criteria) → ranked features

Rules:
- Always call geocode_location before using a place name in any other tool
- The Final Answer MUST be a valid GeoJSON FeatureCollection
- Never guess coordinates — always geocode named places
- Call tools one at a time; wait for the result before continuing
```

### Context window per iteration

Each LLM call receives: system prompt + user question + full history of prior thoughts/actions/observations. Max iterations: 10 (safety limit to prevent infinite loops).

---

## Files

### New files

| File | Purpose |
|---|---|
| `app/routes/agent.py` | `POST /api/agent/query` SSE endpoint; runs `AgentOrchestrator` and streams events |
| `app/utils/agent_orchestrator.py` | ReAct loop: calls LLM, parses Thought/Action/Final Answer, dispatches tools, manages context |
| `app/utils/agent_tools.py` | All 9 tool functions; each wraps existing utility code |
| `app/models/agent_model.py` | `AgentRequest`, `AgentStep`, `AgentFinalAnswer` Pydantic models |

### Modified files

| File | Change |
|---|---|
| `app/main.py` | Register `agent` router |
| `frontend/index.html` | Add SSE client; agent progress panel (collapsible); toggle between old and new endpoint |

### Existing code reused (not modified)

- `app/utils/location_resolver.py` — `geocode_location` tool wraps this
- `app/utils/sql_generator.py` — `query_features` tool reuses `SQLQueryGenerator`
- `app/utils/spatial_engine.py` — routing, isochrone, MCDA tools reuse this
- `app/utils/satellite_processor.py` — `analyze_satellite` tool reuses this
- `app/utils/deepseek.py` — orchestrator reuses `query_gemini` / `query_deepseek` for LLM calls

---

## Error Handling

- **Tool failure:** Tool returns `{ error: "..." }`; orchestrator appends error as observation; LLM can try a different approach
- **Max iterations reached (10):** Stream an `error` event; return partial results if any GeoJSON was collected
- **LLM parse failure:** If LLM output can't be parsed as Thought/Action or Final Answer, retry once with a nudge ("Please respond with Thought: / Action: / Args: format")
- **No GeoJSON in Final Answer:** Return an error event asking the user to rephrase

---

## Frontend Changes

### Agent panel (debug mode)

- Collapsible panel below the search bar
- Streams each `thought`, `action`, `tool_result` event as a row
- Color-coded: purple=thought, green=action, orange=result
- Final answer row shows feature count + timing
- "Hide agent steps" toggle (persisted to localStorage)

### Endpoint toggle

- Small toggle in settings: "Use agent (new)" vs "Use pipeline (classic)"
- Defaults to agent; falls back to classic on error

---

## Verification

1. Start the server: `uvicorn app.main:app --reload`
2. Open `frontend/index.html`
3. Type: "Show me all parks within 1km of Brandenburg Gate" — agent should geocode, buffer, query, return GeoJSON on map
4. Type: "Find the 5 nearest hospitals to my location and route between them" — agent should use `geocode`, `query_features`, `calculate_route`
5. Check SSE events appear in agent panel with correct color-coding
6. Toggle "Hide agent steps" — panel collapses, map result stays
7. Switch to classic pipeline via toggle — old `/api/query` endpoint used
8. Confirm both endpoints return valid GeoJSON that renders on the Leaflet map
