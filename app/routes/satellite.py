"""
Satellite Image Analysis Router
POST /api/satellite/upload   — Upload Sentinel-2 band GeoTIFFs or SAFE ZIPs
POST /api/satellite/analyze  — Run LLM-orchestrated analysis pipeline
DELETE /api/satellite/session/{session_id} — Clean up session files
"""

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List

import rasterio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.models.query_model import SatelliteAnalyzeRequest, SatelliteUploadResponse
from app.utils.raster_operations import RasterOperations
from app.utils.satellite_llm import parse_satellite_intent
from app.utils.satellite_processor import (
    calculate_index,
    compute_change_zonal_stats,
    compute_single_date_zonal_stats,
    crop_to_area,
    extract_bands_from_safe,
    extract_metadata_from_filename,
    extract_metadata_from_safe,
    identify_covering_tiles,
    mosaic_tiles,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/satellite", tags=["satellite"])
raster_ops = RasterOperations()

ALLOWED_EXTENSIONS = {".tif", ".tiff", ".zip"}


# ---------------------------------------------------------------------------
# Session helpers (file-based — multi-worker safe)
# ---------------------------------------------------------------------------

def _session_dir(session_id: str) -> Path:
    safe = session_id.replace("-", "_").replace(" ", "_")[:60]
    return Path(f"/tmp/satellite_{safe}")


def _session_metadata_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session_metadata.json"


def _load_session(session_id: str) -> List[Dict]:
    p = _session_metadata_path(session_id)
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def _save_session(session_id: str, entries: List[Dict]) -> None:
    p = _session_metadata_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(entries, f, indent=2)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _group_by_band(files: List[Dict]) -> Dict[str, List[Dict]]:
    """Group file entries by their band key. Skips entries with band=None."""
    grouped: Dict[str, List[Dict]] = {}
    for entry in files:
        band = entry.get("band")
        if not band:
            continue
        grouped.setdefault(band, []).append(entry)
    return grouped


def _validate_bands_for_index(band_files: Dict[str, List[Dict]], index_type: str) -> None:
    """
    Verify all required bands for the requested index are present.
    Raises HTTPException 422 with a clear message listing missing bands.
    """
    from app.utils.satellite_processor import REQUIRED_BANDS

    required = REQUIRED_BANDS.get(index_type.lower(), [])
    missing = [b for b in required if b not in band_files]
    if missing:
        available = sorted(band_files.keys())
        raise HTTPException(
            status_code=422,
            detail=(
                f"{index_type.upper()} requires bands {required}. "
                f"Missing: {missing}. "
                f"Available in session: {available}. "
                "Please upload the missing band file(s) and try again."
            ),
        )


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=SatelliteUploadResponse)
async def upload_satellite_files(
    files: List[UploadFile] = File(...),
    session_id: str = Form(...),
    format_hint: str = Form("auto"),  # "individual_bands" | "safe_zip" | "auto"
):
    """
    Accept one or more Sentinel-2 band GeoTIFFs (.tif) or SAFE ZIPs (.zip).
    Saves files to /tmp/satellite_{session_id}/, extracts metadata, and
    appends to the session store (incremental — multiple uploads are cumulative).

    Returns a summary of dates, bands, and tile IDs found.
    """
    session_dir = _session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    existing_entries = _load_session(session_id)
    new_entries: List[Dict] = []
    errors: List[str] = []

    for upload in files:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            errors.append(f"Skipped '{upload.filename}': unsupported extension (use .tif or .zip)")
            continue

        dest = session_dir / upload.filename
        content = await upload.read()
        dest.write_bytes(content)

        is_zip = suffix == ".zip"
        is_safe_hint = format_hint in ("safe_zip", "auto")

        if is_zip and is_safe_hint:
            try:
                band_entries = extract_metadata_from_safe(str(dest))
                extracted = extract_bands_from_safe(str(dest), str(session_dir), band_entries)
                for entry in extracted:
                    # Enrich with rasterio bounds + CRS if path is set
                    if entry.get("path") and Path(entry["path"]).exists():
                        try:
                            with rasterio.open(entry["path"]) as src:
                                b = src.bounds
                                entry["bounds"] = [b.left, b.bottom, b.right, b.top]
                                entry["crs"] = str(src.crs)
                        except Exception:
                            pass
                new_entries.extend(extracted)
                logger.info(f"Extracted {len(extracted)} bands from SAFE ZIP {upload.filename}")
            except KeyError:
                errors.append(
                    f"'{upload.filename}' is not a valid Sentinel-2 SAFE ZIP "
                    "(MTD_MSIL2A.xml not found). Try using 'Individual band GeoTIFFs' format."
                )
            except Exception as e:
                errors.append(f"Error reading SAFE ZIP '{upload.filename}': {e}")

        elif not is_zip:
            try:
                meta = extract_metadata_from_filename(upload.filename)
                meta["path"] = str(dest)
                with rasterio.open(str(dest)) as src:
                    b = src.bounds
                    meta["bounds"] = [b.left, b.bottom, b.right, b.top]
                    meta["crs"] = str(src.crs)
                new_entries.append(meta)
                logger.info(f"Registered band file: {upload.filename} → {meta}")
            except Exception as e:
                errors.append(f"Error reading '{upload.filename}': {e}")
        else:
            errors.append(
                f"'{upload.filename}' is a ZIP but format_hint='{format_hint}'. "
                "If this is a SAFE archive, select 'SAFE ZIP' in the upload dialog."
            )

    # Merge with existing session (deduplicate by path)
    existing_paths = {e.get("path") for e in existing_entries}
    merged = existing_entries + [e for e in new_entries if e.get("path") not in existing_paths]
    _save_session(session_id, merged)

    # Build summary
    dates    = sorted({e["date"] for e in merged if e.get("date")})
    bands    = sorted({e["band"] for e in merged if e.get("band")})
    tile_ids = sorted({e["tile_id"] for e in merged if e.get("tile_id")})

    return SatelliteUploadResponse(
        success=True,
        session_id=session_id,
        file_count=len(new_entries),
        total_files=len(merged),
        dates_found=dates,
        bands_found=bands,
        tile_ids=tile_ids,
        errors=errors,
        message=(
            f"Loaded {len(new_entries)} file(s). "
            f"Session total: {len(merged)} files, {len(dates)} date(s), bands: {', '.join(bands)}."
        ),
    )


# ---------------------------------------------------------------------------
# Analyze endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_satellite(request: SatelliteAnalyzeRequest):
    """
    Full satellite analysis pipeline:
    NL question → LLM intent → tile identification → mosaic → crop →
    spectral index → change detection → zonal statistics → GeoJSON choropleth.

    Returns a QueryResponse-compatible JSON dict that the frontend can
    pass directly to addLayer().
    """
    start_time = time.time()

    session_files = _load_session(request.session_id)
    if not session_files:
        raise HTTPException(
            status_code=404,
            detail=(
                "No satellite files found for this session. "
                "Please upload your satellite band files first."
            ),
        )

    # Work directory for intermediate rasters
    work_dir = _session_dir(request.session_id) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ------------------------------------------------------------------
        # Step 1: Parse intent
        # ------------------------------------------------------------------
        intent = parse_satellite_intent(
            request.question,
            session_files,
            request.llm_provider,
        )
        logger.info(f"Satellite intent: {intent}")

        index_type    = intent["index"]
        boundary_sql  = intent["boundary_sql"]
        polygons_sql  = intent["polygons_sql"]
        label         = intent.get("label", "area")
        dates         = intent["dates"][:2]
        analysis_type = intent.get("analysis_type", "single_date")

        if not dates:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not determine which dates to analyse. "
                    "Please specify the year(s) in your question "
                    "(e.g. 'compare 2023 and 2025')."
                ),
            )

        # ------------------------------------------------------------------
        # Step 2: Per-date → mosaic → crop → index
        # ------------------------------------------------------------------
        index_rasters: Dict[str, str] = {}
        coverage_by_date: Dict[str, float] = {}

        for date_str in dates:
            safe_date = date_str.replace("-", "")

            # Identify tiles covering the area for this date (also returns coverage %)
            covering, coverage_pct = identify_covering_tiles(session_files, boundary_sql, date_str)
            if coverage_pct is not None:
                coverage_by_date[date_str] = coverage_pct

            # Group by band
            band_files = _group_by_band(covering)

            # Validate required bands
            _validate_bands_for_index(band_files, index_type)

            # Mosaic + crop per band
            cropped_bands: Dict[str, str] = {}
            from app.utils.satellite_processor import REQUIRED_BANDS
            for band in REQUIRED_BANDS[index_type.lower()]:
                tile_paths = [e["path"] for e in band_files[band] if e.get("path")]

                mosaic_path = str(work_dir / f"mosaic_{band}_{safe_date}.tif")
                mosaic_tiles(tile_paths, mosaic_path)

                crop_path = str(work_dir / f"crop_{band}_{safe_date}.tif")
                crop_to_area(mosaic_path, boundary_sql, crop_path)

                cropped_bands[band] = crop_path

            # Calculate spectral index
            index_path = str(work_dir / f"{index_type}_{safe_date}.tif")
            calculate_index(cropped_bands, index_type, index_path)
            index_rasters[date_str] = index_path

        # ------------------------------------------------------------------
        # Step 3: Generate result GeoDataFrame
        # ------------------------------------------------------------------
        if analysis_type == "change_detection" and len(dates) == 2:
            result_gdf = compute_change_zonal_stats(
                raster_t1=index_rasters[dates[0]],
                raster_t2=index_rasters[dates[1]],
                polygons_sql=polygons_sql,
                index_type=index_type,
            )
            choropleth_property = f"{index_type}_change"
            layer_name = (
                f"{index_type}_change_{label.replace(' ', '_')}"
                f"_{dates[0][:4]}_{dates[1][:4]}"
            )
        else:
            result_gdf = compute_single_date_zonal_stats(
                raster_path=index_rasters[dates[0]],
                polygons_sql=polygons_sql,
                index_type=index_type,
            )
            choropleth_property = f"{index_type}_mean"
            layer_name = (
                f"{index_type}_{label.replace(' ', '_')}_{dates[0][:4]}"
            )

        # ------------------------------------------------------------------
        # Step 4: Serialise to GeoJSON (EPSG:4326)
        # ------------------------------------------------------------------
        if result_gdf.crs and result_gdf.crs.to_epsg() != 4326:
            result_gdf = result_gdf.to_crs(4326)

        geojson_dict = json.loads(result_gdf.to_json())

        # Compute value range for choropleth legend
        values = [
            f["properties"].get(choropleth_property)
            for f in geojson_dict["features"]
            if f["properties"].get(choropleth_property) is not None
        ]
        val_min = float(min(values)) if values else -1.0
        val_max = float(max(values)) if values else 1.0

        feature_count = len(geojson_dict["features"])
        execution_time = round(time.time() - start_time, 2)

        reasoning = (
            f"{index_type.upper()} {'change detection' if analysis_type == 'change_detection' else 'analysis'} "
            f"for {label} "
            + (f"between {dates[0]} and {dates[1]}" if len(dates) == 2 else f"on {dates[0]}")
            + f". {feature_count} polygon(s)."
        )

        return {
            "success": True,
            "query": request.question,
            "result_type": "geojson",
            "data": geojson_dict,
            "layer_name": layer_name,
            "metadata": {
                "index": index_type,
                "label": label,
                "dates": dates,
                "analysis_type": analysis_type,
                "choropleth_property": choropleth_property,
                "choropleth_min": val_min,
                "choropleth_max": val_max,
                "feature_count": feature_count,
                "is_satellite_result": True,
                "coverage_pct": min(coverage_by_date.values()) if coverage_by_date else None,
                "coverage_warning": (
                    f"Only {min(coverage_by_date.values()):.1f}% of {label} is covered "
                    "by the uploaded tiles. Results may be incomplete."
                    if coverage_by_date and min(coverage_by_date.values()) < 99.0
                    else None
                ),
            },
            "reasoning": reasoning,
            "datasets_used": [
                "sentinel-2-l2a",
            ],
            "execution_time": execution_time,
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Satellite analyze pipeline error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline error: {str(e)}. Check server logs for details.",
        )


# ---------------------------------------------------------------------------
# Session cleanup
# ---------------------------------------------------------------------------

@router.delete("/session/{session_id}")
async def clear_satellite_session(session_id: str):
    """
    Delete all uploaded files and session metadata for the given session.
    Called from the frontend when the user clears the satellite badge.
    """
    session_dir = _session_dir(session_id)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.info(f"Cleared satellite session: {session_id}")
        return {"success": True, "message": f"Session {session_id} cleared."}
    return {"success": True, "message": "Session not found (already cleared)."}
