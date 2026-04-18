"""
Agent route — POST /api/agent/query

Streams ReAct agent steps as Server-Sent Events (SSE).
Each event is a JSON-encoded AgentStep.

Event format:
    data: {"type": "thought", "content": "...", ...}\n\n
    data: {"type": "action", "tool_name": "...", ...}\n\n
    data: {"type": "tool_result", "tool_name": "...", "tool_result": ...}\n\n
    data: {"type": "error", "content": "..."}\n\n
    data: {"type": "done", "query_id": "<uuid>"}\n\n
"""
import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.agent_model import AgentRequest, AgentStep
from app.utils.agent_orchestrator import run_agent
from app.utils.agent_trace_store import extract_tables_from_sql, save_trace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


async def _sse_generator(request: AgentRequest) -> AsyncGenerator[str, None]:
    """Wrap the agent async generator as SSE-formatted text chunks."""
    query_id = str(uuid.uuid4())
    collected_steps: list = []
    sql_queries: list = []
    tables_used: set = set()
    results: dict | None = None

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

            # Build step record for persistence (no geometry — keep it small)
            step_record: dict = {"type": step.type, "content": step.content}
            if step.tool_name:
                step_record["tool_name"] = step.tool_name

            # Capture SQL from execute_sql action steps
            if (
                step.type == "action"
                and step.tool_name == "execute_sql"
                and step.tool_args
            ):
                sql = step.tool_args.get("sql", "")
                if sql:
                    sql_queries.append(sql)
                    step_record["sql"] = sql
                    tables_used.update(extract_tables_from_sql(sql))

            # Capture final answer metadata (no geometry)
            if (
                step.type == "tool_result"
                and step.tool_name == "final_answer"
                and step.tool_result
            ):
                fa = step.tool_result
                geojson = fa.get("geojson") or {}
                results = {
                    "feature_count": len(geojson.get("features", [])),
                    "execution_time": fa.get("execution_time"),
                    "summary": fa.get("summary"),
                    "layer_name": fa.get("layer_name"),
                }

            collected_steps.append(step_record)
            serialized = await asyncio.to_thread(json.dumps, payload, default=str)
            yield f"data: {serialized}\n\n"

    except Exception as e:
        logger.error(f"Agent SSE error: {e}")
        error_step = AgentStep(type="error", content=str(e))
        yield f"data: {json.dumps(error_step.model_dump())}\n\n"

    finally:
        try:
            await asyncio.to_thread(
                save_trace,
                query_id,
                collected_steps,
                sql_queries,
                list(tables_used),
                results,
            )
        except Exception as e:
            logger.error(f"Failed to save agent trace {query_id}: {e}", exc_info=True)

        yield f'data: {json.dumps({"type": "done", "query_id": query_id})}\n\n'


@router.post("/query")
async def agent_query(request: AgentRequest) -> StreamingResponse:
    """
    Process a natural language geospatial query using the ReAct agent.

    Streams Server-Sent Events. Each event is a JSON-encoded AgentStep.
    The final meaningful event has type="tool_result" and tool_name="final_answer".
    The closing event has type="done" and includes "query_id" for trace retrieval.
    """
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
