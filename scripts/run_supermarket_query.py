#!/usr/bin/env python3
"""
Diagnostic CLI — Supermarket Site Selection Query
Runs the full 4-phase AI Geospatial pipeline and prints each stage's output.

Usage (from project root):
    python scripts/run_supermarket_query.py
    python scripts/run_supermarket_query.py --provider deepseek
    python scripts/run_supermarket_query.py --save-geojson
    python scripts/run_supermarket_query.py --verbose
"""

import sys
import os
import io
import json
import time
import argparse
import contextlib
import logging
from pathlib import Path
from datetime import datetime

# ── Project root on sys.path ─────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

# Suppress noisy internal logging before importing app modules
logging.basicConfig(level=logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
logging.getLogger("app").setLevel(logging.WARNING)

# ── App imports (after sys.path and logging setup) ────────────────────────────
from app.utils.deepseek import (
    _get_database_schema_for_llm,
    _plan_query_with_llm,
    query_gemini,
    query_deepseek,
    parse_geospatial_query,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEY,
    _detect_business_type,
    _get_business_profile,
    _get_kg_facts,
    _format_business_profile_for_prompt,
    _generate_business_profile_with_llm,
    _evaluate_results,
)
from app.utils.spatial_engine import SpatialEngine

# ── Query ─────────────────────────────────────────────────────────────────────
QUESTION = (
    "I want to find the top 5 locations for a new veterinary clinic in the Marzahn-Hellersdorf district of Berlin. "
    "A location is legally viable if it meets either condition: "
    "Legal condition A — the site is covered by an active B-Plan (bp_rechtsstand = 'In Kraft getreten') "
    "where the zone type (inhalt) includes Wohngebiet, Mischgebiet, or Kerngebiet "
    "(veterinary clinics are permitted as healthcare services in residential and mixed zones). "
    "Legal condition B — the site has no active B-Plan coverage (paragraph 34 BauGB territory), "
    "meaning no wfs_bplan_b_bp_fs polygon intersects the site, but the surrounding area within 100 metres "
    "already contains residential or mixed-use buildings from alkis_buildings. "
    "In addition, every candidate location must: "
    "(1) have available space more than 150 square metres from alkis_buildings, "
    "(2) have parking facilities within 300 metres (pet owners typically drive), "
    "(3) have a public transport stop within 500 metres, "
    "(4) have no existing veterinary clinic within 1000 metres, "
    "(5) have at least 300 residential buildings within 800 metres. "
    "Locations within 300 metres of a park or green area should score higher as a bonus "
    "since dog owners frequent these areas. "
    "Rank results by composite score: residential demand (criterion 5) weighted at 40%, "
    "competitor distance (criterion 4) at 35%, transport and parking access at 25%. "
    "Show top 5 with scores."
)

# ── Formatting helpers ────────────────────────────────────────────────────────
W = 80

def div(char="="):
    print(char * W)

def header(title):
    print()
    div()
    print(f"  {title}")
    div()

def sub(label, value=""):
    if value:
        print(f"  {label}: {value}")
    else:
        print(f"  {label}")

def section(n, name, subtitle=""):
    print()
    div()
    print(f"  PHASE {n} — {name}")
    if subtitle:
        print(f"  {subtitle}")
    div()

def banner(title):
    print()
    div("#")
    print(f"#  {title}")
    print(f"#  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    div("#")

# ── Preflight ─────────────────────────────────────────────────────────────────
def run_preflight(provider: str) -> bool:
    header("PREFLIGHT CHECK")
    ok = True

    gemini_set = bool(GEMINI_API_KEY)
    deepseek_set = bool(DEEPSEEK_API_KEY)

    sub("GEMINI_API_KEY", "Set" if gemini_set else "NOT SET")
    sub("DEEPSEEK_API_KEY", "Set" if deepseek_set else "NOT SET")

    if provider == "gemini" and not gemini_set:
        print("  ERROR: --provider gemini but GEMINI_API_KEY is not set in .env")
        ok = False
    if provider == "deepseek" and not deepseek_set:
        print("  ERROR: --provider deepseek but DEEPSEEK_API_KEY is not set in .env")
        ok = False

    # Test DB connection
    try:
        from sqlalchemy import create_engine, text
        db_url = os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('POSTGRES_USER','geoassist')}:"
            f"{os.getenv('POSTGRES_PASSWORD','geoassist_password')}@"
            f"{os.getenv('POSTGRES_HOST','localhost')}:"
            f"{os.getenv('POSTGRES_PORT','5433')}/"
            f"{os.getenv('POSTGRES_DB','geoassist')}"
        )
        engine = create_engine(db_url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        sub("Database", f"OK (PostGIS {version.split()[0]})")
    except Exception as e:
        sub("Database", f"FAILED — {e}")
        ok = False

    if ok:
        print()
        print("  ✓ All checks passed — starting pipeline")
    else:
        print()
        print("  ✗ Preflight failed — fix issues above before proceeding")
    return ok


# ── Phase 0: Business Intelligence ───────────────────────────────────────────
def run_phase0() -> tuple:
    """Returns (business_type, profile, kg_facts, business_profile_section)"""
    section("0", "BUSINESS INTELLIGENCE", "Profile lookup + knowledge graph query")
    business_type = _detect_business_type(QUESTION)
    if not business_type:
        print("  No business type detected — skipping")
        return None, None, {}, ""
    print(f"  Detected business type : {business_type}")
    profile = _get_business_profile(business_type)
    if profile:
        print(f"  Profile source        : database ({profile['display_name']})")
    else:
        print(f"  Profile source        : LLM-generated (not in DB yet)")
        profile = _generate_business_profile_with_llm(business_type, QUESTION)
    kg_facts = _get_kg_facts(business_type)
    n_perm = len(kg_facts.get("permitted",  []))
    n_proh = len(kg_facts.get("prohibited", []))
    n_cond = len(kg_facts.get("conditional", []))
    print(f"  Knowledge graph       : {n_perm} permitted, {n_proh} prohibited, {n_cond} conditional zones")
    if profile and profile.get("legal_zones"):
        print(f"  Legal zones           : {', '.join(profile['legal_zones'])}")
    if profile and profile.get("competitor_table"):
        print(f"  Competitor exclusion  : {profile['competitor_table']} @ {profile.get('competitor_radius_m', '?')}m")
    section_text = _format_business_profile_for_prompt(profile, kg_facts, business_type)
    print()
    print("  Profile injected into LLM system prompt.")
    return business_type, profile, kg_facts, section_text


# ── Phase 1+2: Table selection + schema discovery ────────────────────────────
def run_phase12(verbose: bool) -> tuple:
    """Returns (schema_text, selected_tables, elapsed_s, captured_debug)"""
    section(
        "1+2",
        "TABLE SELECTION  +  SCHEMA DISCOVERY",
        "LLM picks relevant tables → full schema fetched for those tables",
    )

    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        schema_text, selected_tables = _get_database_schema_for_llm(
            QUESTION, _return_selected_tables=True
        )
    elapsed = time.time() - t0
    debug_output = buf.getvalue()

    sub("Elapsed", f"{elapsed:.2f}s")
    sub("Tables selected", str(len(selected_tables)))
    print()
    for i, t in enumerate(selected_tables, 1):
        print(f"    {i:2d}. {t}")

    schema_lines = schema_text.splitlines()
    print()
    sub("Schema size", f"{len(schema_text):,} chars  |  {len(schema_lines)} lines")

    if verbose:
        print()
        print("  [VERBOSE] Internal pipeline output:")
        div("-")
        print(debug_output)
        div("-")

    return schema_text, selected_tables, elapsed, debug_output


# ── Phase 3: Query planning ──────────────────────────────────────────────────
def run_phase3(schema_text: str, verbose: bool) -> tuple:
    """Returns (query_plan, elapsed_s)"""
    section(
        3,
        "QUERY PLANNING",
        "LLM produces validated filter plan using REAL column values from Phase 2",
    )

    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        query_plan = _plan_query_with_llm(QUESTION, schema_text)
    elapsed = time.time() - t0

    sub("Elapsed", f"{elapsed:.2f}s")
    if query_plan:
        confirmed = query_plan.get("confirmed_tables", [])
        sub("Confirmed tables", str(len(confirmed)))
        filter_plan = query_plan.get("filter_plan", {})
        total_filters = sum(len(v.get("filters", [])) for v in filter_plan.values())
        sub("Filter rules", str(total_filters))
        print()
        print("  Query Plan JSON:")
        div("-")
        print(json.dumps(query_plan, indent=4, ensure_ascii=False))
        div("-")
    else:
        print("  [Phase 3 returned empty plan — Phase 4 will proceed without it]")

    if verbose and buf.getvalue().strip():
        print()
        print("  [VERBOSE] Internal pipeline output:")
        print(buf.getvalue())

    return query_plan, elapsed


# ── Phase 4: SQL generation ──────────────────────────────────────────────────
def run_phase4(schema_text: str, query_plan: dict, provider: str, verbose: bool, business_profile_section: str = "") -> tuple:
    """Returns (operation_plan, sql_text, elapsed_s)"""
    section(
        4,
        "SQL GENERATION",
        f"Provider: {provider.upper()}  |  Translates query plan to PostGIS SQL",
    )

    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        try:
            if provider == "deepseek":
                resp = query_deepseek(
                    QUESTION,
                    precomputed_schema=schema_text,
                    query_plan=query_plan,
                    business_profile_section=business_profile_section,
                )
            else:
                resp = query_gemini(
                    QUESTION,
                    precomputed_schema=schema_text,
                    query_plan=query_plan,
                )
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR calling {provider}: {e}")
            return None, "", elapsed

    elapsed = time.time() - t0

    sub("Elapsed", f"{elapsed:.2f}s")
    sub("Provider", provider.upper())

    raw_content = resp.get("content", "")
    system_prompt = resp.get("system_prompt", "")

    # Parse the JSON response into OperationPlan (replicate parse_geospatial_query logic)
    from app.models.query_model import OperationPlan, GeospatialOperation
    import re

    try:
        cleaned = raw_content.strip()
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if not cleaned.startswith("{"):
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m:
                cleaned = m.group(0)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Escape-fix retry
            fixed = re.sub(
                r'"sql"\s*:\s*"((?:[^"\\]|\\.)*?(?:SELECT|WITH)[^"]*?)"',
                lambda m: f'"sql": "{m.group(1).replace(chr(34), chr(92)+chr(34))}"',
                cleaned,
                flags=re.IGNORECASE | re.DOTALL,
            )
            parsed = json.loads(fixed)

        operations = [GeospatialOperation(**op) for op in parsed.get("operations", [])]
        plan = OperationPlan(
            operations=operations,
            layer_name=parsed.get("layer_name"),
            reasoning=parsed.get("reasoning"),
            datasets_required=parsed.get("datasets_required", []),
            system_prompt=system_prompt,
            user_prompt=QUESTION,
        )

    except Exception as e:
        print(f"  ERROR parsing LLM response: {e}")
        print("  Raw LLM output (first 2000 chars):")
        print(raw_content[:2000])
        return None, raw_content, elapsed

    # Extract SQL
    sql_text = ""
    for op in plan.operations:
        op_name = op.operation.value if hasattr(op.operation, "value") else str(op.operation)
        if op_name in ("spatial_query", "load"):
            candidate = op.parameters.get("sql", "")
            if candidate:
                sql_text = candidate
                break

    sub("Operations count", str(len(plan.operations)))
    if plan.operations:
        op_types = [
            (op.operation.value if hasattr(op.operation, "value") else str(op.operation))
            for op in plan.operations
        ]
        sub("Operation types", ", ".join(op_types))
    sub("Reasoning", plan.reasoning or "—")

    if sql_text:
        print()
        print("  Generated SQL:")
        div("-")
        print(sql_text)
        div("-")
    else:
        print()
        print("  [No SQL found in operations — raw LLM response:]")
        div("-")
        print(raw_content[:3000])
        div("-")

    if verbose and system_prompt:
        print()
        print("  [VERBOSE] System prompt sent to LLM (first 3000 chars):")
        div("-")
        print(system_prompt[:3000])
        div("-")

    return plan, sql_text, elapsed


# ── Execution ─────────────────────────────────────────────────────────────────
def run_execution(plan, save_geojson: bool) -> tuple:
    """Returns (features_list, elapsed_s)"""
    section(
        "EX",
        "EXECUTION",
        "Running generated SQL against PostGIS database",
    )

    engine = SpatialEngine()
    t0 = time.time()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = engine.execute_plan(plan)
    elapsed = time.time() - t0

    sub("Elapsed", f"{elapsed:.2f}s")

    if not result or not result.get("success", False):
        err = result.get("error", "Unknown error") if result else "execute_plan returned None"
        print(f"  ERROR: {err}")
        return [], elapsed

    data = result.get("data", {})
    features = data.get("features", []) if isinstance(data, dict) else []
    sub("Features returned", str(len(features)))

    if features:
        print()
        # Table header
        col_w = [4, 12, 10, 10, 20, 30]
        headers = ["Rank", "Area (sqm)", "Latitude", "Longitude", "Landuse", "Notes/Name"]
        row_fmt = "  {:>{}}  {:>{}}  {:>{}}  {:>{}}  {:<{}}  {:<{}}"

        print(row_fmt.format(
            headers[0], col_w[0],
            headers[1], col_w[1],
            headers[2], col_w[2],
            headers[3], col_w[3],
            headers[4], col_w[4],
            headers[5], col_w[5],
        ))
        div("-")

        for rank, feat in enumerate(features[:5], 1):
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})

            # Latitude/Longitude from geometry centroid
            lat = lon = "—"
            if geom:
                gtype = geom.get("type", "")
                coords = geom.get("coordinates", [])
                try:
                    if gtype == "Point" and coords:
                        lon, lat = f"{coords[0]:.5f}", f"{coords[1]:.5f}"
                    elif gtype in ("Polygon", "MultiPolygon") and coords:
                        # Rough centroid from first ring
                        ring = coords[0] if gtype == "Polygon" else coords[0][0]
                        avg_lon = sum(c[0] for c in ring) / len(ring)
                        avg_lat = sum(c[1] for c in ring) / len(ring)
                        lon, lat = f"{avg_lon:.5f}", f"{avg_lat:.5f}"
                except Exception:
                    pass

            # Area
            area_raw = (
                props.get("area_sqm")
                or props.get("flaecheqm")
                or props.get("area")
                or props.get("shape_area")
                or "—"
            )
            try:
                area_display = f"{float(area_raw):,.0f}"
            except (TypeError, ValueError):
                area_display = str(area_raw)

            # Landuse
            landuse = (
                props.get("landuse")
                or props.get("nutzart")
                or props.get("bezgfk")
                or "—"
            )

            # Name/notes
            name = (
                props.get("name")
                or props.get("address")
                or props.get("composite_score")
                or props.get("total_score")
                or "—"
            )
            name_str = str(name)[:28]

            print(row_fmt.format(
                rank, col_w[0],
                area_display, col_w[1],
                lat, col_w[2],
                lon, col_w[3],
                str(landuse)[:18], col_w[4],
                name_str, col_w[5],
            ))

    if save_geojson and features:
        out_path = REPO_ROOT / "supermarket_sites_marzahn.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print()
        sub("GeoJSON saved", str(out_path))

    return features, elapsed


# ── Phase 5: Result evaluation ────────────────────────────────────────────────
def run_phase5(features: list, profile, business_type: str) -> dict:
    """Returns verdict dict {pass, issues, warnings}"""
    section("5", "RESULT EVALUATION", "Rule-based quality check on returned locations")
    if not business_type or not features:
        print("  Skipped — no business type detected or no features returned")
        return {}
    # Flatten GeoJSON features to property dicts with lat/lon added
    flat = []
    for f in features:
        props = dict(f.get("properties", {}) or {})
        geom  = f.get("geometry", {}) or {}
        coords = geom.get("coordinates", [])
        try:
            if geom.get("type") == "Point":
                props["lat"] = coords[1]
                props["lon"] = coords[0]
            elif geom.get("type") in ("Polygon", "MultiPolygon"):
                ring = coords[0] if geom["type"] == "Polygon" else coords[0][0]
                props["lat"] = sum(c[1] for c in ring) / len(ring)
                props["lon"] = sum(c[0] for c in ring) / len(ring)
        except Exception:
            pass
        flat.append(props)

    verdict  = _evaluate_results(flat, profile, business_type)
    passed   = verdict.get("pass", True)
    issues   = verdict.get("issues",   [])
    warnings = verdict.get("warnings", [])
    print(f"  Verdict   : {'PASS ✓' if passed else 'FAIL ✗'}")
    for iss in issues:
        print(f"  ISSUE     : {iss}")
    for w in warnings:
        print(f"  WARNING   : {w}")
    if passed and not warnings:
        print("  No quality issues detected.")
    return verdict


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary(timings: dict, plan, features, provider: str, bt: str = None, verdict: dict = None):
    header("PIPELINE SUMMARY")

    total = sum(timings.values())
    verdict_str = ""
    if verdict:
        verdict_str = "PASS" if verdict.get("pass") else f"FAIL ({len(verdict.get('issues',[]))} issue(s))"
    rows = [
        ("Phase 0    Business Intelligence",      timings.get("phase0",  0),   f"business: {bt or '—'}"),
        ("Phase 1+2  Table Selection + Schema",   timings.get("phase12", 0),   ""),
        ("Phase 3    Query Planning",             timings.get("phase3",  0),   ""),
        ("Phase 4    SQL Generation",             timings.get("phase4",  0),   f"provider: {provider}"),
        ("Execution  PostGIS",                    timings.get("exec",    0),   f"{len(features)} features returned"),
        ("Phase 5    Result Evaluation",          timings.get("phase5",  0),   verdict_str),
    ]
    for label, t, note in rows:
        note_str = f"  [{note}]" if note else ""
        print(f"  {label:<42}  {t:>6.2f}s{note_str}")

    div("-")
    print(f"  {'TOTAL':<42}  {total:>6.2f}s")

    if plan:
        print()
        datasets = plan.datasets_required or []
        if datasets:
            sub("Tables used", ", ".join(datasets))
        ops = [
            (op.operation.value if hasattr(op.operation, "value") else str(op.operation))
            for op in (plan.operations or [])
        ]
        sub("Operations", ", ".join(ops) if ops else "—")


# ── Improvement suggestions ───────────────────────────────────────────────────
def print_improvements():
    header("SUGGESTED IMPROVEMENTS")
    improvements = [
        (
            "1. WALKING ISOCHRONE vs. STRAIGHT-LINE BUFFER",
            "   Criterion 6 ('10-minute walk to 500+ residential buildings') is currently "
            "approximated\n"
            "   with ST_DWithin(~700m radius). Real walking distance follows road networks.\n"
            "   The app already has a Valhalla isochrone API:\n"
            "     POST /api/walking-distance/coverage  →  returns actual walkable polygon.\n"
            "   Use that polygon in an ST_Within() check instead of a circular buffer.",
        ),
        (
            "2. AREA CALCULATION — VERIFY CORRECT CRS",
            "   ST_Area(geometry) uses degrees² (EPSG:4326) → wildly wrong sq meter values.\n"
            "   ST_Area(geom_25833) uses meters² (EPSG:25833 UTM) → correct.\n"
            "   Inspect the generated SQL: confirm the >700 sqm filter uses geom_25833,\n"
            "   not the geometry column. If not, ask the LLM to specify the projected column.",
        ),
        (
            "3. SPATIAL INDEX COVERAGE",
            "   Every ST_DWithin() call (500m supermarket exclusion, transport proximity,\n"
            "   parking proximity) needs a GiST index on geom_25833 for the target table.\n"
            "   Run:  EXPLAIN ANALYZE <generated SQL>\n"
            "   Look for 'Seq Scan' on osm_supermarkets, osm_transport_stops, osm_parking.\n"
            "   Fix:  CREATE INDEX ON vector.<table> USING GIST (geom_25833);",
        ),
        (
            "4. MCDA SCORING — EXPOSE PER-CRITERION SCORES",
            "   The app's SpatialEngine.apply_mcda_scoring() computes composite suitability\n"
            "   scores. For this 6-criteria query the MCDA step fires, but the individual\n"
            "   criterion scores (transport_score, competition_score, etc.) are usually\n"
            "   collapsed into a single composite_score.\n"
            "   Improvement: ask the LLM to include named score columns in the SQL SELECT\n"
            "   (e.g., transport_score, parking_score, building_count) so the result table\n"
            "   shows WHY each location ranked where it did.",
        ),
        (
            "5. RESIDENTIAL BUILDING COUNT LOGIC",
            "   'Serve 500+ residential buildings' requires joining alkis_buildings filtered\n"
            "   by residential function codes (bezgfk LIKE '1%' in ALKIS classification).\n"
            "   Verify the generated SQL counts only residential buildings, not all buildings.\n"
            "   Also consider whether the Valhalla isochrone polygon (improvement #1) is used\n"
            "   as the spatial filter for counting residential buildings.",
        ),
    ]
    for title, body in improvements:
        print()
        print(f"  {title}")
        print(body)
    print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Run supermarket site-selection query through the AI Geospatial pipeline"
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "deepseek"],
        default="gemini",
        help="LLM provider for SQL generation (default: gemini)",
    )
    parser.add_argument(
        "--save-geojson",
        action="store_true",
        help="Save top-5 results to supermarket_sites_marzahn.geojson",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print internal LLM debug output and system prompts",
    )
    args = parser.parse_args()

    banner("AI GEOSPATIAL DIAGNOSTIC — SUPERMARKET SITE SELECTION")
    print(f"  Query  : {QUESTION[:100]}...")
    print(f"  Provider: {args.provider.upper()}")

    # Preflight
    if not run_preflight(args.provider):
        sys.exit(1)

    # Initialize db_manager so Phase 0 can connect to business_profiles / knowledge_graph
    from app.utils.database import db_manager as _dbm
    if _dbm.engine is None:
        _dbm.initialize()

    timings = {}

    # Phase 0
    t0_start = time.time()
    bt, profile, kg_facts, bp_section = run_phase0()
    timings["phase0"] = time.time() - t0_start

    # Phase 1+2
    schema_text, selected_tables, t12, _ = run_phase12(args.verbose)
    timings["phase12"] = t12

    # Phase 3
    query_plan, t3 = run_phase3(schema_text, args.verbose)
    timings["phase3"] = t3

    # Phase 4
    plan, sql_text, t4 = run_phase4(schema_text, query_plan, args.provider, args.verbose, bp_section)
    timings["phase4"] = t4

    # Execution
    features, tex = [], 0.0
    if plan:
        features, tex = run_execution(plan, args.save_geojson)
    else:
        section("EX", "EXECUTION", "Skipped — Phase 4 did not produce a valid plan")
    timings["exec"] = tex

    # Phase 5
    t5_start = time.time()
    verdict = run_phase5(features, profile, bt)
    timings["phase5"] = time.time() - t5_start

    # Summary
    print_summary(timings, plan, features, args.provider, bt=bt, verdict=verdict)

    # Improvements
    print_improvements()

    div()
    print()


if __name__ == "__main__":
    main()
