"""
Satellite Image Processor
Handles metadata extraction, spatial tile identification, mosaicking, cropping,
spectral index calculation, and zonal statistics for Sentinel-2 L2A imagery.
Pure computation — no LLM calls, no network requests.
"""

import re
import json
import zipfile
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.merge import merge as rasterio_merge
from rasterio.enums import Resampling
from rasterio.warp import reproject, calculate_default_transform
from rasterio.crs import CRS
from shapely.geometry import box, shape
import geopandas as gpd

from app.utils.raster_operations import RasterOperations
from app.utils.database import db_manager

logger = logging.getLogger(__name__)

raster_ops = RasterOperations()

# Band requirements for each spectral index
REQUIRED_BANDS: Dict[str, List[str]] = {
    "ndvi": ["B04", "B08"],
    "evi":  ["B02", "B04", "B08"],
    "savi": ["B04", "B08"],
    "ndwi": ["B03", "B08"],
    "ndbi": ["B08", "B11"],
}

# Raster calculator expressions (variable names match band keys)
INDEX_FORMULAS: Dict[str, str] = {
    "evi":  "2.5 * (B08 - B04) / (B08 + 6 * B04 - 7.5 * B02 + 1 + 1e-10)",
    "savi": "1.5 * (B08 - B04) / (B08 + B04 + 0.5 + 1e-10)",
    "ndwi": "(B03 - B08) / (B03 + B08 + 1e-10)",
    "ndbi": "(B11 - B08) / (B11 + B08 + 1e-10)",
}

# Sentinel-2 L2A filename pattern (official naming convention)
# Example: T33UUU_20230615T095031_B04_10m.tif
_S2_FILENAME_RE = re.compile(
    r"(?:(?P<tile>T\d{2}[A-Z]{3})_)?"
    r"(?:(?P<datetime>\d{8}T\d{6})_)?"
    r"(?P<band>B\d{2}[AB]?)"
    r"(?:_(?P<res>\d+m))?",
    re.IGNORECASE,
)

# Fallback: bare date YYYYMMDD anywhere in filename
_DATE_RE = re.compile(r"(\d{8})")


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def extract_metadata_from_filename(filename: str) -> Dict:
    """
    Parse a Sentinel-2 L2A band filename into structured metadata.

    Handles the official naming convention:
        T33UUU_20230615T095031_B04_10m.tif

    And simpler variants like:
        B04_20230615.tif  or  berlin_2023_B08.tif

    Returns:
        Dict with keys: tile_id, date (ISO string), band, resolution.
        Any unparseable field is set to None — never raises.
    """
    stem = Path(filename).stem
    result: Dict = {"tile_id": None, "date": None, "band": None, "resolution": None}

    m = _S2_FILENAME_RE.search(stem)
    if m:
        result["tile_id"]   = m.group("tile")
        result["band"]      = m.group("band").upper() if m.group("band") else None
        result["resolution"] = m.group("res")

        raw_dt = m.group("datetime")
        if raw_dt:
            try:
                result["date"] = datetime.strptime(raw_dt, "%Y%m%dT%H%M%S").strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Fallback date: bare YYYYMMDD in filename
    if result["date"] is None:
        dm = _DATE_RE.search(stem)
        if dm:
            try:
                result["date"] = datetime.strptime(dm.group(1), "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

    return result


def extract_metadata_from_safe(zip_path: str) -> List[Dict]:
    """
    Extract per-band metadata from a Sentinel-2 SAFE ZIP archive.

    Reads MTD_MSIL2A.xml for acquisition date and tile ID, then enumerates
    band GeoTIFFs under GRANULE/*/IMG_DATA/.

    Returns:
        List of dicts (one per band file found), each with:
        tile_id, date, band, resolution, zip_member (internal ZIP path).

    Raises:
        FileNotFoundError  if zip_path does not exist.
        KeyError           if MTD_MSIL2A.xml is missing (not a SAFE ZIP).
    """
    results = []
    zp = Path(zip_path)
    if not zp.exists():
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()

        # Locate root metadata XML
        mtd_candidates = [m for m in members if m.endswith("MTD_MSIL2A.xml")]
        if not mtd_candidates:
            raise KeyError("MTD_MSIL2A.xml not found — not a valid SAFE ZIP")

        mtd_member = mtd_candidates[0]
        with zf.open(mtd_member) as f:
            tree = ET.parse(f)
            root = tree.getroot()

        # Strip namespace for simpler XPath
        ns = ""
        raw_tag = root.tag
        if raw_tag.startswith("{"):
            ns = raw_tag.split("}")[0] + "}"

        # Acquisition date
        date_str = None
        for tag in ["PRODUCT_START_TIME", "DATATAKE_SENSING_START"]:
            el = root.find(f".//{ns}{tag}")
            if el is not None and el.text:
                try:
                    date_str = datetime.fromisoformat(el.text[:19]).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass

        # Tile ID — derive from any member path that contains /GRANULE/
        # (don't rely on directory entries ending "/", many ZIPs omit them)
        tile_id = None
        granule_paths = [m for m in members if "/GRANULE/" in m]
        if not granule_paths:
            # Fallback: tile ID from the ZIP filename itself (T33UUU in S2A_MSIL2A_..._T33UUU_...)
            tm = re.search(r"_(T\d{2}[A-Z]{3})_", Path(zip_path).name)
            if tm:
                tile_id = tm.group(1)
        else:
            granule_name = granule_paths[0].split("/GRANULE/")[1].split("/")[0]
            tm = re.search(r"_(T\d{2}[A-Z]{3})_", granule_name)
            if tm:
                tile_id = tm.group(1)
            # Also try the ZIP filename as fallback
            if not tile_id:
                tm = re.search(r"_(T\d{2}[A-Z]{3})_", Path(zip_path).name)
                if tm:
                    tile_id = tm.group(1)

        # Fallback date from ZIP filename if XML parsing failed
        if date_str is None:
            dm = re.search(r"_(\d{8}T\d{6})_", Path(zip_path).name)
            if dm:
                try:
                    date_str = datetime.strptime(dm.group(1), "%Y%m%dT%H%M%S").strftime("%Y-%m-%d")
                except ValueError:
                    pass

        # Enumerate band image files — Sentinel-2 L2A uses JP2 (JPEG 2000)
        # Also support GeoTIFF for pre-converted files
        band_members = [
            m for m in members
            if m.lower().endswith((".jp2", ".tif", ".tiff"))
            and "/IMG_DATA/" in m  # only actual band imagery, skip QI/AUX files
        ]
        for member in band_members:
            band = None
            res  = None
            bm = re.search(r"_(B\d{2}[AB]?)_?(\d+m)?", member, re.IGNORECASE)
            if bm:
                band = bm.group(1).upper()
                res  = bm.group(2)
            results.append({
                "tile_id": tile_id,
                "date": date_str,
                "band": band,
                "resolution": res,
                "zip_member": member,
                "path": None,  # Will be filled after extraction
            })

    return results


def extract_bands_from_safe(zip_path: str, session_dir: str, band_entries: List[Dict]) -> List[Dict]:
    """
    Extract band GeoTIFFs from a SAFE ZIP to session_dir.
    Updates each entry's 'path' key in-place. Returns the updated entries.
    """
    updated = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for entry in band_entries:
            zm = entry.get("zip_member")
            if not zm:
                updated.append(entry)
                continue
            # Build a flat destination filename
            dest_name = Path(zm).name
            dest_path = Path(session_dir) / dest_name
            with zf.open(zm) as src, open(dest_path, "wb") as dst:
                dst.write(src.read())
            entry = {**entry, "path": str(dest_path)}
            updated.append(entry)
    return updated


# ---------------------------------------------------------------------------
# Area geometry helpers — SQL-driven, no hardcoded table names
# ---------------------------------------------------------------------------

def _load_area_geometry(boundary_sql: str) -> gpd.GeoDataFrame:
    """
    Execute boundary_sql and return a GeoDataFrame for the area of interest.

    Tries common geometry column names in priority order.
    Corrects CRS for known UTM columns (geom_25833).
    """
    _GEOM_COLS = [
        ("geometry", None),
        ("geom", None),
        ("geom_25833", "EPSG:25833"),
        ("the_geom", None),
        ("shape", None),
    ]
    last_err: Optional[Exception] = None
    for col, override_crs in _GEOM_COLS:
        try:
            gdf = db_manager.execute_spatial_query(boundary_sql, geom_col=col)
            if gdf is None or len(gdf) == 0 or gdf.geometry.isna().all():
                continue
            if override_crs:
                gdf = gdf.set_crs(override_crs, allow_override=True)
            elif gdf.crs and gdf.crs.to_epsg() == 4326:
                # execute_spatial_query always assigns EPSG:4326; if coordinates are
                # outside valid lat/lon range the geometry is actually in a projected
                # CRS (e.g. EPSG:25833 from ST_Transform). Correct automatically.
                b = gdf.total_bounds  # (minx, miny, maxx, maxy)
                if b[0] > 180 or b[1] > 90 or b[2] > 180 or b[3] > 90:
                    gdf = gdf.set_crs("EPSG:25833", allow_override=True)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs("EPSG:4326")
            return gdf
        except Exception as e:
            last_err = e
    raise ValueError(
        f"boundary_sql failed: Could not find usable geometry column.\n"
        f"SQL: {boundary_sql}\nLast error: {last_err}"
    )


# ---------------------------------------------------------------------------
# Tile coverage identification
# ---------------------------------------------------------------------------

def identify_covering_tiles(
    session_files: List[Dict],
    boundary_sql: str,
    target_date: Optional[str] = None,
    date_tolerance_days: int = 30,
) -> Tuple[List[Dict], Optional[float]]:
    """
    Return the subset of session_files whose raster bounds spatially intersect
    the area returned by boundary_sql, optionally filtered by date.
    Also computes what percentage of the area is covered by the matched tiles.

    Args:
        session_files:       List of file metadata dicts from the session store.
        boundary_sql:        SQL returning a single 'geometry' column (EPSG:4326).
        target_date:         ISO date string; if None, no date filter.
        date_tolerance_days: Files within ±this many days of target_date match.

    Returns:
        Tuple of (matching_files, coverage_pct).

    Raises:
        ValueError if boundary_sql returns no geometry.
        ValueError if no tiles intersect the area (after date filter).
    """
    area_gdf = _load_area_geometry(boundary_sql)
    area_geom = area_gdf.union_all() if hasattr(area_gdf, "union_all") else area_gdf.unary_union

    # Reproject area to EPSG:4326 for comparison
    if area_gdf.crs and area_gdf.crs.to_epsg() != 4326:
        area_gdf_4326 = area_gdf.to_crs(4326)
        area_geom_4326 = area_gdf_4326.union_all() if hasattr(area_gdf_4326, "union_all") else area_gdf_4326.unary_union
    else:
        area_geom_4326 = area_geom

    target_dt = None
    if target_date:
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"Could not parse target_date '{target_date}', ignoring date filter")

    matching = []
    for entry in session_files:
        file_path = entry.get("path")
        if not file_path or not Path(file_path).exists():
            continue

        # Date filter
        if target_dt and entry.get("date"):
            try:
                file_dt = datetime.strptime(entry["date"], "%Y-%m-%d")
                if abs((file_dt - target_dt).days) > date_tolerance_days:
                    continue
            except ValueError:
                pass

        # Spatial check: use cached bounds if available, else read from rasterio
        bounds = entry.get("bounds")
        try:
            if bounds is None:
                with rasterio.open(file_path) as src:
                    b = src.bounds
                    file_crs = src.crs
                    bounds = [b.left, b.bottom, b.right, b.top]
            else:
                # Need CRS to build shapely box correctly; read it
                with rasterio.open(file_path) as src:
                    file_crs = src.crs

            tile_box = box(*bounds)

            # Reproject tile box to EPSG:4326 if needed
            if file_crs and CRS.from_epsg(4326) != file_crs:
                tile_gdf = gpd.GeoDataFrame(geometry=[tile_box], crs=file_crs)
                tile_gdf = tile_gdf.to_crs(4326)
                tile_box = tile_gdf.geometry.iloc[0]

            if tile_box.intersects(area_geom_4326):
                matching.append(entry)

        except Exception as e:
            logger.warning(f"Could not check bounds for {file_path}: {e}")

    if not matching:
        date_msg = f" for date {target_date}" if target_date else ""
        raise ValueError(
            f"No uploaded tiles intersect the requested area{date_msg}. "
            "Check that your uploaded files cover this area."
        )

    # Compute coverage: what fraction of the district is covered by the union of matched tiles.
    # Each tile's bounds box is used (deduplicated by path to avoid re-opening the same file).
    coverage_pct: Optional[float] = None
    try:
        tile_union = None
        seen_paths = set()
        for entry in matching:
            fp = entry.get("path")
            bounds = entry.get("bounds")
            if not bounds or not fp or fp in seen_paths:
                continue
            seen_paths.add(fp)
            with rasterio.open(fp) as src:
                file_crs = src.crs
            t_box = box(*bounds)
            if file_crs and CRS.from_epsg(4326) != file_crs:
                t_gdf = gpd.GeoDataFrame(geometry=[t_box], crs=file_crs)
                t_box = t_gdf.to_crs(4326).geometry.iloc[0]
            tile_union = t_box if tile_union is None else tile_union.union(t_box)

        if tile_union is not None and area_geom_4326.area > 0:
            covered = tile_union.intersection(area_geom_4326)
            coverage_pct = round(covered.area / area_geom_4326.area * 100, 1)

        if coverage_pct is not None and coverage_pct < 99.0:
            logger.warning(
                f"Incomplete coverage: {coverage_pct:.1f}% of the area is covered "
                "by the uploaded tiles. Results may be incomplete."
            )
        else:
            logger.info(f"Coverage: {coverage_pct}%")
    except Exception as e:
        logger.warning(f"Coverage calculation failed: {e}")

    return matching, coverage_pct


# ---------------------------------------------------------------------------
# Mosaic
# ---------------------------------------------------------------------------

def mosaic_tiles(tile_paths: List[str], output_path: str) -> str:
    """
    Merge multiple single-band GeoTIFFs into one mosaic using rasterio.merge.
    All inputs are reprojected to the CRS of the first tile before merging.

    Args:
        tile_paths:  List of absolute paths to input GeoTIFFs (must be same band).
        output_path: Absolute path for the output mosaic GeoTIFF.

    Returns:
        output_path

    Raises:
        ValueError if tile_paths is empty.
    """
    if not tile_paths:
        raise ValueError("mosaic_tiles: tile_paths must not be empty")

    if len(tile_paths) == 1:
        # Re-encode as float32 GeoTIFF; do not raw-copy JP2 bytes into a .tif filename
        with rasterio.open(tile_paths[0]) as src:
            profile = src.profile.copy()
            profile.update(driver="GTiff", dtype="float32", compress="lzw", count=1)
            data = src.read(1).astype("float32")
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(data, 1)
        return output_path

    datasets = [rasterio.open(p) for p in tile_paths]
    try:
        ref_crs = datasets[0].crs

        # Reproject all datasets to reference CRS before merge
        merged_array, merged_transform = rasterio_merge(
            datasets,
            resampling=Resampling.nearest
        )

        profile = datasets[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=merged_array.shape[1],
            width=merged_array.shape[2],
            transform=merged_transform,
            dtype="float32",
            compress="lzw",
            count=1,
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(merged_array[0].astype("float32"), 1)

    finally:
        for ds in datasets:
            ds.close()

    logger.info(f"Mosaicked {len(tile_paths)} tiles → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------

def crop_to_area(raster_path: str, boundary_sql: str, output_path: str) -> str:
    """
    Clip a raster to the geometry returned by boundary_sql.

    Args:
        raster_path:   Input GeoTIFF path.
        boundary_sql:  SQL returning a single 'geometry' column (EPSG:4326).
        output_path:   Output GeoTIFF path.

    Returns:
        output_path
    """
    area_gdf = _load_area_geometry(boundary_sql)
    raster_ops.clip_raster_by_vector(raster_path, area_gdf, output_path)
    logger.info(f"Cropped {raster_path} → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Spectral index calculation
# ---------------------------------------------------------------------------

def _align_bands(band_paths_dict: Dict[str, str], tmp_dir: str) -> Dict[str, str]:
    """
    Ensure all bands share the same grid (resolution + CRS + extent).
    Reprojects lower-resolution bands to match the highest-resolution band.
    Returns a new dict with paths to aligned (possibly resampled) files.
    """
    # Determine the reference band (finest resolution = smallest pixel size)
    ref_band = None
    ref_pixel_size = float("inf")

    for band, path in band_paths_dict.items():
        with rasterio.open(path) as src:
            ps = abs(src.transform.a)  # pixel width
            if ps < ref_pixel_size:
                ref_pixel_size = ps
                ref_band = band

    aligned = {}
    with rasterio.open(band_paths_dict[ref_band]) as ref_src:
        ref_crs       = ref_src.crs
        ref_transform = ref_src.transform
        ref_height    = ref_src.height
        ref_width     = ref_src.width

    for band, path in band_paths_dict.items():
        with rasterio.open(path) as src:
            same_grid = (
                src.crs == ref_crs
                and src.height == ref_height
                and src.width == ref_width
                and src.transform == ref_transform
            )
            if same_grid:
                aligned[band] = path
                continue

        # Resample to reference grid
        aligned_path = str(Path(tmp_dir) / f"aligned_{band}.tif")
        with rasterio.open(path) as src:
            out_array = np.empty((ref_height, ref_width), dtype="float32")
            reproject(
                source=rasterio.band(src, 1),
                destination=out_array,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear,
            )
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                crs=ref_crs,
                transform=ref_transform,
                height=ref_height,
                width=ref_width,
                dtype="float32",
                compress="lzw",
                count=1,
            )
            with rasterio.open(aligned_path, "w", **profile) as dst:
                dst.write(out_array, 1)

        aligned[band] = aligned_path
        logger.info(f"Aligned {band} to reference grid → {aligned_path}")

    return aligned


def calculate_index(
    band_paths_dict: Dict[str, str],
    index_type: str,
    output_path: str,
) -> str:
    """
    Compute a spectral index from a dict mapping band names to file paths.

    Supported indices: ndvi, evi, savi, ndwi, ndbi.

    Args:
        band_paths_dict: {"B04": "/path/B04.tif", "B08": "/path/B08.tif", ...}
        index_type:      One of: ndvi, evi, savi, ndwi, ndbi.
        output_path:     Output GeoTIFF path.

    Returns:
        output_path

    Raises:
        ValueError for unsupported index or missing required bands.
    """
    idx = index_type.lower()
    if idx not in REQUIRED_BANDS:
        raise ValueError(
            f"Unsupported index '{index_type}'. Supported: {list(REQUIRED_BANDS.keys())}"
        )

    missing = [b for b in REQUIRED_BANDS[idx] if b not in band_paths_dict]
    if missing:
        available = list(band_paths_dict.keys())
        raise ValueError(
            f"{index_type.upper()} requires bands {REQUIRED_BANDS[idx]}. "
            f"Missing: {missing}. Available: {available}. "
            "Please upload the missing band files."
        )

    # Align all bands to the same grid (handles mixed resolutions)
    tmp_dir = str(Path(output_path).parent)
    relevant_bands = {b: band_paths_dict[b] for b in REQUIRED_BANDS[idx]}
    aligned = _align_bands(relevant_bands, tmp_dir)

    if idx == "ndvi":
        raster_ops.compute_ndvi(aligned["B04"], aligned["B08"], output_path)
    else:
        formula = INDEX_FORMULAS[idx]
        raster_ops.raster_calculator(formula, aligned, output_path)

    logger.info(f"Calculated {idx.upper()} → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Zonal statistics
# ---------------------------------------------------------------------------

def _load_polygons_for_area(polygons_sql: str) -> gpd.GeoDataFrame:
    """
    Execute polygons_sql and return a GeoDataFrame of zone polygons for
    zonal statistics.

    Tries common geometry column names in priority order.
    Corrects CRS for known UTM columns (geom_25833).
    """
    _GEOM_COLS = [
        ("geometry", None),
        ("geom", None),
        ("geom_25833", "EPSG:25833"),
        ("the_geom", None),
        ("shape", None),
    ]
    last_err: Optional[Exception] = None
    for col, override_crs in _GEOM_COLS:
        try:
            gdf = db_manager.execute_spatial_query(polygons_sql, geom_col=col)
            if gdf is None or len(gdf) == 0 or gdf.geometry.isna().all():
                continue
            if override_crs:
                gdf = gdf.set_crs(override_crs, allow_override=True)
            elif gdf.crs and gdf.crs.to_epsg() == 4326:
                # Same defensive check as _load_area_geometry: execute_spatial_query
                # always assigns EPSG:4326, but geometry may actually be projected.
                b = gdf.total_bounds
                if b[0] > 180 or b[1] > 90 or b[2] > 180 or b[3] > 90:
                    gdf = gdf.set_crs("EPSG:25833", allow_override=True)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs("EPSG:4326")
            return gdf
        except Exception as e:
            last_err = e
    raise ValueError(
        f"polygons_sql failed: Could not find usable geometry column.\n"
        f"SQL: {polygons_sql}\nLast error: {last_err}"
    )


def compute_change_zonal_stats(
    raster_t1: str,
    raster_t2: str,
    polygons_sql: str,
    index_type: str = "ndvi",
) -> gpd.GeoDataFrame:
    """
    Compute per-polygon zonal statistics for index change between two dates.

    Args:
        raster_t1:    Path to index raster at time 1 (earlier date).
        raster_t2:    Path to index raster at time 2 (later date).
        polygons_sql: SQL returning rows with 'name' + 'geometry' (EPSG:4326).
        index_type:   Index name used for column naming (e.g. 'ndvi').

    Returns:
        GeoDataFrame (EPSG:4326) with columns:
            name, geometry,
            {index}_mean_t1, {index}_mean_t2, {index}_change,
            {index}_min, {index}_max, {index}_std, pixel_count
    """
    idx = index_type.lower()
    polygons = _load_polygons_for_area(polygons_sql)

    stats_t1 = raster_ops.zonal_stats(raster_t1, polygons, stats=["mean", "min", "max", "std", "count"])
    stats_t2 = raster_ops.zonal_stats(raster_t2, polygons, stats=["mean", "min", "max", "std", "count"])

    result = polygons.copy()
    result[f"{idx}_mean_t1"] = np.round(stats_t1["mean"].astype(float), 4)
    result[f"{idx}_mean_t2"] = np.round(stats_t2["mean"].astype(float), 4)
    result[f"{idx}_change"]  = np.round(
        stats_t2["mean"].astype(float) - stats_t1["mean"].astype(float), 4
    )
    result[f"{idx}_min"]     = np.round(stats_t2["min"].astype(float), 4)
    result[f"{idx}_max"]     = np.round(stats_t2["max"].astype(float), 4)
    result[f"{idx}_std"]     = np.round(stats_t2["std"].astype(float), 4)
    result["pixel_count"]    = stats_t2["count"].astype(int)

    if result.crs and result.crs.to_epsg() != 4326:
        result = result.to_crs(4326)

    logger.info(f"Computed {idx.upper()} change zonal stats for {len(result)} polygons")
    return result


def compute_single_date_zonal_stats(
    raster_path: str,
    polygons_sql: str,
    index_type: str = "ndvi",
) -> gpd.GeoDataFrame:
    """
    Compute per-polygon zonal statistics for a single-date index raster.

    Args:
        raster_path:  Path to index raster.
        polygons_sql: SQL returning rows with 'name' + 'geometry' (EPSG:4326).
        index_type:   Index name used for column naming.

    Returns:
        GeoDataFrame (EPSG:4326) with columns:
            name, geometry,
            {index}_mean, {index}_min, {index}_max, {index}_std, pixel_count
    """
    idx = index_type.lower()
    polygons = _load_polygons_for_area(polygons_sql)

    stats = raster_ops.zonal_stats(raster_path, polygons, stats=["mean", "min", "max", "std", "count"])

    result = polygons.copy()
    result[f"{idx}_mean"]  = np.round(stats["mean"].astype(float), 4)
    result[f"{idx}_min"]   = np.round(stats["min"].astype(float), 4)
    result[f"{idx}_max"]   = np.round(stats["max"].astype(float), 4)
    result[f"{idx}_std"]   = np.round(stats["std"].astype(float), 4)
    result["pixel_count"]  = stats["count"].astype(int)

    if result.crs and result.crs.to_epsg() != 4326:
        result = result.to_crs(4326)

    return result
