"""
Business Intelligence Setup
============================
Creates and seeds:
  1. vector.business_profiles  — site-selection criteria per business type
  2. metadata.knowledge_graph  — BauNVO legal zone rules + data mappings

Run once:
  conda run -n geoassist python scripts/setup_business_intelligence.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER','geoassist')}:"
    f"{os.getenv('POSTGRES_PASSWORD','geoassist_password')}@"
    f"{os.getenv('POSTGRES_HOST','localhost')}:"
    f"{os.getenv('POSTGRES_PORT','5433')}/"
    f"{os.getenv('POSTGRES_DB','geoassist')}"
)

engine = create_engine(DB_URL)

W = 70

def section(title):
    print(f"\n{'='*W}\n  {title}\n{'='*W}")

def ok(msg):  print(f"  ✅ {msg}")
def info(msg): print(f"  ℹ  {msg}")
def warn(msg): print(f"  ⚠️  {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. CREATE TABLES
# ─────────────────────────────────────────────────────────────────────────────

CREATE_BUSINESS_PROFILES = """
CREATE TABLE IF NOT EXISTS vector.business_profiles (
    business_type        VARCHAR(100) PRIMARY KEY,
    display_name         VARCHAR(200),
    legal_zones          TEXT[],        -- inhalt ILIKE patterns for B-Plan condition A
    suitable_bezgfk      TEXT[],        -- building function values to prefer
    avoid_bezgfk         TEXT[],        -- building function values to EXCLUDE
    competitor_table     VARCHAR(100),  -- OSM table name for competitor exclusion
    competitor_filter    TEXT,          -- optional WHERE fragment (e.g. "shop='beauty'")
    competitor_radius_m  INT  DEFAULT 500,
    min_area_sqm         INT  DEFAULT 100,
    parking_radius_m     INT  DEFAULT 300,
    transport_radius_m   INT  DEFAULT 400,
    min_residential_buildings INT DEFAULT 300,
    residential_radius_m INT  DEFAULT 800,
    weight_residential   NUMERIC(4,2) DEFAULT 0.40,
    weight_competitor    NUMERIC(4,2) DEFAULT 0.30,
    weight_access        NUMERIC(4,2) DEFAULT 0.30,
    bonus_tables         TEXT[],        -- e.g. ARRAY['osm_parks:300']
    notes                TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_KNOWLEDGE_GRAPH = """
CREATE TABLE IF NOT EXISTS metadata.knowledge_graph (
    id          SERIAL PRIMARY KEY,
    subject     VARCHAR(200) NOT NULL,   -- business type or entity
    predicate   VARCHAR(100) NOT NULL,   -- permitted_in / prohibited_in / data_in / demand_from
    object      VARCHAR(200) NOT NULL,   -- zone name / table name
    weight      NUMERIC(4,2) DEFAULT 1.0,
    condition   TEXT,                    -- e.g. 'floor_area_sqm > 800'
    law_ref     VARCHAR(100),            -- e.g. 'BauNVO §11 Abs.3'
    domain      VARCHAR(50)  DEFAULT 'business',
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS kg_subject_idx ON metadata.knowledge_graph(subject);
CREATE INDEX IF NOT EXISTS kg_predicate_idx ON metadata.knowledge_graph(predicate);
"""


# ─────────────────────────────────────────────────────────────────────────────
# 2. BUSINESS PROFILES SEED DATA
# ─────────────────────────────────────────────────────────────────────────────

BUSINESS_PROFILES = [
    {
        "business_type": "veterinary_clinic",
        "display_name": "Veterinary Clinic (Tierarztpraxis)",
        "legal_zones": ["Wohngebiet", "Mischgebiet", "Kerngebiet"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Dienstleistungsgebäude", "Bürogebäude"],
        "avoid_bezgfk": ["Seniorenheim", "Krankenhaus", "Schule", "Industriegebäude", "Lagergebäude"],
        "competitor_table": "osm_veterinary",
        "competitor_filter": None,
        "competitor_radius_m": 1000,
        "min_area_sqm": 150,
        "parking_radius_m": 300,
        "transport_radius_m": 500,
        "min_residential_buildings": 300,
        "residential_radius_m": 800,
        "weight_residential": 0.40,
        "weight_competitor": 0.35,
        "weight_access": 0.25,
        "bonus_tables": ["osm_parks:300"],
        "notes": "Pet owners drive; park proximity signals dog-walking demand.",
    },
    {
        "business_type": "pharmacy",
        "display_name": "Pharmacy (Apotheke)",
        "legal_zones": ["Wohngebiet", "Mischgebiet", "Kerngebiet", "Nahversorgungszentrum"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Einzelhandelsgebäude", "Dienstleistungsgebäude"],
        "avoid_bezgfk": ["Industriegebäude", "Lagergebäude", "Seniorenheim"],
        "competitor_table": "osm_pharmacies",
        "competitor_filter": None,
        "competitor_radius_m": 500,
        "min_area_sqm": 80,
        "parking_radius_m": 200,
        "transport_radius_m": 400,
        "min_residential_buildings": 500,
        "residential_radius_m": 600,
        "weight_residential": 0.40,
        "weight_competitor": 0.35,
        "weight_access": 0.25,
        "bonus_tables": ["osm_doctors:300", "osm_hospitals:500"],
        "notes": "Proximity to doctors and hospitals increases demand.",
    },
    {
        "business_type": "supermarket",
        "display_name": "Supermarket (Lebensmitteleinzelhandel)",
        "legal_zones": ["Mischgebiet", "Kerngebiet", "Nahversorgungszentrum"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Einzelhandelsgebäude"],
        "avoid_bezgfk": ["Wohnhaus", "Industriegebäude", "Seniorenheim", "Schule"],
        "competitor_table": "osm_supermarkets",
        "competitor_filter": None,
        "competitor_radius_m": 500,
        "min_area_sqm": 700,
        "parking_radius_m": 200,
        "transport_radius_m": 400,
        "min_residential_buildings": 500,
        "residential_radius_m": 800,
        "weight_residential": 0.40,
        "weight_competitor": 0.30,
        "weight_access": 0.30,
        "bonus_tables": [],
        "notes": "Large-scale retail (>800sqm) requires SO/MK zone under BauNVO §11 Abs.3.",
    },
    {
        "business_type": "cafe",
        "display_name": "Café / Coffee Shop",
        "legal_zones": ["Mischgebiet", "Kerngebiet", "Nahversorgungszentrum", "Wohngebiet"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Einzelhandelsgebäude", "Gaststättengebäude"],
        "avoid_bezgfk": ["Industriegebäude", "Lagergebäude", "Seniorenheim"],
        "competitor_table": "osm_cafes",
        "competitor_filter": None,
        "competitor_radius_m": 300,
        "min_area_sqm": 60,
        "parking_radius_m": 200,
        "transport_radius_m": 300,
        "min_residential_buildings": 200,
        "residential_radius_m": 600,
        "weight_residential": 0.35,
        "weight_competitor": 0.30,
        "weight_access": 0.35,
        "bonus_tables": ["osm_universities:500", "osm_parks:300"],
        "notes": "Footfall generators (universities, parks, transport) are the key demand signal.",
    },
    {
        "business_type": "restaurant",
        "display_name": "Restaurant",
        "legal_zones": ["Mischgebiet", "Kerngebiet", "Nahversorgungszentrum"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Gaststättengebäude", "Einzelhandelsgebäude"],
        "avoid_bezgfk": ["Industriegebäude", "Lagergebäude"],
        "competitor_table": "osm_restaurants",
        "competitor_filter": None,
        "competitor_radius_m": 250,
        "min_area_sqm": 100,
        "parking_radius_m": 200,
        "transport_radius_m": 300,
        "min_residential_buildings": 300,
        "residential_radius_m": 600,
        "weight_residential": 0.35,
        "weight_competitor": 0.30,
        "weight_access": 0.35,
        "bonus_tables": ["osm_tourist_info:500"],
        "notes": "Tourism clusters and office density are key demand signals.",
    },
    {
        "business_type": "gym",
        "display_name": "Gym / Fitness Studio",
        "legal_zones": ["Mischgebiet", "Kerngebiet", "Gewerbegebiet"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Sporthalle", "Dienstleistungsgebäude"],
        "avoid_bezgfk": ["Wohnhaus", "Seniorenheim", "Schule", "Industriegebäude"],
        "competitor_table": "osm_sports_centres",
        "competitor_filter": None,
        "competitor_radius_m": 1500,
        "min_area_sqm": 400,
        "parking_radius_m": 300,
        "transport_radius_m": 500,
        "min_residential_buildings": 500,
        "residential_radius_m": 1000,
        "weight_residential": 0.40,
        "weight_competitor": 0.35,
        "weight_access": 0.25,
        "bonus_tables": [],
        "notes": "Needs large floor area; residential density within 1km drives membership demand.",
    },
    {
        "business_type": "kindergarten",
        "display_name": "Kindergarten / Kita",
        "legal_zones": ["Wohngebiet", "Mischgebiet", "Gemeinbedarf"],
        "suitable_bezgfk": ["Wohnhaus", "Gebäude für Gemeinbedarf", "Schule"],
        "avoid_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Industriegebäude", "Gaststättengebäude"],
        "competitor_table": "osm_kindergartens",
        "competitor_filter": None,
        "competitor_radius_m": 500,
        "min_area_sqm": 200,
        "parking_radius_m": 300,
        "transport_radius_m": 600,
        "min_residential_buildings": 400,
        "residential_radius_m": 600,
        "weight_residential": 0.50,
        "weight_competitor": 0.30,
        "weight_access": 0.20,
        "bonus_tables": ["osm_schools:500"],
        "notes": "Must be in or adjacent to residential zones. Proximity to schools is a positive signal.",
    },
    {
        "business_type": "dental_practice",
        "display_name": "Dental Practice (Zahnarztpraxis)",
        "legal_zones": ["Wohngebiet", "Mischgebiet", "Kerngebiet"],
        "suitable_bezgfk": ["Gebäude für Wirtschaft oder Gewerbe", "Dienstleistungsgebäude", "Bürogebäude", "Wohnhaus"],
        "avoid_bezgfk": ["Seniorenheim", "Industriegebäude", "Lagergebäude"],
        "competitor_table": "osm_dentists",
        "competitor_filter": None,
        "competitor_radius_m": 800,
        "min_area_sqm": 100,
        "parking_radius_m": 300,
        "transport_radius_m": 500,
        "min_residential_buildings": 400,
        "residential_radius_m": 800,
        "weight_residential": 0.40,
        "weight_competitor": 0.35,
        "weight_access": 0.25,
        "bonus_tables": [],
        "notes": "Population density per subdivision is the primary demand signal.",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 3. KNOWLEDGE GRAPH SEED DATA
# ─────────────────────────────────────────────────────────────────────────────

# predicate options:
#   permitted_in          — business is permitted in this BauNVO zone by right
#   conditionally_permitted_in — permitted with conditions (Ausnahme)
#   prohibited_in         — explicitly not permitted
#   data_in               — competitor/existing data lives in this table
#   demand_from           — this table is a demand generator for this business

KNOWLEDGE_GRAPH = [
    # ── Veterinary Clinic ─────────────────────────────────────────────────
    ("veterinary_clinic", "permitted_in",   "Wohngebiet",   1.0, None, "BauNVO §4 Abs.2"),
    ("veterinary_clinic", "permitted_in",   "Mischgebiet",  1.0, None, "BauNVO §6"),
    ("veterinary_clinic", "permitted_in",   "Kerngebiet",   1.0, None, "BauNVO §7"),
    ("veterinary_clinic", "permitted_in",   "Gewerbegebiet",0.8, "small practices only", "BauNVO §8"),
    ("veterinary_clinic", "data_in",        "osm_veterinary", 1.0, None, None),
    ("veterinary_clinic", "demand_from",    "osm_parks",    0.3, "300", None),

    # ── Pharmacy ──────────────────────────────────────────────────────────
    ("pharmacy", "permitted_in",   "Wohngebiet",          1.0, None, "BauNVO §4"),
    ("pharmacy", "permitted_in",   "Mischgebiet",         1.0, None, "BauNVO §6"),
    ("pharmacy", "permitted_in",   "Kerngebiet",          1.0, None, "BauNVO §7"),
    ("pharmacy", "permitted_in",   "Nahversorgungszentrum",1.0, None, "BauNVO §11"),
    ("pharmacy", "data_in",        "osm_pharmacies",      1.0, None, None),
    ("pharmacy", "demand_from",    "osm_doctors",         0.3, "300", None),
    ("pharmacy", "demand_from",    "osm_hospitals",       0.4, "500", None),

    # ── Supermarket ───────────────────────────────────────────────────────
    ("supermarket", "permitted_in",   "Nahversorgungszentrum", 1.0, None, "BauNVO §11"),
    ("supermarket", "permitted_in",   "Kerngebiet",            1.0, None, "BauNVO §7"),
    ("supermarket", "permitted_in",   "Mischgebiet",           0.8, "floor_area_sqm <= 800", "BauNVO §6"),
    ("supermarket", "conditionally_permitted_in", "Mischgebiet", 0.6, "floor_area_sqm <= 800", "BauNVO §6"),
    ("supermarket", "prohibited_in",  "Gewerbegebiet",         1.0, "floor_area_sqm > 800", "BauNVO §11 Abs.3"),
    ("supermarket", "prohibited_in",  "Wohngebiet",            1.0, None, "BauNVO §4"),
    ("supermarket", "data_in",        "osm_supermarkets",      1.0, None, None),

    # ── Café ──────────────────────────────────────────────────────────────
    ("cafe", "permitted_in",   "Mischgebiet",           1.0, None, "BauNVO §6"),
    ("cafe", "permitted_in",   "Kerngebiet",            1.0, None, "BauNVO §7"),
    ("cafe", "permitted_in",   "Nahversorgungszentrum", 1.0, None, "BauNVO §11"),
    ("cafe", "permitted_in",   "Wohngebiet",            0.7, "small, neighbourhood-serving", "BauNVO §4 Abs.2"),
    ("cafe", "data_in",        "osm_cafes",             1.0, None, None),
    ("cafe", "demand_from",    "osm_universities",      0.4, "500", None),
    ("cafe", "demand_from",    "osm_parks",             0.3, "300", None),
    ("cafe", "demand_from",    "osm_transport_stops",   0.3, "200", None),

    # ── Restaurant ────────────────────────────────────────────────────────
    ("restaurant", "permitted_in",   "Mischgebiet",           1.0, None, "BauNVO §6"),
    ("restaurant", "permitted_in",   "Kerngebiet",            1.0, None, "BauNVO §7"),
    ("restaurant", "permitted_in",   "Nahversorgungszentrum", 1.0, None, "BauNVO §11"),
    ("restaurant", "data_in",        "osm_restaurants",       1.0, None, None),
    ("restaurant", "demand_from",    "osm_tourist_info",      0.3, "500", None),

    # ── Gym ───────────────────────────────────────────────────────────────
    ("gym", "permitted_in",   "Mischgebiet",  1.0, None, "BauNVO §6"),
    ("gym", "permitted_in",   "Kerngebiet",   1.0, None, "BauNVO §7"),
    ("gym", "permitted_in",   "Gewerbegebiet",0.9, None, "BauNVO §8"),
    ("gym", "data_in",        "osm_sports_centres", 1.0, None, None),

    # ── Kindergarten ──────────────────────────────────────────────────────
    ("kindergarten", "permitted_in",   "Wohngebiet",  1.0, None, "BauNVO §4"),
    ("kindergarten", "permitted_in",   "Mischgebiet", 1.0, None, "BauNVO §6"),
    ("kindergarten", "prohibited_in",  "Gewerbegebiet", 1.0, None, "BauNVO §8"),
    ("kindergarten", "data_in",        "osm_kindergartens", 1.0, None, None),
    ("kindergarten", "demand_from",    "osm_schools", 0.3, "500", None),

    # ── Dental Practice ───────────────────────────────────────────────────
    ("dental_practice", "permitted_in",   "Wohngebiet",  1.0, None, "BauNVO §4"),
    ("dental_practice", "permitted_in",   "Mischgebiet", 1.0, None, "BauNVO §6"),
    ("dental_practice", "permitted_in",   "Kerngebiet",  1.0, None, "BauNVO §7"),
    ("dental_practice", "data_in",        "osm_dentists", 1.0, None, None),
]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run():
    section("Step 1 — Create tables")
    with engine.begin() as conn:
        conn.execute(text(CREATE_BUSINESS_PROFILES))
        ok("vector.business_profiles created (or already exists)")
        conn.execute(text(CREATE_KNOWLEDGE_GRAPH))
        ok("metadata.knowledge_graph created (or already exists)")

    section("Step 2 — Seed business profiles")
    with engine.begin() as conn:
        inserted = 0
        for p in BUSINESS_PROFILES:
            conn.execute(text("""
                INSERT INTO vector.business_profiles (
                    business_type, display_name, legal_zones, suitable_bezgfk,
                    avoid_bezgfk, competitor_table, competitor_filter,
                    competitor_radius_m, min_area_sqm, parking_radius_m,
                    transport_radius_m, min_residential_buildings,
                    residential_radius_m, weight_residential, weight_competitor,
                    weight_access, bonus_tables, notes
                ) VALUES (
                    :business_type, :display_name, :legal_zones, :suitable_bezgfk,
                    :avoid_bezgfk, :competitor_table, :competitor_filter,
                    :competitor_radius_m, :min_area_sqm, :parking_radius_m,
                    :transport_radius_m, :min_residential_buildings,
                    :residential_radius_m, :weight_residential, :weight_competitor,
                    :weight_access, :bonus_tables, :notes
                )
                ON CONFLICT (business_type) DO UPDATE SET
                    display_name=EXCLUDED.display_name,
                    legal_zones=EXCLUDED.legal_zones,
                    suitable_bezgfk=EXCLUDED.suitable_bezgfk,
                    avoid_bezgfk=EXCLUDED.avoid_bezgfk,
                    competitor_table=EXCLUDED.competitor_table,
                    competitor_filter=EXCLUDED.competitor_filter,
                    competitor_radius_m=EXCLUDED.competitor_radius_m,
                    min_area_sqm=EXCLUDED.min_area_sqm,
                    parking_radius_m=EXCLUDED.parking_radius_m,
                    transport_radius_m=EXCLUDED.transport_radius_m,
                    min_residential_buildings=EXCLUDED.min_residential_buildings,
                    residential_radius_m=EXCLUDED.residential_radius_m,
                    weight_residential=EXCLUDED.weight_residential,
                    weight_competitor=EXCLUDED.weight_competitor,
                    weight_access=EXCLUDED.weight_access,
                    bonus_tables=EXCLUDED.bonus_tables,
                    notes=EXCLUDED.notes,
                    updated_at=NOW()
            """), p)
            inserted += 1
        ok(f"Upserted {inserted} business profiles")

    section("Step 3 — Seed knowledge graph")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM metadata.knowledge_graph WHERE domain = 'business'"))
        inserted = 0
        for (subj, pred, obj, weight, condition, law_ref) in KNOWLEDGE_GRAPH:
            conn.execute(text("""
                INSERT INTO metadata.knowledge_graph
                    (subject, predicate, object, weight, condition, law_ref, domain)
                VALUES (:s, :p, :o, :w, :c, :l, 'business')
            """), {"s": subj, "p": pred, "o": obj, "w": weight, "c": condition, "l": law_ref})
            inserted += 1
        ok(f"Inserted {inserted} knowledge graph triples")

    section("Step 4 — Register business_profiles with auto-discovery")
    try:
        from app.utils.auto_discovery import AutoTableDiscovery
        existing = AutoTableDiscovery.get_new_tables()
        if "business_profiles" in existing:
            info("Triggering auto-discovery for business_profiles...")
            AutoTableDiscovery.discover_single_table("business_profiles")
            ok("Auto-discovery complete")
        else:
            info("business_profiles already registered — updating usage_hint manually")
        # Always update usage_hint to ensure correct Phase 1 behaviour
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE metadata.table_descriptions SET
                    usage_hint = :hint,
                    key_columns = ARRAY['business_type','display_name','legal_zones',
                                        'suitable_bezgfk','avoid_bezgfk',
                                        'competitor_table','competitor_radius_m',
                                        'min_area_sqm','weight_residential'],
                    analysis_patterns = ARRAY['site_selection','business_location','planning']
                WHERE table_name = 'business_profiles'
            """), {"hint": (
                "ALWAYS include this table for any business site selection, location finding, "
                "or 'where should I open X' query. "
                "JOIN on business_type to get: legal_zones (array of B-Plan inhalt values to "
                "filter wfs_bplan_b_bp_fs), suitable_bezgfk (array of alkis_buildings bezgfk "
                "building function values), avoid_bezgfk (building types to EXCLUDE), "
                "competitor_table (OSM table name for competitor exclusion), "
                "competitor_radius_m, min_area_sqm, parking_radius_m, transport_radius_m, "
                "min_residential_buildings, weight_residential, weight_competitor, weight_access. "
                "Read the profile row first, then apply all values as spatial filters and scoring weights."
            )})
        ok("usage_hint updated for business_profiles")
    except Exception as e:
        warn(f"Auto-discovery step failed (non-fatal): {e}")

    section("Step 5 — Verify")
    with engine.connect() as conn:
        n_profiles = conn.execute(text("SELECT COUNT(*) FROM vector.business_profiles")).scalar()
        n_kg = conn.execute(text("SELECT COUNT(*) FROM metadata.knowledge_graph")).scalar()
        n_permitted = conn.execute(text(
            "SELECT COUNT(*) FROM metadata.knowledge_graph WHERE predicate='permitted_in'"
        )).scalar()
        n_prohibited = conn.execute(text(
            "SELECT COUNT(*) FROM metadata.knowledge_graph WHERE predicate='prohibited_in'"
        )).scalar()
        ok(f"business_profiles: {n_profiles} rows")
        ok(f"knowledge_graph: {n_kg} triples ({n_permitted} permitted_in, {n_prohibited} prohibited_in)")

        print()
        print("  Sample profiles:")
        rows = conn.execute(text(
            "SELECT business_type, display_name, competitor_table, competitor_radius_m "
            "FROM vector.business_profiles ORDER BY business_type"
        )).fetchall()
        for r in rows:
            print(f"    {r[0]:<25} competitor: {r[2] or 'none':<25} radius: {r[3]}m")

    print(f"\n{'='*W}")
    print("  ✅  Business Intelligence setup complete.")
    print(f"{'='*W}\n")


if __name__ == "__main__":
    run()
