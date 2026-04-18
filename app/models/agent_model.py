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
    max_iterations: int = 40

    class Config:
        json_schema_extra = {
            "example": {
                "question": "How many playgrounds are within 500m of Neukölln Rathaus?",
                "llm_provider": "gemini",
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
