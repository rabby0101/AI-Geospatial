#!/usr/bin/env python
"""
General-purpose spectral index batch computation script.

Reads a Sentinel-2 SAFE ZIP (or individual band GeoTIFFs), clips to an
optional boundary, computes a spectral index (NDVI/EVI/SAVI/NDWI/NDBI),
and runs zonal statistics against any PostGIS vector layer.

Usage examples
--------------
# NDVI for all Flurstücke in Berlin Mitte
conda run -n geoassist python scripts/compute_spectral_index.py \\
  --safe "data/S2B_MSIL2A_20260425T101559_N0512_R065_T33UUU_20260425T141249.SAFE.zip" \\
  --polygons-sql "SELECT uuid AS id, geom_25833 FROM vector.wfs_alkis_flurstuecke_flurstuecke WHERE ST_Intersects(geom_25833, (SELECT geom_25833 FROM vector.wfs_alkis_bezirke_bezirksgrenzen WHERE namgem='Mitte'))" \\
  --boundary-sql "SELECT geom_25833 FROM vector.wfs_alkis_bezirke_bezirksgrenzen WHERE namgem='Mitte'" \\
  --index ndvi

# NDWI for all planning zones, save to PostGIS
conda run -n geoassist python scripts/compute_spectral_index.py \\
  --safe "data/my_tile.SAFE.zip" \\
  --polygons-sql "SELECT gml_id AS id, geom_25833 FROM vector.lor_planungsraeume_2021" \\
  --index ndwi \\
  --output-table vector.ndwi_results_2026
"""

import argparse
import logging
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as rasterio_mask
from rasterstats import zonal_stats as rasterstats_zonal

# Add project root to path so app.utils imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.satellite_processor import (
    REQUIRED_BANDS,
    extract_metadata_from_safe,
)
from app.utils.database import db_manager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Sentinel-2 L2A band → IMG_DATA member name fragments
_BAND_RES_PREFERENCE = {
    "B02": "R10m", "B03": "R10m", "B04": "R10m", "B08": "R10m",
    "B11": "R20m", "B12": "R20m",
}


# ---------------------------------------------------------------------------
# Band extraction from SAFE ZIP
# ---------------------------------------------------------------------------

def extract_band_from_safe(zip_path: str, band: str, dest_dir: Path) -> Path:
    """
    Extract the best-resolution JP2 for the given band from a SAFE ZIP.
    Returns the path to the extracted file.
    """
    preferred_res = _BAND_RES_PREFERENCE.get(band.upper(), "R10m")

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        candidates = [
            m for m in members
            if "/IMG_DATA/" in m
            and m.lower().endswith((".jp2", ".tif", ".tiff"))
            and f"_{band.upper()}_" in m.upper()
        ]
        if not candidates:
            raise FileNotFoundError(
                f"Band {band} not found in {zip_path}. Available bands: "
                + str(sorted({m.split("_")[-2] for m in members if "/IMG_DATA/" in m}))
            )

        # Prefer the requested resolution; fall back to any match
        preferred = [c for c in candidates if preferred_res in c]
        chosen = (preferred or candidates)[0]

        dest = dest_dir / Path(chosen).name
        if not dest.exists():
            with zf.open(chosen) as src:
                dest.write_bytes(src.read())
        logger.info(f"Extracted {band}: {Path(chosen).name} → {dest}")
        return dest


# ---------------------------------------------------------------------------
# Boundary clipping
# ---------------------------------------------------------------------------

def _load_boundary_geom(boundary_sql: str, target_crs_epsg: int):
    """
    Query boundary_sql, try common geometry column names, reproject to target CRS.
    Returns a list of GeoJSON-like dicts usable by rasterio.mask.
    """
    _GEOM_COLS = [
        ("geom_25833", "EPSG:25833"),
        ("geometry", None),
        ("geom", None),
        ("the_geom", None),
    ]
    for col, override_crs in _GEOM_COLS:
        try:
            gdf = db_manager.execute_spatial_query(boundary_sql, geom_col=col)
            if gdf is None or len(gdf) == 0 or gdf.geometry.isna().all():
                continue
            if override_crs:
                gdf = gdf.set_crs(override_crs, allow_override=True)
            if gdf.crs and gdf.crs.to_epsg() != target_crs_epsg:
                gdf = gdf.to_crs(f"EPSG:{target_crs_epsg}")
            return [g.__geo_interface__ for g in gdf.geometry]
        except Exception:
            continue
    raise ValueError(f"boundary_sql returned no usable geometry.\nSQL: {boundary_sql}")


def clip_band(band_path: Path, boundary_sql: str, raster_epsg: int, out_path: Path) -> Path:
    """Clip a band raster to the boundary geometry; fill outside with -9999."""
    geoms = _load_boundary_geom(boundary_sql, raster_epsg)
    with rasterio.open(band_path) as src:
        clipped, transform = rasterio_mask(src, geoms, crop=True, nodata=-9999)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff", dtype="float32", count=1,
            height=clipped.shape[1], width=clipped.shape[2],
            transform=transform, nodata=-9999, compress="lzw",
        )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(clipped[0].astype("float32"), 1)
    return out_path


# ---------------------------------------------------------------------------
# Spectral index computation (nodata-aware)
# ---------------------------------------------------------------------------

INDEX_FORMULAS = {
    "evi":  lambda b: 2.5 * (b["B08"] - b["B04"]) / (b["B08"] + 6 * b["B04"] - 7.5 * b["B02"] + 1 + 1e-10),
    "savi": lambda b: 1.5 * (b["B08"] - b["B04"]) / (b["B08"] + b["B04"] + 0.5 + 1e-10),
    "ndwi": lambda b: (b["B03"] - b["B08"]) / (b["B03"] + b["B08"] + 1e-10),
    "ndbi": lambda b: (b["B11"] - b["B08"]) / (b["B11"] + b["B08"] + 1e-10),
    "ndvi": lambda b: (b["B08"] - b["B04"]) / (b["B08"] + b["B04"] + 1e-10),
}


def compute_index(band_paths: dict[str, Path], index: str, out_path: Path) -> Path:
    """
    Compute a spectral index from band GeoTIFFs with proper nodata handling.

    band_paths: {"B04": Path, "B08": Path, ...}
    Returns path to output GeoTIFF.
    """
    idx = index.lower()
    arrays = {}
    profile = None
    nodata_mask = None

    for band, path in band_paths.items():
        with rasterio.open(path) as src:
            nd = src.nodata
            arr = src.read(1).astype(float)
            if nd is not None:
                arr[arr == nd] = np.nan
            # Also treat -9999 as nodata (from clip step)
            arr[arr == -9999] = np.nan
            arrays[band] = arr
            if profile is None:
                profile = src.profile.copy()
                profile.update(driver="GTiff", dtype="float32", count=1,
                               compress="lzw", nodata=-9999)

        bad = np.isnan(arr)
        nodata_mask = bad if nodata_mask is None else (nodata_mask | bad)

    with np.errstate(invalid="ignore", divide="ignore"):
        result = INDEX_FORMULAS[idx](arrays)

    result = np.clip(result, -1, 1)
    result[nodata_mask] = np.nan

    out = np.where(np.isnan(result), -9999.0, result).astype(np.float32)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out, 1)

    valid_count = int((out != -9999).sum())
    valid_vals = out[out != -9999]
    logger.info(
        f"{idx.upper()} raster: {valid_count} valid pixels, "
        f"mean={valid_vals.mean():.4f}, range=[{valid_vals.min():.4f}, {valid_vals.max():.4f}]"
    )
    return out_path


# ---------------------------------------------------------------------------
# Polygon loading (tries common geometry column names)
# ---------------------------------------------------------------------------

def load_polygons(polygons_sql: str, geom_col: str | None, geom_epsg: int | None) -> gpd.GeoDataFrame:
    _GEOM_COLS = [
        ("geom_25833", "EPSG:25833"),
        ("geometry", None),
        ("geom", None),
        ("the_geom", None),
        ("shape", None),
    ]
    if geom_col:
        _GEOM_COLS = [(geom_col, f"EPSG:{geom_epsg}" if geom_epsg else None)] + _GEOM_COLS

    last_err = None
    for col, override_crs in _GEOM_COLS:
        try:
            gdf = db_manager.execute_spatial_query(polygons_sql, geom_col=col)
            if gdf is None or len(gdf) == 0 or gdf.geometry.isna().all():
                continue
            if override_crs:
                gdf = gdf.set_crs(override_crs, allow_override=True)
            return gdf
        except Exception as e:
            last_err = e
    raise ValueError(f"Could not load polygons.\nSQL: {polygons_sql}\nLast error: {last_err}")


# ---------------------------------------------------------------------------
# Zonal statistics
# ---------------------------------------------------------------------------

def run_zonal_stats(index_raster: Path, polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Compute mean/min/max/std/count per polygon using rasterstats (single raster open).
    Reprojects polygons to match the raster CRS before running.
    """
    with rasterio.open(index_raster) as src:
        raster_crs = src.crs
        nodata = src.nodata if src.nodata is not None else -9999

    if polygons.crs and raster_crs:
        if polygons.crs.to_epsg() != raster_crs.to_epsg():
            polygons = polygons.to_crs(raster_crs)

    raw = rasterstats_zonal(
        polygons.geometry,
        str(index_raster),
        stats=["mean", "min", "max", "std", "count"],
        nodata=nodata,
        all_touched=False,
    )

    result = polygons.copy()
    result["ndvi_mean"]  = np.array([r.get("mean")  for r in raw], dtype=float)
    result["ndvi_min"]   = np.array([r.get("min")   for r in raw], dtype=float)
    result["ndvi_max"]   = np.array([r.get("max")   for r in raw], dtype=float)
    result["ndvi_std"]   = np.array([r.get("std")   for r in raw], dtype=float)
    result["pixel_count"] = np.array([r.get("count", 0) for r in raw], dtype=int)

    if result.crs and result.crs.to_epsg() != 4326:
        result = result.to_crs("EPSG:4326")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compute a spectral index (NDVI/EVI/SAVI/NDWI/NDBI) and "
                    "run zonal statistics against any PostGIS vector layer."
    )
    parser.add_argument("--safe", help="Path to Sentinel-2 SAFE ZIP")
    parser.add_argument("--raster-b04", help="Path to pre-extracted B04 GeoTIFF (instead of --safe)")
    parser.add_argument("--raster-b08", help="Path to pre-extracted B08 GeoTIFF (instead of --safe)")
    parser.add_argument("--raster-b03", help="Path to pre-extracted B03 GeoTIFF")
    parser.add_argument("--raster-b02", help="Path to pre-extracted B02 GeoTIFF")
    parser.add_argument("--raster-b11", help="Path to pre-extracted B11 GeoTIFF")
    parser.add_argument(
        "--polygons-sql", required=True,
        help='SQL returning (id, geometry) rows for zonal stats zones. '
             'Example: "SELECT uuid AS id, geom_25833 FROM vector.wfs_alkis_flurstuecke_flurstuecke"',
    )
    parser.add_argument(
        "--boundary-sql",
        help="Optional SQL for clip boundary. If omitted, bands are not clipped.",
    )
    parser.add_argument(
        "--index", default="ndvi",
        choices=list(REQUIRED_BANDS.keys()),
        help="Spectral index to compute (default: ndvi)",
    )
    parser.add_argument("--date", help="Target acquisition date YYYY-MM-DD (auto-detected from SAFE filename if omitted)")
    parser.add_argument("--output-table", help="PostGIS table to write results to (schema.tablename)")
    parser.add_argument("--geom-col", help="Geometry column name in polygons SQL (auto-detected if omitted)")
    parser.add_argument("--geom-epsg", type=int, help="EPSG code for the geometry column CRS")
    args = parser.parse_args()

    if not args.safe and not (args.raster_b04 and args.raster_b08):
        parser.error("Provide either --safe or both --raster-b04 and --raster-b08")

    t0 = time.time()
    idx = args.index.lower()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # --- Step 1: Obtain band files ---
        band_paths: dict[str, Path] = {}

        if args.safe:
            logger.info(f"Reading SAFE ZIP: {args.safe}")
            for band in REQUIRED_BANDS[idx]:
                band_paths[band] = extract_band_from_safe(args.safe, band, tmp)
        else:
            raster_map = {
                "B02": args.raster_b02, "B03": args.raster_b03,
                "B04": args.raster_b04, "B08": args.raster_b08, "B11": args.raster_b11,
            }
            for band in REQUIRED_BANDS[idx]:
                path = raster_map.get(band)
                if not path:
                    parser.error(f"{idx.upper()} requires {band}. Provide --raster-{band.lower()}")
                band_paths[band] = Path(path)

        # Detect raster CRS from first band
        with rasterio.open(band_paths[REQUIRED_BANDS[idx][0]]) as src:
            raster_epsg = src.crs.to_epsg()
        logger.info(f"Raster CRS: EPSG:{raster_epsg}")

        # --- Step 2: Clip bands to boundary (optional) ---
        if args.boundary_sql:
            logger.info("Clipping bands to boundary...")
            clipped: dict[str, Path] = {}
            for band, path in band_paths.items():
                out = tmp / f"clipped_{band}.tif"
                clipped[band] = clip_band(path, args.boundary_sql, raster_epsg, out)
            band_paths = clipped

        # --- Step 3: Compute spectral index ---
        index_raster = tmp / f"{idx}_index.tif"
        logger.info(f"Computing {idx.upper()}...")
        compute_index(band_paths, idx, index_raster)

        # --- Step 4: Load polygons ---
        logger.info("Loading polygons from database...")
        db_manager.initialize()
        polygons = load_polygons(args.polygons_sql, args.geom_col, args.geom_epsg)
        logger.info(f"Loaded {len(polygons)} polygons")

        # --- Step 5: Zonal statistics ---
        logger.info(f"Running zonal statistics ({len(polygons)} polygons)...")
        result = run_zonal_stats(index_raster, polygons)
        # Rename ndvi_* columns to {index}_* if not NDVI
        if idx != "ndvi":
            result = result.rename(columns={
                "ndvi_mean": f"{idx}_mean", "ndvi_min": f"{idx}_min",
                "ndvi_max": f"{idx}_max", "ndvi_std": f"{idx}_std",
            })

        # --- Step 6: Print summary ---
        mean_col = f"{idx}_mean"
        non_null = result[mean_col].notna().sum()
        valid = result[mean_col].dropna()
        elapsed = round(time.time() - t0, 1)

        print(f"\n{'='*60}")
        print(f"  {idx.upper()} zonal statistics complete ({elapsed}s)")
        print(f"{'='*60}")
        print(f"  Polygons:    {len(result)}")
        print(f"  Non-null:    {non_null} ({100 * non_null / len(result):.1f}%)")
        if len(valid) > 0:
            print(f"  Mean {idx.upper()}:  {valid.mean():.4f}")
            print(f"  Min  {idx.upper()}:  {valid.min():.4f}")
            print(f"  Max  {idx.upper()}:  {valid.max():.4f}")
        print(f"{'='*60}\n")

        # --- Step 7: Save to PostGIS (optional) ---
        if args.output_table:
            parts = args.output_table.split(".")
            schema, table = (parts[0], parts[1]) if len(parts) == 2 else ("public", parts[0])
            logger.info(f"Writing results to {schema}.{table}...")
            result.to_postgis(table, db_manager.engine, schema=schema, if_exists="replace", index=False)
            logger.info(f"Saved {len(result)} rows to {args.output_table}")

    return result


if __name__ == "__main__":
    main()
