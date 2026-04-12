"""
Satellite LLM Intent Parser
Converts a natural language question about satellite imagery into a structured
intent dict. Uses the live database schema (same pattern as the main query
pipeline) so no table names or area names are hardcoded here.
"""

import json
import re
import logging
import os
from typing import Dict, Any, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL     = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL   = "deepseek-chat"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# ---------------------------------------------------------------------------
# Dynamic schema fetcher
# ---------------------------------------------------------------------------

def _get_polygon_tables_for_llm() -> str:
    """
    Query metadata.table_descriptions for polygon/multipolygon tables and
    return a formatted text block describing them — the same way the main
    geospatial query pipeline exposes the database to the LLM.
    """
    try:
        from app.utils.database import db_manager
        tables = db_manager.get_schema_with_descriptions()
        if not tables:
            return "(no polygon tables found in metadata)"

        lines = ["Available vector polygon tables in PostGIS (schema: vector):\n"]
        for t in sorted(tables, key=lambda x: x["table"]):
            geom = t.get("geometry_type") or t.get("geometry", "")
            if not geom or "POLYGON" not in geom.upper():
                continue
            desc = t.get("description", "")
            cols = [
                (c["name"] if isinstance(c, dict) else c)
                for c in t.get("columns", [])
            ]
            lines.append(f'  vector.{t["table"]}')
            lines.append(f'    Description: {desc}')
            lines.append(f'    Geometry: {geom}')
            lines.append(f'    Columns: {", ".join(cols[:15])}')
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Could not fetch polygon tables for LLM: {e}")
        return "(could not fetch table list)"


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(schema_text: str) -> str:
    return f"""You are a satellite image analysis assistant.
Given a user question and available satellite image metadata, produce a JSON
object that tells the pipeline:
  1. Which spectral index to compute.
  2. Which dates to use.
  3. Two PostGIS SQL queries:
       boundary_sql  — returns ONE row with a single 'geometry' column
                       (EPSG:4326) representing the area to clip the rasters to.
       polygons_sql  — returns MULTIPLE rows, each with a 'name' (text) column
                       and a 'geometry' column (EPSG:4326), representing the
                       zones to aggregate index values over.
  4. A short human-readable label describing the area/granularity chosen.

{schema_text}

Supported spectral indices:
  ndvi  (requires B04, B08)   — vegetation
  evi   (requires B02, B04, B08)
  savi  (requires B04, B08)
  ndwi  (requires B03, B08)   — water
  ndbi  (requires B08, B11)   — built-up / urban

Rules:
- Choose the index from the user's question; default to ndvi for vegetation.
- boundary_sql MUST return a single geometry that is the spatial union/extent
  of the area of interest. Use ST_Union if multiple rows could match.
  Always ensure the geometry is in EPSG:4326 using ST_Transform where needed.
- polygons_sql MUST return rows aliased as 'name' and 'geometry' (EPSG:4326).
  Pick the table and granularity that best matches the user's phrasing
  (e.g. "subdivision", "district", "parcel", "LOR", etc.).
  Use a spatial filter (e.g. ST_Within centroid) to restrict to the area of
  interest when the user asks about a sub-region.
- analysis_type: "change_detection" if 2 dates / user mentions change;
  "single_date" otherwise.
- dates: pick from available_dates that best match what the user mentions.
- label: short description like "Pankow subdivisions" or "Berlin districts".
- Return ONLY valid JSON. No markdown fences, no extra text.

Output schema:
{{
  "index":        "ndvi",
  "dates":        ["2024-06-26", "2025-07-01"],
  "analysis_type": "change_detection",
  "boundary_sql": "SELECT ST_Transform(ST_Union(geometry), 4326) AS geometry FROM vector.wfs_alkis_bezirk WHERE lower(namgem) = 'pankow'",
  "polygons_sql": "SELECT o.nam AS name, o.geometry AS geometry FROM vector.wfs_alkis_ortsteile o WHERE ST_Within(ST_Centroid(o.geometry), ST_Transform((SELECT geometry FROM vector.wfs_alkis_bezirk WHERE lower(namgem) = 'pankow'), 4326))",
  "label":        "Pankow subdivisions"
}}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_satellite_intent(
    question: str,
    session_metadata: List[Dict],
    llm_provider: str = "gemini",
) -> Dict[str, Any]:
    """
    Parse a natural language satellite query into a structured intent dict.

    Args:
        question:         User's natural language question.
        session_metadata: List of file metadata dicts from the session store.
        llm_provider:     'gemini' | 'deepseek'.

    Returns:
        Validated intent dict with keys:
            index, dates, analysis_type, boundary_sql, polygons_sql, label

    Raises:
        ValueError if intent cannot be determined even after fallback.
    """
    available_dates = sorted({m["date"] for m in session_metadata if m.get("date")})
    available_bands = sorted({m["band"] for m in session_metadata if m.get("band")})

    # Build dynamic system prompt with live table schema
    schema_text = _get_polygon_tables_for_llm()
    system_prompt = _build_system_prompt(schema_text)

    user_prompt = (
        f"Available dates in session: {available_dates}\n"
        f"Available bands: {available_bands}\n\n"
        f"User question: {question}"
    )

    raw_json = None

    # Try primary provider
    try:
        if llm_provider == "deepseek" and DEEPSEEK_API_KEY:
            raw_json = _call_deepseek(user_prompt, system_prompt)
        elif GEMINI_API_KEY:
            raw_json = _call_gemini(user_prompt, system_prompt)
        elif DEEPSEEK_API_KEY:
            raw_json = _call_deepseek(user_prompt, system_prompt)
    except Exception as e:
        logger.warning(f"Primary LLM call failed: {e}")

    # Retry with other provider
    if raw_json is None:
        try:
            if llm_provider != "deepseek" and DEEPSEEK_API_KEY:
                raw_json = _call_deepseek(user_prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Fallback LLM call failed: {e}")

    intent = None
    if raw_json:
        intent = _parse_json_response(raw_json)

    # Regex fallback if LLM unavailable or returned invalid JSON
    if intent is None:
        logger.info("Using regex fallback parser for satellite intent")
        intent = _regex_fallback_parser(question, session_metadata)

    return _validate_intent(intent)


# ---------------------------------------------------------------------------
# LLM callers
# ---------------------------------------------------------------------------

def _call_gemini(user_prompt: str, system_prompt: str) -> Optional[str]:
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if candidates:
        return candidates[0]["content"]["parts"][0]["text"]
    return None


def _call_deepseek(user_prompt: str, system_prompt: str) -> Optional[str]:
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 800,
    }
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str) -> Optional[Dict]:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Regex fallback — generates SQL from question patterns
# ---------------------------------------------------------------------------

_INDEX_KEYWORDS = {
    "ndvi":  ["ndvi", "vegetation", "green", "plant", "forest", "tree", "leaf"],
    "ndwi":  ["ndwi", "water", "lake", "river", "moisture"],
    "ndbi":  ["ndbi", "built", "urban", "building", "impervious"],
    "evi":   ["evi", "enhanced vegetation"],
    "savi":  ["savi", "soil adjusted"],
}

# Known Berlin district names for the fallback SQL builder only
_BERLIN_DISTRICTS = {
    "mitte", "friedrichshain-kreuzberg", "pankow", "charlottenburg-wilmersdorf",
    "spandau", "steglitz-zehlendorf", "tempelhof-schöneberg", "neukölln",
    "treptow-köpenick", "marzahn-hellersdorf", "lichtenberg", "reinickendorf",
}


def _regex_fallback_parser(question: str, session_metadata: List[Dict]) -> Dict:
    """
    Rule-based fallback. Detects index, area, granularity from question text
    and builds the corresponding boundary_sql / polygons_sql directly.
    """
    q = question.lower()

    # Index
    detected_index = "ndvi"
    for idx, keywords in _INDEX_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            detected_index = idx
            break

    # Granularity keywords
    want_subdivision = any(
        kw in q for kw in ["subdivision", "ortsteil", "ortsteile", "sub-district", "lor"]
    )

    # Area — check for a named district or "berlin" (whole city)
    detected_district = None
    for d in _BERLIN_DISTRICTS:
        if d in q:
            detected_district = d
            break

    whole_city = (
        "berlin" in q and detected_district is None
    ) or detected_district is None

    # Build SQL based on detected area + granularity
    if whole_city:
        boundary_sql = (
            "SELECT ST_Transform(ST_Union(geometry), 4326) AS geometry "
            "FROM vector.wfs_alkis_bezirk"
        )
        if want_subdivision:
            polygons_sql = (
                "SELECT nam AS name, geometry AS geometry "
                "FROM vector.wfs_alkis_ortsteile"
            )
            label = "Berlin subdivisions"
        else:
            polygons_sql = (
                "SELECT namgem AS name, ST_Transform(geometry, 4326) AS geometry "
                "FROM vector.wfs_alkis_bezirk"
            )
            label = "Berlin districts"
    else:
        d = detected_district
        boundary_sql = (
            f"SELECT ST_Transform(ST_Union(geometry), 4326) AS geometry "
            f"FROM vector.wfs_alkis_bezirk WHERE lower(namgem) = '{d}'"
        )
        if want_subdivision:
            polygons_sql = (
                f"SELECT o.nam AS name, o.geometry AS geometry "
                f"FROM vector.wfs_alkis_ortsteile o "
                f"WHERE ST_Within(ST_Centroid(o.geometry), ST_Transform("
                f"(SELECT geometry FROM vector.wfs_alkis_bezirk "
                f" WHERE lower(namgem) = '{d}'), 4326))"
            )
            label = f"{d.title()} subdivisions"
        else:
            polygons_sql = (
                f"SELECT namgem AS name, ST_Transform(geometry, 4326) AS geometry "
                f"FROM vector.wfs_alkis_bezirk WHERE lower(namgem) = '{d}'"
            )
            label = d.title()

    # Dates
    available_dates = sorted({m["date"] for m in session_metadata if m.get("date")})
    year_matches = re.findall(r"\b(20\d{2})\b", q)
    selected_dates = []
    for yr in year_matches:
        for dt in available_dates:
            if dt.startswith(yr):
                selected_dates.append(dt)
                break
    seen: set = set()
    selected_dates = [d for d in selected_dates if not (d in seen or seen.add(d))]
    if not selected_dates:
        selected_dates = available_dates[:2]
    selected_dates = selected_dates[:2]

    analysis_type = "change_detection" if len(selected_dates) >= 2 else "single_date"

    return {
        "index":        detected_index,
        "dates":        selected_dates,
        "analysis_type": analysis_type,
        "boundary_sql": boundary_sql,
        "polygons_sql": polygons_sql,
        "label":        label,
    }


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------

def _validate_intent(intent: Dict) -> Dict:
    """
    Validate and normalise the parsed intent dict.
    Raises ValueError if required SQL fields are missing.
    """
    intent["index"] = str(intent.get("index") or "ndvi").lower().strip()

    # Ensure dates is a list of at most 2 strings
    dates = intent.get("dates") or []
    if isinstance(dates, str):
        dates = [dates]
    intent["dates"] = [str(d) for d in dates][:2]

    # Re-derive analysis_type from date count
    if len(intent["dates"]) >= 2:
        intent["analysis_type"] = "change_detection"
    elif len(intent["dates"]) == 1:
        intent["analysis_type"] = "single_date"
    else:
        intent["analysis_type"] = intent.get("analysis_type", "single_date")

    intent["label"] = str(intent.get("label") or "area").strip()

    # Validate SQL fields
    for field in ("boundary_sql", "polygons_sql"):
        val = intent.get(field, "").strip()
        if not val:
            raise ValueError(
                f"LLM did not produce a '{field}'. "
                "Try rephrasing your question or check that the relevant "
                "spatial tables are registered in metadata.table_descriptions."
            )
        intent[field] = val

    return intent
