from unittest.mock import patch
from app.utils.agent_orchestrator import (
    _parse_llm_output,
    _build_agent_system_prompt,
    _truncate_result,
    run_agent,
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


def test_parse_final_answer_with_feature():
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
    for tool in [
        "geocode_location", "create_buffer", "query_features",
        "spatial_filter", "get_schema_info", "calculate_route",
        "walking_isochrone", "analyze_satellite", "score_locations",
    ]:
        assert tool in prompt


def test_system_prompt_enforces_select_star():
    prompt = _build_agent_system_prompt()
    assert "SELECT *" in prompt, "System prompt must instruct agent to use SELECT *"


def test_system_prompt_enforces_geom_25833():
    prompt = _build_agent_system_prompt()
    assert "geom_25833" in prompt
    assert "ST_AsGeoJSON(ST_Transform(geom_25833, 4326))" in prompt


def test_system_prompt_forbids_geometry_column():
    prompt = _build_agent_system_prompt()
    assert "ST_AsGeoJSON(geometry)" not in prompt


import asyncio


def _collect_steps(gen):
    """Collect all steps from an async generator."""
    steps = []
    async def _run():
        async for step in gen:
            steps.append(step)
    asyncio.run(_run())
    return steps


def test_run_agent_injects_selected_features_context():
    captured_messages = []

    def mock_call_llm(messages, provider="deepseek"):
        captured_messages.extend(messages)
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
        _collect_steps(run_agent(
            question="Find bakeries near my selection",
            session_id="session_abc",
            selected_features=selected,
        ))

    user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "Cafe Mitte" in user_msg
    assert "amenity" in user_msg
    assert "temp.temp_selected_session_abc" in user_msg


def test_run_agent_no_selected_features_no_injection():
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
    assert "temp_selected" not in user_msg


def test_truncate_result_long_feature_collection():
    big = {"type": "FeatureCollection", "features": [{"id": i} for i in range(500)]}
    truncated = _truncate_result(big)
    assert truncated["_truncated"].startswith("Showing 5 of 500")
    assert len(truncated["features"]) == 5
