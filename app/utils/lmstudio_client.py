"""
LM Studio client — OpenAI-compatible local inference.
"""
import os, sys
from dotenv import load_dotenv

import requests

load_dotenv()

LMSTUDIO_API_URL = os.getenv("LMSTUDIO_API_URL", "http://localhost:1234/v1")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "gemma-4-e4b-it")
LMSTUDIO_TIMEOUT = int(os.getenv("LMSTUDIO_TIMEOUT", "120"))
print(f"[lmstudio_client] LMSTUDIO_MODEL = {LMSTUDIO_MODEL}", flush=True)
print(f"[lmstudio_client] LMSTUDIO_API_URL = {LMSTUDIO_API_URL}", flush=True)

# Simple in-memory cache shared across query helpers
_query_cache: dict = {}


def query_lmstudio(messages: list) -> str:
    """Call LM Studio local server (OpenAI-compatible). Returns raw text content."""
    url = f"{LMSTUDIO_API_URL}/chat/completions"
    payload = {
        "model": LMSTUDIO_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
        "thinking": False,
    }
    print(f"[query_lmstudio] URL: {url}", flush=True)
    print(f"[query_lmstudio] Payload model: {payload['model']}", flush=True)
    print(f"[query_lmstudio] Messages count: {len(messages)}", flush=True)
    print(f"[query_lmstudio] Full payload: {payload}", flush=True)
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=LMSTUDIO_TIMEOUT,
    )
    print(f"[query_lmstudio] Response status: {resp.status_code}", flush=True)
    if resp.status_code != 200:
        print(f"[query_lmstudio] Error body: {resp.text[:200]}", flush=True)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def invalidate_query_cache() -> None:
    """Clear the in-memory query cache (called when the DB schema changes)."""
    _query_cache.clear()
    print("✅ Query cache invalidated (schema change detected)")
