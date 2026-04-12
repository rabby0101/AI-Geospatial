"""
Agent trace storage — saves and retrieves per-query agent traces from Postgres.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text


def _get_engine():
    db_user = os.getenv('POSTGRES_USER', 'geoassist')
    db_password = os.getenv('POSTGRES_PASSWORD', 'geoassist_password')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5433')
    db_name = os.getenv('POSTGRES_DB', 'geoassist')
    return create_engine(
        f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}',
        pool_pre_ping=True,
    )


def init_trace_table() -> None:
    """Create agent_traces table if it does not exist. Called at app startup."""
    engine = _get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_traces (
                query_id  TEXT PRIMARY KEY,
                steps     JSONB NOT NULL DEFAULT '[]',
                sql_queries JSONB NOT NULL DEFAULT '[]',
                tables_used JSONB NOT NULL DEFAULT '[]',
                results   JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.commit()


def extract_tables_from_sql(sql: str) -> List[str]:
    """Return unique table names matching vector.<name> in a SQL string."""
    return list(set(re.findall(r'(?:FROM|JOIN)\s+vector\.(\w+)', sql, re.IGNORECASE)))


def save_trace(
    query_id: str,
    steps: List[Dict[str, Any]],
    sql_queries: List[str],
    tables_used: List[str],
    results: Optional[Dict[str, Any]] = None,
) -> None:
    engine = _get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO agent_traces (query_id, steps, sql_queries, tables_used, results)
                VALUES (:query_id, :steps::jsonb, :sql_queries::jsonb,
                        :tables_used::jsonb, :results::jsonb)
                ON CONFLICT (query_id) DO UPDATE SET
                    steps       = EXCLUDED.steps,
                    sql_queries = EXCLUDED.sql_queries,
                    tables_used = EXCLUDED.tables_used,
                    results     = EXCLUDED.results
            """),
            {
                "query_id":    query_id,
                "steps":       json.dumps(steps),
                "sql_queries": json.dumps(sql_queries),
                "tables_used": json.dumps(tables_used),
                "results":     json.dumps(results) if results is not None else None,
            },
        )
        conn.commit()


def get_trace(query_id: str) -> Optional[Dict[str, Any]]:
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT steps, sql_queries, tables_used, results
                FROM agent_traces WHERE query_id = :qid
            """),
            {"qid": query_id},
        ).fetchone()
    if not row:
        return None
    return {
        "query_id":    query_id,
        "steps":       row[0] or [],
        "sql_queries": row[1] or [],
        "tables_used": row[2] or [],
        "results":     row[3],
    }
