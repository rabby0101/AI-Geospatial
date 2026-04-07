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


def test_truncate_result_long_feature_collection():
    big = {"type": "FeatureCollection", "features": [{"id": i} for i in range(500)]}
    truncated = _truncate_result(big)
    assert truncated["_truncated"].startswith("Showing 5 of 500")
    assert len(truncated["features"]) == 5
