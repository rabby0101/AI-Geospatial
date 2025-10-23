"""
Raster Operations API Endpoints
Handles NDVI analysis, terrain processing, land cover classification
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

from app.utils.spatial_engine import SpatialEngine
from app.utils.raster_operations import RasterOperations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/raster", tags=["raster"])

# Initialize engines
spatial_engine = SpatialEngine(data_dir="./data")
raster_ops = RasterOperations()


# ==================== Request Models ====================

class NDVIChangeRequest(BaseModel):
    """Request model for NDVI change detection"""
    ndvi_t1: str = Field(..., description="Path to earlier NDVI raster (relative to data/)")
    ndvi_t2: str = Field(..., description="Path to later NDVI raster (relative to data/)")
    threshold: float = Field(-0.2, description="Loss threshold (negative for loss)")
    mask_vector: Optional[str] = Field(None, description="Optional vector mask (e.g., residential areas)")

    class Config:
        json_schema_extra = {
            "example": {
                "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_2018.tif",
                "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
                "threshold": -0.2,
                "mask_vector": "vector/osm/berlin_residential.geojson"
            }
        }


class ZonalStatsRequest(BaseModel):
    """Request model for zonal statistics"""
    raster: str = Field(..., description="Path to raster file")
    vector: str = Field(..., description="Path to vector polygons")
    stats: List[str] = Field(['mean', 'min', 'max'], description="Statistics to compute")
    categorical: bool = Field(False, description="Compute categorical stats (for land cover)")

    class Config:
        json_schema_extra = {
            "example": {
                "raster": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
                "vector": "vector/osm/berlin_parks.geojson",
                "stats": ["mean", "min", "max", "std"]
            }
        }


class ClipRasterRequest(BaseModel):
    """Request model for clipping raster by vector"""
    raster: str = Field(..., description="Path to input raster")
    vector: str = Field(..., description="Path to vector polygon for clipping")
    output: Optional[str] = Field(None, description="Output path for clipped raster")


class VectorizeRasterRequest(BaseModel):
    """Request model for raster to vector conversion"""
    raster: str = Field(..., description="Path to input raster")
    threshold: Optional[float] = Field(None, description="Threshold value")
    operator: str = Field('greater', description="Threshold operator: greater, less, equal")


# ==================== NDVI Endpoints ====================

@router.post("/ndvi/change-detection")
async def ndvi_change_detection(request: NDVIChangeRequest) -> Dict[str, Any]:
    """
    Detect vegetation change between two time periods using NDVI

    This endpoint:
    1. Computes NDVI difference between two rasters
    2. Detects areas with significant vegetation loss
    3. Optionally filters results by a mask vector (e.g., residential areas)

    Returns:
        GeoJSON FeatureCollection of vegetation loss areas

    Example usage:
    ```python
    import requests

    response = requests.post(
        "http://localhost:8000/raster/ndvi/change-detection",
        json={
            "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_2018.tif",
            "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
            "threshold": -0.2,
            "mask_vector": "vector/osm/berlin_residential.geojson"
        }
    )
    result = response.json()
    ```
    """
    try:
        logger.info(f"NDVI change detection request: {request.ndvi_t1} → {request.ndvi_t2}")

        # Build operation
        operation = {
            'type': 'vegetation_loss',
            'params': {
                'ndvi_t1': request.ndvi_t1,
                'ndvi_t2': request.ndvi_t2,
                'threshold': request.threshold,
            }
        }

        # Add mask if provided
        if request.mask_vector:
            operation['params']['mask_vector'] = request.mask_vector

        # Execute
        result = spatial_engine.execute_raster_operation(operation)

        if result.get('success'):
            logger.info(f"Found {result['metadata']['count']} vegetation loss areas")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Operation failed'))

    except Exception as e:
        logger.error(f"Error in NDVI change detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ndvi/zonal-stats")
async def ndvi_zonal_statistics(request: ZonalStatsRequest) -> Dict[str, Any]:
    """
    Compute NDVI statistics per polygon (zonal statistics)

    Aggregates raster values (e.g., NDVI) within each vector polygon.
    Useful for analyzing vegetation health per district, park, or agricultural field.

    Returns:
        GeoJSON with polygons enriched with zonal statistics

    Example:
    ```python
    # Get mean NDVI for each park in Berlin
    response = requests.post(
        "http://localhost:8000/raster/ndvi/zonal-stats",
        json={
            "raster": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
            "vector": "vector/osm/berlin_parks.geojson",
            "stats": ["mean", "min", "max"]
        }
    )
    ```
    """
    try:
        logger.info(f"Zonal stats request: {request.raster} x {request.vector}")

        operation = {
            'type': 'zonal_stats',
            'params': {
                'raster': request.raster,
                'vector': request.vector,
                'stats': request.stats
            }
        }

        result = spatial_engine.execute_raster_operation(operation)

        if result.get('success'):
            logger.info(f"Computed zonal stats for {result['metadata']['count']} polygons")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error'))

    except Exception as e:
        logger.error(f"Error in zonal stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ndvi/timeseries/{region}")
async def ndvi_timeseries(
    region: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    location: Optional[str] = Query(None, description="GeoJSON point or polygon")
) -> Dict[str, Any]:
    """
    Get NDVI time series for a location

    Note: This is a placeholder endpoint. Full implementation requires:
    - Historical NDVI data download
    - Time series extraction
    - Temporal aggregation

    Returns:
        Time series data with dates and NDVI values
    """
    # Placeholder implementation
    return {
        "success": False,
        "message": "NDVI time series not yet implemented",
        "todo": [
            "Download historical Sentinel-2 data",
            "Extract NDVI values at location",
            "Aggregate temporal statistics"
        ]
    }


# ==================== General Raster Operations ====================

@router.post("/clip")
async def clip_raster(request: ClipRasterRequest) -> Dict[str, Any]:
    """
    Clip raster by vector polygon

    Useful for:
    - Extracting raster data for a specific region
    - Creating analysis-ready subsets
    - Reducing file size

    Returns:
        Path to clipped raster file
    """
    try:
        operation = {
            'type': 'clip_raster',
            'params': {
                'raster': request.raster,
                'vector': request.vector,
                'output': request.output or 'temp/clipped.tif'
            }
        }

        result = spatial_engine.execute_raster_operation(operation)
        return result

    except Exception as e:
        logger.error(f"Error clipping raster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vectorize")
async def vectorize_raster(request: VectorizeRasterRequest) -> Dict[str, Any]:
    """
    Convert raster to vector polygons

    Useful for:
    - Converting classified rasters to polygons
    - Extracting areas above/below threshold
    - Integration with vector analysis

    Example:
    ```python
    # Convert areas with NDVI > 0.5 to polygons
    response = requests.post(
        "http://localhost:8000/raster/vectorize",
        json={
            "raster": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
            "threshold": 0.5,
            "operator": "greater"
        }
    )
    ```
    """
    try:
        operation = {
            'type': 'vectorize_raster',
            'params': {
                'raster': request.raster,
                'threshold': request.threshold,
                'operator': request.operator
            }
        }

        result = spatial_engine.execute_raster_operation(operation)
        return result

    except Exception as e:
        logger.error(f"Error vectorizing raster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Utility Endpoints ====================

@router.get("/catalog")
async def list_rasters() -> Dict[str, Any]:
    """
    List available raster datasets

    Returns catalog of NDVI, DEM, land cover, and other raster data
    """
    import json

    catalog_path = Path("data/metadata/catalog.json")

    if not catalog_path.exists():
        return {
            "success": False,
            "error": "Catalog not found"
        }

    with open(catalog_path) as f:
        catalog = json.load(f)

    # Filter raster datasets
    rasters = catalog.get('datasets', {}).get('raster', [])

    return {
        "success": True,
        "count": len(rasters),
        "rasters": rasters
    }


@router.get("/info/{dataset_id}")
async def raster_info(dataset_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a raster dataset

    Args:
        dataset_id: Dataset identifier from catalog

    Returns:
        Metadata including resolution, extent, bands, etc.
    """
    import json

    catalog_path = Path("data/metadata/catalog.json")

    if not catalog_path.exists():
        raise HTTPException(status_code=404, detail="Catalog not found")

    with open(catalog_path) as f:
        catalog = json.load(f)

    # Search for dataset
    rasters = catalog.get('datasets', {}).get('raster', [])

    for raster in rasters:
        if raster.get('id') == dataset_id:
            return {
                "success": True,
                "dataset": raster
            }

    raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "raster-operations",
        "version": "1.0.0"
    }


# ==================== Example Complex Query ====================

@router.post("/analyze/urban-vegetation-loss")
async def analyze_urban_vegetation_loss(
    region: str = Query(..., description="Region name (e.g., 'berlin')"),
    year_start: int = Query(2018, description="Start year"),
    year_end: int = Query(2024, description="End year"),
    threshold: float = Query(-0.2, description="Loss threshold")
) -> Dict[str, Any]:
    """
    Complex analysis: Urban vegetation loss

    Combines:
    - NDVI change detection
    - Urban area filtering
    - Statistical summary

    This is an example of a high-level analysis endpoint that combines
    multiple raster operations.

    Returns:
        Comprehensive analysis results with maps and statistics
    """
    try:
        logger.info(f"Urban vegetation loss analysis: {region} ({year_start}-{year_end})")

        # Build paths
        ndvi_t1 = f"raster/ndvi_timeseries/{region}_ndvi_{year_start}.tif"
        ndvi_t2 = f"raster/ndvi_timeseries/{region}_ndvi_{year_end}.tif"
        urban_mask = f"vector/urban_areas_{region}.geojson"

        # Execute NDVI change detection
        operation = {
            'type': 'vegetation_loss',
            'params': {
                'ndvi_t1': ndvi_t1,
                'ndvi_t2': ndvi_t2,
                'threshold': threshold,
                'mask_vector': urban_mask
            }
        }

        result = spatial_engine.execute_raster_operation(operation)

        if result.get('success'):
            # Add analysis metadata
            result['analysis'] = {
                'region': region,
                'time_period': f"{year_start}-{year_end}",
                'threshold': threshold,
                'type': 'urban_vegetation_loss'
            }

            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error'))

    except Exception as e:
        logger.error(f"Error in urban vegetation loss analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))
