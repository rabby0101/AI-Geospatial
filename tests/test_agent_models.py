from app.models.agent_model import AgentRequest, AgentStep, AgentFinalAnswer


def test_agent_request_defaults():
    req = AgentRequest(question="Find parks near me")
    assert req.llm_provider == "deepseek"
    assert req.max_iterations == 20


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


def test_agent_step_types():
    step = AgentStep(type="thought", content="I need to geocode this location")
    assert step.type == "thought"


def test_agent_final_answer():
    fa = AgentFinalAnswer(
        geojson={"type": "FeatureCollection", "features": []},
        summary="Found 3 parks",
        layer_name="parks_nearby",
        steps_taken=3,
        execution_time=1.5,
    )
    assert fa.steps_taken == 3
