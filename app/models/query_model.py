from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class OperationType(str, Enum):
    """Types of geospatial operations"""
    LOAD = "load"
    SPATIAL_QUERY = "spatial_query"  # Direct PostGIS SQL query
    RASTER_ANALYSIS = "raster_analysis"  # For NDVI, DEM, land cover analysis
    ROUTING = "routing"  # Road network routing and connectivity analysis
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

    NEAREST_BY_ROAD = "nearest_by_road"  # Find nearest POI using road network distance
    WALKING_TIME = "walking_time"  # Find POIs within walking time using road network


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
    selected_feature: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Selected feature from map for context-aware queries {'geometry': 'WKT', 'geometry_type': 'Point/Polygon/...', 'properties': {...}, 'name': 'feature_name'}"
    )
    drawn_geometry: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Geometry drawn by user (GeoJSON geometry format) - used as spatial context for LLM"
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider to use: 'deepseek', 'gemini', or 'gemma3'"
    )
    active_skill: Optional[str] = Field(
        default=None,
        description="Active skill ID (e.g. 'location_expert'). Scopes the pipeline to reduce token usage."
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
    system_prompt: Optional[str] = Field(default=None, description="System prompt sent to DeepSeek (for debugging)")
    user_prompt: Optional[str] = Field(default=None, description="User prompt sent to DeepSeek (for debugging)")


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
    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt sent to DeepSeek (for debugging in browser console)"
    )
    user_prompt: Optional[str] = Field(
        default=None,
        description="User prompt sent to DeepSeek (for debugging in browser console)"
    )

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


class DirectionStep(BaseModel):
    """Single step in turn-by-turn directions"""
    step: int
    instruction: str
    street: Optional[str] = None
    distance_m: float = 0.0
    duration_seconds: Optional[float] = None


class Waypoint(BaseModel):
    """Waypoint in optimal tour"""
    order: int
    name: str
    lat: float
    lon: float
    arrival_distance_m: Optional[float] = None


class RoutingResult(BaseModel):
    """Result of optimal tour routing"""
    success: bool
    geometry: Dict[str, Any] = Field(..., description="GeoJSON LineString of the route")
    total_distance_m: float
    total_time_minutes: Optional[float] = None
    waypoints: List[Waypoint] = Field(default_factory=list)
    directions: List[DirectionStep] = Field(default_factory=list)
    optimal_sequence: List[int] = Field(default_factory=list, description="Order of visited waypoints")
    layer_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Satellite image analysis models
# ---------------------------------------------------------------------------

class SatelliteUploadResponse(BaseModel):
    """Response from POST /api/satellite/upload"""
    success: bool
    session_id: str
    file_count: int = Field(description="Number of files processed in this upload")
    total_files: int = Field(description="Total files accumulated in the session")
    dates_found: List[str] = Field(default_factory=list, description="ISO dates extracted from filenames")
    bands_found: List[str] = Field(default_factory=list, description="Band names found (B04, B08, etc.)")
    tile_ids: List[str] = Field(default_factory=list, description="Sentinel-2 tile IDs found (T33UUU, etc.)")
    errors: List[str] = Field(default_factory=list, description="Non-fatal parse warnings per file")
    message: Optional[str] = None


class SatelliteAnalyzeRequest(BaseModel):
    """Request body for POST /api/satellite/analyze"""
    question: str = Field(..., description="Natural language analysis question")
    session_id: str = Field(..., description="Session ID from the upload step")
    llm_provider: str = Field(default="gemini", description="LLM provider: 'gemini' or 'deepseek'")
