"""
LM Studio client — OpenAI-compatible local inference.
"""
import os

import requests

LMSTUDIO_API_URL = os.getenv("LMSTUDIO_API_URL", "http://localhost:1234/v1")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "gemma-4-e4b-it")
LMSTUDIO_TIMEOUT = int(os.getenv("LMSTUDIO_TIMEOUT", "120"))

# Simple in-memory cache shared across query helpers
_query_cache: dict = {}


def query_lmstudio(messages: list) -> str:
    """Call LM Studio local server (OpenAI-compatible). Returns raw text content."""
    payload = {
        "model": LMSTUDIO_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }
    resp = requests.post(
        f"{LMSTUDIO_API_URL}/chat/completions",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=LMSTUDIO_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def invalidate_query_cache() -> None:
    """Clear the in-memory query cache (called when the DB schema changes)."""
    _query_cache.clear()
    print("✅ Query cache invalidated (schema change detected)")
