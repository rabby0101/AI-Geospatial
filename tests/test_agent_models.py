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
        execution_time=1.5,
    )
    assert fa.steps_taken == 3
