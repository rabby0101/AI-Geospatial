# Agent: Selected Features Context + Geometry Column Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two agent-mode bugs: (1) agent has no context about map-selected features, (2) agent misses the `geom_25833` geometry column and generates partial SELECT queries.

**Architecture:** The fix threads `session_id` + `selected_features` from the frontend through the model → route → orchestrator, then injects a human-readable context block into the agent's user message. The geometry fix is a prompt + column-ordering change with no DB schema changes.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, PostGIS, vanilla JS (frontend)

---

## File Map

| File | Change |
|------|--------|
| `app/models/agent_model.py` | Add `session_id` + `selected_features` to `AgentRequest` |
| `app/routes/agent.py` | Forward new fields to `run_agent()` |
| `app/utils/agent_orchestrator.py` | Accept params; inject context; update system prompt |
| `app/utils/agent_tools.py` | Sort geom cols first in `get_table_columns`; fix `execute_sql` docstring |
| `frontend/index.html` | Add `session_id` + `selected_features` to agent payload |
| `tests/test_agent_models.py` | New test: fields accepted and default to None |
| `tests/test_agent_route.py` | New test: new fields forwarded to run_agent |
| `tests/test_agent_orchestrator.py` | New tests: context injected; system prompt rules |
| `tests/test_agent_tools.py` | New test: geom_25833 appears first in get_table_columns |

---

## Task 1: Add session_id and selected_features to AgentRequest

**Files:**
- Modify: `app/models/agent_model.py`
- Test: `tests/test_agent_models.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agent_models.py`:

```python
def test_agent_request_accepts_session_and_features():
    req = AgentRequest(
        question="Find cafes near selection",
        session_id="session_123",
        selected_features=[
            {"geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
             "properties": {"name": "Test Cafe", "amenity": "cafe"},
             "name": "Test Cafe"}
        ],
    )
    assert req.session_id == "session_123"
    assert len(req.selected_features) == 1
    assert req.selected_features[0]["properties"]["amenity"] == "cafe"


def test_agent_request_session_and_features_default_none():
    req = AgentRequest(question="Find parks")
    assert req.session_id is None
    assert req.selected_features is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/skfazlarabby/Documents/GitHub/AI-Geospatial
pytest tests/test_agent_models.py::test_agent_request_accepts_session_and_features -v
```

Expected: `FAILED` — `AgentRequest` has no `session_id` field.

- [ ] **Step 3: Add fields to AgentRequest**

Edit `app/models/agent_model.py`, replace the class body:

```python
from pydantic import BaseModel
from typing import Any, Dict, List, Literal, Optional


class AgentRequest(BaseModel):
    question: str
    llm_provider: Optional[str] = "deepseek"
    user_location: Optional[Dict[str, float]] = None
    drawn_geometry: Optional[Dict[str, Any]] = None
    selected_feature: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    selected_features: Optional[List[Dict[str, Any]]] = None
    max_iterations: int = 10

    class Config:
        json_schema_extra = {
            "example": {
                "question": "How many playgrounds are within 500m of Neukölln Rathaus?",
                "llm_provider": "deepseek",
            }
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_models.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/agent_model.py tests/test_agent_models.py
git commit -m "feat(agent): add session_id and selected_features to AgentRequest"
```

---

## Task 2: Sort geometry columns first in get_table_columns

**Files:**
- Modify: `app/utils/agent_tools.py` (lines 428–449)
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agent_tools.py`:

```python
def test_get_table_columns_geom_25833_appears_first():
    """geom_25833 must appear first even when it's at a high ordinal position."""
    mock_cols = [
        {"column_name": "id", "data_type": "integer"},
        {"column_name": "name", "data_type": "text"},
        {"column_name": "amenity", "data_type": "text"},
        {"column_name": "addr_street", "data_type": "text"},
        {"column_name": "geom_25833", "data_type": "USER-DEFINED"},
    ]
    import pandas as pd
    mock_df = pd.DataFrame(mock_cols)

    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = mock_df
        result = get_table_columns("osm_cafes")

    assert isinstance(result, list)
    assert result[0]["column"] == "geom_25833", (
        f"Expected geom_25833 first, got: {result[0]['column']}"
    )
```

Add `get_table_columns` to the import at the top of the test file:

```python
from app.utils.agent_tools import (
    geocode_location,
    create_buffer,
    get_schema_info,
    get_table_columns,
    TOOL_REGISTRY,
)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_tools.py::test_get_table_columns_geom_25833_appears_first -v
```

Expected: `FAILED` — geom_25833 appears at position 4, not 0.

- [ ] **Step 3: Add geometry-first sort to get_table_columns**

In `app/utils/agent_tools.py`, after line `columns = [{"column": r["column_name"], "type": r["data_type"]} for r in rows]` (line ~429), add:

```python
        # Geometry columns bubble to top so the LLM always sees them,
        # even in wide tables (50+ columns) where they'd otherwise be truncated
        GEO_COLS = {"geom_25833", "geometry", "geom"}
        geo = [c for c in columns if c["column"] in GEO_COLS]
        non_geo = [c for c in columns if c["column"] not in GEO_COLS]
        columns = geo + non_geo
```

Place this block immediately after the `columns = [...]` list comprehension and before the `sample_cols = ...` line.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_tools.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_tools.py tests/test_agent_tools.py
git commit -m "fix(agent): sort geometry columns first in get_table_columns"
```

---

## Task 3: Update system prompt — enforce SELECT * and geom_25833

**Files:**
- Modify: `app/utils/agent_orchestrator.py` — `_build_agent_system_prompt()` (lines 31–95)
- Test: `tests/test_agent_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_orchestrator.py`:

```python
def test_system_prompt_enforces_select_star():
    prompt = _build_agent_system_prompt()
    assert "SELECT *" in prompt, "System prompt must instruct agent to use SELECT *"


def test_system_prompt_enforces_geom_25833():
    prompt = _build_agent_system_prompt()
    assert "geom_25833" in prompt
    assert "ST_AsGeoJSON(geom_25833)" in prompt


def test_system_prompt_forbids_geometry_column():
    prompt = _build_agent_system_prompt()
    # Should not instruct the agent to use the generic 'geometry' column name
    assert "ST_AsGeoJSON(geometry)" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_orchestrator.py::test_system_prompt_enforces_select_star tests/test_agent_orchestrator.py::test_system_prompt_enforces_geom_25833 tests/test_agent_orchestrator.py::test_system_prompt_forbids_geometry_column -v
```

Expected: all 3 FAIL.

- [ ] **Step 3: Update the system prompt**

In `app/utils/agent_orchestrator.py`, replace the `execute_sql rules:` block inside `_build_agent_system_prompt()` (the block starting at the line `execute_sql rules:` through the closing `Always add LIMIT 500` line):

Old block:
```
execute_sql rules:
- Tables are in the 'vector' schema: FROM vector.<table_name>
- Always include geometry: SELECT ST_AsGeoJSON(geometry) AS geometry
- For spatial filter with a buffer polygon use:
  WHERE ST_Within(geometry, ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json>'), 4326))
  or ST_Intersects for partial overlap
- Always add LIMIT 500
```

New block:
```
execute_sql rules:
- Tables are in the 'vector' schema: FROM vector.<table_name>
- ALWAYS write: SELECT *, ST_AsGeoJSON(geom_25833) AS geometry
  - geom_25833 is THE geometry column in ALL tables (vector.* and temp.*)
  - Never use 'geometry' or 'geom' as the geometry column name
  - SELECT * preserves all feature attributes in the result
- For spatial proximity queries use geom_25833 directly (no transform needed — units are metres):
  ST_DWithin(a.geom_25833, b.geom_25833, <metres>)
- For spatial filter with a buffer polygon use:
  WHERE ST_Within(ST_Transform(geom_25833, 4326), ST_SetSRID(ST_GeomFromGeoJSON('<polygon_json>'), 4326))
  or ST_Intersects for partial overlap
- Always add LIMIT 500
```

Also update the `Spatial tips:` section. Replace:
```
- GEOMETRY COLUMN: Check with get_table_columns — common names are 'geometry' or 'geom_25833'.
  Use ST_AsGeoJSON(geometry) AS geometry in SELECT.
```
With:
```
- GEOMETRY COLUMN: ALL tables use geom_25833 (EPSG:25833, units = metres).
  Always write ST_AsGeoJSON(geom_25833) AS geometry in your SELECT.
  get_table_columns will show it first in the column list.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_orchestrator.py -v
```

Expected: all tests PASS (including the existing `test_system_prompt_contains_all_tools`).

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_orchestrator.py tests/test_agent_orchestrator.py
git commit -m "fix(agent): enforce SELECT * and geom_25833 in system prompt"
```

---

## Task 4: Inject selected features context into run_agent

**Files:**
- Modify: `app/utils/agent_orchestrator.py` — `run_agent()` (lines 211–239)
- Test: `tests/test_agent_orchestrator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agent_orchestrator.py`:

```python
import asyncio

def _collect_steps(coro):
    """Helper: collect all steps from run_agent async generator (mocking LLM)."""
    steps = []
    async def _run():
        async for step in coro:
            steps.append(step)
    asyncio.get_event_loop().run_until_complete(_run())
    return steps


def test_run_agent_injects_selected_features_context():
    """User content must include feature properties and temp table reference."""
    captured_messages = []

    def mock_call_llm(messages, provider="deepseek"):
        captured_messages.extend(messages)
        # Return a valid final answer on first call so we don't loop forever
        return (
            'Thought: Done.\nFinal Answer:\n'
            '{"type":"FeatureCollection","features":[]}\n'
            'Summary: Test.\nLayer: test'
        )

    selected = [
        {"geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
         "properties": {"name": "Cafe Mitte", "amenity": "cafe"},
         "name": "Cafe Mitte"}
    ]

    with patch("app.utils.agent_orchestrator._call_llm", side_effect=mock_call_llm):
        _collect_steps(
            run_agent(
                question="Find bakeries near my selection",
                session_id="session_abc",
                selected_features=selected,
            )
        )

    user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "Cafe Mitte" in user_msg
    assert "amenity" in user_msg
    assert "temp.temp_selected_session_abc" in user_msg


def test_run_agent_no_selected_features_no_injection():
    """Without selected features the user content stays the same as before."""
    captured_messages = []

    def mock_call_llm(messages, provider="deepseek"):
        captured_messages.extend(messages)
        return (
            'Thought: Done.\nFinal Answer:\n'
            '{"type":"FeatureCollection","features":[]}\n'
            'Summary: Test.\nLayer: test'
        )

    with patch("app.utils.agent_orchestrator._call_llm", side_effect=mock_call_llm):
        _collect_steps(run_agent(question="Find parks"))

    user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "selected" not in user_msg.lower()
    assert "temp_selected" not in user_msg
```

Add `run_agent` to the import at the top of `tests/test_agent_orchestrator.py`:

```python
from unittest.mock import patch
from app.utils.agent_orchestrator import (
    _parse_llm_output,
    _build_agent_system_prompt,
    _truncate_result,
    run_agent,
)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_orchestrator.py::test_run_agent_injects_selected_features_context tests/test_agent_orchestrator.py::test_run_agent_no_selected_features_no_injection -v
```

Expected: `FAILED` — `run_agent()` doesn't accept `session_id` / `selected_features`.

- [ ] **Step 3: Update run_agent signature and context injection**

In `app/utils/agent_orchestrator.py`, replace the `run_agent` function signature and the context-building block (lines 211–239):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_orchestrator.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/utils/agent_orchestrator.py tests/test_agent_orchestrator.py
git commit -m "feat(agent): inject selected features context into run_agent"
```

---

## Task 5: Forward session_id and selected_features through the agent route

**Files:**
- Modify: `app/routes/agent.py`
- Test: `tests/test_agent_route.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_agent_route.py`:

```python
def test_agent_query_forwards_session_and_features():
    """Route must pass session_id and selected_features to run_agent."""
    forwarded_kwargs = {}

    async def mock_run_agent(*args, **kwargs):
        forwarded_kwargs.update(kwargs)
        for step in _make_mock_steps():
            yield step

    with patch("app.routes.agent.run_agent", side_effect=mock_run_agent):
        client = TestClient(app)
        resp = client.post(
            "/api/agent/query",
            json={
                "question": "Find cafes near selection",
                "session_id": "session_xyz",
                "selected_features": [
                    {"geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
                     "properties": {"name": "Test Cafe"},
                     "name": "Test Cafe"}
                ],
            },
        )

    assert resp.status_code == 200
    assert forwarded_kwargs.get("session_id") == "session_xyz"
    assert len(forwarded_kwargs.get("selected_features", [])) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_route.py::test_agent_query_forwards_session_and_features -v
```

Expected: `FAILED` — `run_agent` not called with `session_id`.

- [ ] **Step 3: Update the route**

In `app/routes/agent.py`, replace the `_sse_generator` function:

```python
async def _sse_generator(request: AgentRequest) -> AsyncGenerator[str, None]:
    """Wrap the agent async generator as SSE-formatted text chunks."""
    try:
        async for step in run_agent(
            question=request.question,
            llm_provider=request.llm_provider or "deepseek",
            max_iterations=request.max_iterations,
            user_location=request.user_location,
            drawn_geometry=request.drawn_geometry,
            session_id=request.session_id,
            selected_features=request.selected_features,
        ):
            payload = step.model_dump()
            yield f"data: {json.dumps(payload, default=str)}\n\n"
    except Exception as e:
        logger.error(f"Agent SSE error: {e}")
        error_step = AgentStep(type="error", content=str(e))
        yield f"data: {json.dumps(error_step.model_dump())}\n\n"
    finally:
        yield 'data: {"type": "done"}\n\n'
```

- [ ] **Step 4: Run all agent tests**

```bash
pytest tests/test_agent_route.py tests/test_agent_models.py tests/test_agent_orchestrator.py tests/test_agent_tools.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/agent.py tests/test_agent_route.py
git commit -m "feat(agent): forward session_id and selected_features to run_agent"
```

---

## Task 6: Update frontend to send session_id and selected_features in agent payload

**Files:**
- Modify: `frontend/index.html` (~line 9397)

No automated test for this — verify manually in the browser.

- [ ] **Step 1: Locate the agent query payload block**

In `frontend/index.html`, find (~line 9397):

```js
const payload = { question, llm_provider: 'deepseek', max_iterations: 10 };
if (window.drawnGeometry) payload.drawn_geometry = window.drawnGeometry;
if (window.userLocation) payload.user_location = window.userLocation;
```

- [ ] **Step 2: Add session_id and selected_features**

Replace those 3 lines with:

```js
const payload = { question, llm_provider: 'deepseek', max_iterations: 10 };
if (window.drawnGeometry) payload.drawn_geometry = window.drawnGeometry;
if (window.userLocation) payload.user_location = window.userLocation;
if (window.sessionId) payload.session_id = window.sessionId;
if (selectedFeatures && selectedFeatures.length > 0) payload.selected_features = selectedFeatures;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): pass session_id and selected_features to agent query"
```

---

## Task 7: Update execute_sql docstring to match new SELECT * pattern

**Files:**
- Modify: `app/utils/agent_tools.py` — `execute_sql()` docstring (lines 459–466)

This is a documentation fix only — no logic change.

- [ ] **Step 1: Update the docstring**

In `app/utils/agent_tools.py`, replace the `execute_sql` docstring rules block:

Old:
```python
    Rules for writing the SQL:
    - Always SELECT the geometry column: use ST_AsGeoJSON(geom) AS geometry
      (or ST_AsGeoJSON(geom_25833) if the table uses EPSG:25833)
    - Tables live in the 'vector' schema: FROM vector.<table_name>
```

New:
```python
    Rules for writing the SQL:
    - ALWAYS write: SELECT *, ST_AsGeoJSON(geom_25833) AS geometry
      geom_25833 is the geometry column in ALL tables; SELECT * preserves all attributes
    - Tables live in the 'vector' schema: FROM vector.<table_name>
      Temp tables (selected features) live in the 'temp' schema: FROM temp.<table_name>
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add app/utils/agent_tools.py
git commit -m "docs(agent): align execute_sql docstring with SELECT * / geom_25833 convention"
```

---

## Verification (End-to-End)

1. Start the server: `uvicorn app.main:app --reload`
2. Open the frontend in a browser
3. Click 2–3 map features to select them (they should highlight)
4. Enable agent mode, submit: *"Show me all cafes within 300m of those selected features"*
5. In the SSE thought stream, confirm:
   - The user message includes the selected feature names and properties
   - The agent references `temp.temp_selected_<session_id>` in its SQL
   - The SQL uses `SELECT *` and `ST_AsGeoJSON(geom_25833) AS geometry`
   - The result layer shows ALL columns (not just name/geometry)
6. Try a table with many columns: ask about `osm_buildings` — confirm `get_table_columns` returns `geom_25833` as the first column in the agent thought stream
