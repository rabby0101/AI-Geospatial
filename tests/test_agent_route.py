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


def test_agent_query_rejects_empty_question():
    client = TestClient(app)
    resp = client.post("/api/agent/query", json={"question": "   "})
    assert resp.status_code == 422
