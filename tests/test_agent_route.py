import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.agent_model import AgentStep, AgentFinalAnswer


def _make_mock_steps():
    steps = [
        AgentStep(type="thought", content="I need to geocode."),
        AgentStep(type="action", content="geocode_location(...)", tool_name="geocode_location"),
        AgentStep(
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
        ),
    ]
    return steps


def test_agent_query_returns_sse_stream():
    """Route should return text/event-stream content type."""
    async def mock_run_agent(*args, **kwargs):
        for step in _make_mock_steps():
            yield step

    with patch("app.routes.agent.run_agent", side_effect=mock_run_agent):
        client = TestClient(app)
        resp = client.post(
            "/api/agent/query",
            json={"question": "Find parks near me"},
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_agent_query_rejects_empty_question():
    client = TestClient(app)
    resp = client.post("/api/agent/query", json={"question": "   "})
    assert resp.status_code == 422
