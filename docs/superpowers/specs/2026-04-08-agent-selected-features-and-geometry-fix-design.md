# Agent: Selected Features Context + Geometry Column Fixes

**Date:** 2026-04-08  
**Branch:** feature/skills-system

---

## Context

Two bugs in agent mode:

1. **Selected features context missing** — When a user selects features on the map and asks a question like "show cafes within 300m of those selected items", the agent fails. The frontend creates a temp PostGIS table (`temp.temp_selected_{session_id}`) but never tells the agent about it. The agent query payload omits `session_id` and selected feature data, so the LLM has no context about what was selected.

2. **Geometry column missed / partial column selection** — The agent sometimes generates `SELECT name, amenity FROM vector.table` (specific columns) instead of `SELECT *`, dropping all other feature attributes. Worse, `get_table_columns` returns columns in DB ordinal order with LIMIT 40 — OSM tables have 50+ columns and `geom_25833` sits near the end, so it is never returned. The agent then writes SQL with no geometry column or uses the wrong one (`geometry` instead of `geom_25833`).

---

## Fix 1 — Pass Selected Features Context to Agent

### Data flow today

```
Frontend selects features → addFeatureToSelection() captures {geometry, properties, name}
→ updateAllSelectedFeatures() POSTs geometries to /api/create-temp-layer
→ temp.temp_selected_{session_id} created in DB (only geometry+id, no properties)

Agent query payload: {question, llm_provider, max_iterations}  ← NO session_id, NO features
→ run_agent() has no awareness of selection
→ get_schema_info() only reads metadata.table_descriptions, never temp schema
→ Agent has no way to know selected features exist
```

### Changes

**`frontend/index.html`** (~line 9397)

Add to agent query payload:
```js
if (window.sessionId) payload.session_id = window.sessionId;
if (selectedFeatures.length > 0) payload.selected_features = selectedFeatures;
// selectedFeatures = [{geometry, properties, name}, ...] — already captured on click
```

**`app/models/agent_model.py`**

Add two fields to `AgentRequest`:
```python
session_id: Optional[str] = None
selected_features: Optional[List[Dict[str, Any]]] = None
```

**`app/routes/agent.py`**

Forward new fields in `_sse_generator()` call to `run_agent()`:
```python
async for step in run_agent(
    ...
    session_id=request.session_id,
    selected_features=request.selected_features,
):
```

**`app/utils/agent_orchestrator.py`** — `run_agent()`

Add parameters:
```python
async def run_agent(
    question: str,
    llm_provider: str = "deepseek",
    max_iterations: int = 15,
    user_location: Optional[Dict] = None,
    drawn_geometry: Optional[Dict] = None,
    session_id: Optional[str] = None,
    selected_features: Optional[List[Dict]] = None,
) -> AsyncGenerator[AgentStep, None]:
```

Inject into `user_content` after existing drawn_geometry block:
```python
if selected_features:
    lines = []
    for i, feat in enumerate(selected_features[:10]):  # cap at 10
        props = feat.get("properties") or {}
        name = feat.get("name") or props.get("name") or f"Feature {i+1}"
        props_str = json.dumps(props, ensure_ascii=False)[:300]
        lines.append(f"  {i+1}. {name}: {props_str}")
    user_content += (
        f"\n\nUser has selected {len(selected_features)} feature(s) on the map:\n"
        + "\n".join(lines)
    )
    if session_id:
        user_content += (
            f"\n\nSelected features' geometries are stored in PostGIS table: "
            f"temp.temp_selected_{session_id} (columns: id, geom_25833). "
            f"Use this table in SQL for spatial proximity queries involving the selected features."
        )
```

---

## Fix 2 — SELECT * and Always Use geom_25833

### Problem A — geometry column truncated in get_table_columns

`get_table_columns` queries `information_schema.columns ORDER BY ordinal_position LIMIT 40`. OSM tables have 50+ columns; `geom_25833` is at position ~51 and never appears. The agent writes SQL without a geometry column.

**`app/utils/agent_tools.py`** — `get_table_columns()`

After building the `columns` list, move geometry columns to the top:
```python
GEO_COLS = {"geom_25833", "geometry", "geom"}
geo = [c for c in columns if c["column"] in GEO_COLS]
non_geo = [c for c in columns if c["column"] not in GEO_COLS]
columns = geo + non_geo
```

This guarantees `geom_25833` always appears in the returned list regardless of table column count.

### Problem B — agent selects specific columns / uses wrong geometry column

The system prompt example `SELECT ST_AsGeoJSON(geometry) AS geometry` teaches the LLM to select only the geometry column and use `geometry` (not `geom_25833`).

**`app/utils/agent_orchestrator.py`** — `_build_agent_system_prompt()`

Replace the execute_sql rules block:

Old:
```
- Always include geometry: SELECT ST_AsGeoJSON(geometry) AS geometry
- For spatial filter with a buffer polygon use: ...
```

New:
```
- ALWAYS write: SELECT *, ST_AsGeoJSON(geom_25833) AS geometry
  - geom_25833 is THE geometry column in ALL tables — never use geometry or geom
  - SELECT * preserves all feature attributes in the result
  - ST_AsGeoJSON(geom_25833) AS geometry exports it as GeoJSON for the map
- For spatial proximity (ST_DWithin) use geom_25833 directly (meters, no transform needed):
  ST_DWithin(a.geom_25833, b.geom_25833, <meters>)
- For spatial filter with a buffer polygon use:
  WHERE ST_Within(ST_Transform(geom_25833, 4326), ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json>'), 4326))
```

Also update the docstring in `execute_sql()` in `app/utils/agent_tools.py` to match the new pattern (no code change needed, just docstring alignment).

`execute_sql()` already strips all raw geom columns from properties (lines 493–496), so `SELECT *` + the GeoJSON alias produces clean output.

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/index.html` | Add `session_id` + `selected_features` to agent payload |
| `app/models/agent_model.py` | Add `session_id` + `selected_features` to `AgentRequest` |
| `app/routes/agent.py` | Forward new params to `run_agent()` |
| `app/utils/agent_orchestrator.py` | Accept params in `run_agent()`; inject context; update system prompt |
| `app/utils/agent_tools.py` | Sort geom columns first in `get_table_columns`; update `execute_sql` docstring |

---

## Verification

1. Select 2–3 features on the map (e.g. buildings, bus stops)
2. Enable agent mode, ask: *"Show me all cafes within 300m of those selected items"*
3. Confirm agent receives selected feature properties in its context (visible in SSE thought steps)
4. Confirm agent uses `temp.temp_selected_{session_id}` in its SQL
5. Confirm the final result layer shows ALL feature columns (not just name/geometry)
6. Confirm `geom_25833` is used in ST_DWithin (visible in agent thought steps)
7. Run a table with 50+ columns — confirm `get_table_columns` returns `geom_25833` first
