"""
Agent trace retrieval — GET /api/agent/trace/{query_id}

Returns the stored steps, SQL queries, tables, and result summary
for a completed agent query. Used by the frontend to restore the
4-section panel when revisiting a layer after page refresh.
"""
from fastapi import APIRouter, HTTPException

from app.utils.agent_trace_store import get_trace

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/trace/{query_id}")
async def get_agent_trace(query_id: str):
    """Return the stored trace for a query_id, or 404 if not found."""
    trace = get_trace(query_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
