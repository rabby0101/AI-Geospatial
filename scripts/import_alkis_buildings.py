"""
Import ALKIS Gebäude (buildings) from Berlin Senate WFS into PostGIS.

Creates and populates vector.alkis_buildings with 782k authoritative
cadastral building footprints (CC0, EPSG:25833).

Usage:
    python scripts/import_alkis_buildings.py

Environment:
    DATABASE_URL or individual DB_* env vars (same as app).
"""

import os
import sys
import time
import logging
import requests
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── WFS constants ──────────────────────────────────────────────────────────────
WFS_URL = "https://gdi.berlin.de/services/wfs/alkis_gebaeude"
LAYER   = "alkis_gebaeude:gebaeude"
PAGE_SIZE = 1000      # features per request
MAX_PAGES = 2000      # safety cap  (2 000 × 1 000 = 2 M features)
REQUEST_TIMEOUT = 60  # seconds per HTTP request

# ── GFK → building category mapping ───────────────────────────────────────────
def gfk_to_building(gfk: Optional[int]) -> str:
    """Map ALKIS building function code to a backward-compatible category."""
    if gfk is None:
        return "yes"
    if 1000 <= gfk <= 1999:
        return "residential"
    if 2000 <= gfk <= 2099:
        return "residential"
    if 2100 <= gfk <= 2999:
        return "commercial"
    if 3000 <= gfk <= 3019:
        return "commercial"
    if 3020 <= gfk <= 3029:
        return "office"
    if 3030 <= gfk <= 3059:
        return "retail"
    if 3060 <= gfk <= 3099:
        return "retail"
    if 3100 <= gfk <= 3999:
        return "commercial"
    return "yes"


# ── DB helpers ─────────────────────────────────────────────────────────────────
def get_engine():
    """Build a SQLAlchemy engine from env vars."""
    from sqlalchemy import create_engine

    url = os.getenv("DATABASE_URL")
    if not url:
        host   = os.getenv("DB_HOST",     "localhost")
        port   = os.getenv("DB_PORT",     "5432")
        db     = os.getenv("DB_NAME",     "berlin_geodata")
        user   = os.getenv("DB_USER",     "postgres")
        passwd = os.getenv("DB_PASSWORD", "postgres")
        url = f"postgresql://{user}:{passwd}@{host}:{port}/{db}"

    return create_engine(url, pool_pre_ping=True)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS vector.alkis_buildings (
    uuid        TEXT PRIMARY KEY,
    gkn         TEXT,
    nam         TEXT,
    gfk         INTEGER,
    bezgfk      TEXT,
    building    TEXT,
    namlag      TEXT,
    hnr         TEXT,
    shape_area  NUMERIC,
    aog         INTEGER,
    geometry    GEOMETRY(MultiPolygon, 4326),
    geom_25833  GEOMETRY(MultiPolygon, 25833)
);
CREATE INDEX IF NOT EXISTS idx_alkis_buildings_geom
    ON vector.alkis_buildings USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_alkis_buildings_geom_25833
    ON vector.alkis_buildings USING GIST(geom_25833);
CREATE INDEX IF NOT EXISTS idx_alkis_buildings_building
    ON vector.alkis_buildings(building);
"""

UPSERT_SQL = """
INSERT INTO vector.alkis_buildings
    (uuid, gkn, nam, gfk, bezgfk, building, namlag, hnr, shape_area, aog, geom_25833)
VALUES
    (:uuid, :gkn, :nam, :gfk, :bezgfk, :building, :namlag, :hnr, :shape_area, :aog,
     ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), 25833))
ON CONFLICT (uuid) DO UPDATE SET
    gkn        = EXCLUDED.gkn,
    nam        = EXCLUDED.nam,
    gfk        = EXCLUDED.gfk,
    bezgfk     = EXCLUDED.bezgfk,
    building   = EXCLUDED.building,
    namlag     = EXCLUDED.namlag,
    hnr        = EXCLUDED.hnr,
    shape_area = EXCLUDED.shape_area,
    aog        = EXCLUDED.aog,
    geom_25833 = EXCLUDED.geom_25833;
"""

# WFS returns EPSG:25833 natively — derive 4326 geometry by transform
UPDATE_PROJ_SQL = """
UPDATE vector.alkis_buildings
SET geometry = ST_Transform(geom_25833, 4326)
WHERE geometry IS NULL;
"""


# ── WFS fetching ───────────────────────────────────────────────────────────────
def fetch_page(start_index: int) -> dict:
    """Fetch one GeoJSON page from the WFS (native EPSG:25833 coordinates)."""
    params = {
        "SERVICE":      "WFS",
        "VERSION":      "2.0.0",
        "REQUEST":      "GetFeature",
        "TYPENAMES":    LAYER,          # WFS 2.0 uses TYPENAMES (plural)
        "outputFormat": "application/json",
        "COUNT":        PAGE_SIZE,
        "STARTINDEX":   start_index,
    }
    resp = requests.get(WFS_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def parse_feature(feat: dict) -> Optional[dict]:
    """Extract relevant properties from a GeoJSON feature."""
    import json

    props = feat.get("properties") or {}
    geom  = feat.get("geometry")

    if not geom:
        return None

    uuid = props.get("uuid") or props.get("gml_id") or props.get("id")
    if not uuid:
        return None

    gfk_raw = props.get("gfk")
    try:
        gfk = int(gfk_raw) if gfk_raw is not None else None
    except (ValueError, TypeError):
        gfk = None

    aog_raw = props.get("aog")
    try:
        aog = int(aog_raw) if aog_raw is not None else None
    except (ValueError, TypeError):
        aog = None

    area_raw = props.get("shape_area") or props.get("flaeche")
    try:
        shape_area = float(area_raw) if area_raw is not None else None
    except (ValueError, TypeError):
        shape_area = None

    return {
        "uuid":         str(uuid),
        "gkn":          props.get("gkn"),
        "nam":          props.get("nam"),
        "gfk":          gfk,
        "bezgfk":       props.get("bezgfk"),
        "building":     gfk_to_building(gfk),
        "namlag":       props.get("namlag"),
        "hnr":          props.get("hnr"),
        "shape_area":   shape_area,
        "aog":          aog,
        "geometry_json": json.dumps(geom),
    }


# ── Main import loop ───────────────────────────────────────────────────────────
def run_import():
    import json
    from sqlalchemy import text

    engine = get_engine()

    logger.info("Creating table vector.alkis_buildings (if not exists)…")
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_SQL))
    logger.info("Table ready.")

    total_inserted = 0
    start_ts = time.time()

    for page_num in range(MAX_PAGES):
        start_index = page_num * PAGE_SIZE

        logger.info(f"  Fetching page {page_num + 1} (startIndex={start_index})…")
        try:
            data = fetch_page(start_index)
        except requests.HTTPError as exc:
            logger.error(f"HTTP error on page {page_num + 1}: {exc}")
            break
        except requests.Timeout:
            logger.error(f"Timeout on page {page_num + 1}; stopping.")
            break

        features = data.get("features") or []
        if not features:
            logger.info("No more features — import complete.")
            break

        rows = [r for r in (parse_feature(f) for f in features) if r]

        if rows:
            with engine.begin() as conn:
                conn.execute(text(UPSERT_SQL), rows)
            total_inserted += len(rows)

        logger.info(
            f"    Page {page_num + 1}: {len(features)} fetched, "
            f"{len(rows)} upserted — running total: {total_inserted:,}"
        )

        if len(features) < PAGE_SIZE:
            logger.info("Last page reached — import complete.")
            break

    # Populate projected geometry column
    logger.info("Updating geom_25833 column (ST_Transform to EPSG:25833)…")
    with engine.begin() as conn:
        conn.execute(text(UPDATE_PROJ_SQL))
    logger.info("Projection update done.")

    elapsed = time.time() - start_ts
    logger.info(
        f"\n✅  ALKIS import finished: {total_inserted:,} buildings "
        f"in {elapsed:.0f}s ({elapsed / 60:.1f} min)"
    )

    # Quick verification
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*), COUNT(geom_25833) FROM vector.alkis_buildings")
        ).fetchone()
        logger.info(f"   DB row count: {row[0]:,}  |  with geom_25833: {row[1]:,}")

        dist = conn.execute(
            text(
                "SELECT building, COUNT(*) cnt "
                "FROM vector.alkis_buildings "
                "GROUP BY building ORDER BY cnt DESC"
            )
        ).fetchall()
        logger.info("   Category distribution:")
        for r in dist:
            logger.info(f"     {r[0]:20s} {r[1]:>8,}")


if __name__ == "__main__":
    run_import()
