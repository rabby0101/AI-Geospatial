from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class OperationType(str, Enum):
    """Types of geospatial operations"""
    LOAD = "load"
    SPATIAL_QUERY = "spatial_query"  # Direct PostGIS SQL query
    RASTER_ANALYSIS = "raster_analysis"  # For NDVI, DEM, land cover analysis
    BUFFER = "buffer"
    CLIP = "clip"
    INTERSECTION = "intersection"
    UNION = "union"
    DIFFERENCE = "difference"
    COMPUTE = "compute"
    AGGREGATE = "aggregate"
    FILTER = "filter"
    SORT = "sort"
    RETURN = "return"


class GeospatialOperation(BaseModel):
    """Represents a single geospatial operation"""
    operation: OperationType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class NLQuery(BaseModel):
    """Natural language query input"""
    question: str = Field(..., description="Natural language geospatial query")
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional context like city, timeframe, etc."
    )
    user_location: Optional[Dict[str, float]] = Field(
        default=None,
        description="User's GPS coordinates {'lat': latitude, 'lon': longitude}"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Find all flood zones within 2 km of hospitals in Berlin.",
                "context": {"city": "Berlin", "buffer_distance": 2000},
                "user_location": {"lat": 52.52, "lon": 13.405}
            }
        }


class OperationPlan(BaseModel):
    """Structured plan from LLM"""
    operations: List[GeospatialOperation]
    reasoning: Optional[str] = None
    datasets_required: List[str] = Field(default_factory=list)
    layer_name: Optional[str] = Field(default=None, description="Generated layer name for the result")


class QueryResponse(BaseModel):
    """Response from geospatial query"""
    success: bool
    query: str
    result_type: str = Field(..., description="Type of result: geojson, statistics, etc.")
    data: Any = Field(..., description="GeoJSON or processed data")
    layer_name: Optional[str] = Field(default=None, description="AI-generated meaningful layer name for the result")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional info like count, area, etc."
    )
    operations: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Structured operations performed to generate results"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="AI reasoning about why this operation plan was chosen"
    )
    datasets_used: Optional[List[str]] = Field(
        default=None,
        description="List of datasets/tables used in the query"
    )
    error: Optional[str] = None
    execution_time: Optional[float] = None

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "query": "Find flood zones near hospitals",
                "result_type": "geojson",
                "data": {"type": "FeatureCollection", "features": []},
                "layer_name": "hospitals_flood_risk_zones",
                "metadata": {"count": 5, "total_area_km2": 12.5},
                "operations": [
                    {
                        "operation": "spatial_query",
                        "parameters": {"sql": "SELECT * FROM vector.osm_hospitals"},
                        "description": "Get all hospitals"
                    }
                ],
                "reasoning": "Using hospitals and flood zones data to find risk areas",
                "datasets_used": ["osm_hospitals", "flood_zones"],
                "execution_time": 1.23
            }
        }


class DatasetInfo(BaseModel):
    """Information about available datasets"""
    name: str
    type: str  # raster or vector
    description: str
    path: Optional[str] = ""  # Made optional for database tables
    schema: Optional[str] = "vector"  # Database schema
    row_count: Optional[int] = None
    geometry_type: Optional[str] = None
    columns: Optional[List[str]] = Field(default_factory=list)
    crs: Optional[str] = "EPSG:4326"
    bounds: Optional[List[float]] = None
    temporal_range: Optional[Dict[str, str]] = None
    tags: List[str] = Field(default_factory=list)
