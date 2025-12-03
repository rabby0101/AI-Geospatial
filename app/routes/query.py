import time
from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
from app.models.query_model import NLQuery, QueryResponse, DatasetInfo
from app.utils.deepseek import parse_geospatial_query, get_available_datasets, clear_query_cache
from app.utils.spatial_engine import SpatialEngine
from app.utils.database import db_manager

router = APIRouter(prefix="/api", tags=["queries"])


@router.post("/query", response_model=QueryResponse)
async def geospatial_query(request: NLQuery) -> QueryResponse:
    """
    Process a natural language geospatial query.

    This endpoint:
    1. Parses the natural language query using DeepSeek
    2. Generates a structured operation plan
    3. Executes the plan using the SpatialEngine
    4. Returns GeoJSON results

    Example:
        {
            "question": "Find hospitals within 2 km of flood zones in Berlin"
        }
    """
    start_time = time.time()

    try:
        # Parse the query using DeepSeek
        operation_plan = parse_geospatial_query(
            question=request.question,
            context=request.context,
            user_location=request.user_location,
            selected_feature=request.selected_feature
        )

        # Execute the operation plan
        engine = SpatialEngine()
        result = engine.execute_plan(operation_plan)

        # Calculate execution time
        execution_time = time.time() - start_time

        # Check if execution was successful
        if not result.get("success", False):
            return QueryResponse(
                success=False,
                query=request.question,
                result_type="error",
                data={},
                error=result.get("error", "Unknown error occurred"),
                execution_time=execution_time
            )

        # Extract layer name, operations, reasoning, and datasets from operation plan
        layer_name = operation_plan.layer_name if operation_plan else None
        # Convert operations to list of dicts for JSON serialization
        operations = [
            {
                "operation": op.operation,
                "parameters": op.parameters,
                "description": op.description
            }
            for op in (operation_plan.operations or [])
        ] if operation_plan else None
        reasoning = operation_plan.reasoning if operation_plan else None
        datasets_used = operation_plan.datasets_required if operation_plan else None

        # Return successful response
        return QueryResponse(
            success=True,
            query=request.question,
            result_type=result.get("result_type", "geojson"),
            data=result.get("data", {}),
            layer_name=layer_name,
            metadata=result.get("metadata"),
            operations=operations,
            reasoning=reasoning,
            datasets_used=datasets_used,
            execution_time=execution_time,
            system_prompt=operation_plan.system_prompt if operation_plan else None,
            user_prompt=operation_plan.user_prompt if operation_plan else None
        )

    except Exception as e:
        execution_time = time.time() - start_time
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}"
        )


@router.post("/query-stats", response_model=QueryResponse)
async def geospatial_stats_query(request: NLQuery) -> QueryResponse:
    """
    Process a natural language statistical/aggregation query.

    This endpoint is for queries that return tabular statistical results
    rather than spatial geometries (e.g., density comparisons, aggregations).

    This endpoint:
    1. Parses the natural language query using DeepSeek
    2. Generates a structured operation plan (marked as stats query)
    3. Executes the plan using the SpatialEngine's stats executor
    4. Returns JSON table results instead of GeoJSON

    Example:
        {
            "question": "Compare bank density and restaurant density in Mitte versus Charlottenburg-Wilmersdorf"
        }
    """
    start_time = time.time()

    try:
        # Parse the query using DeepSeek
        operation_plan = parse_geospatial_query(
            question=request.question,
            context=request.context,
            user_location=request.user_location,
            query_type="stats"  # Signal DeepSeek this is a stats query
        )

        # Execute the operation plan with stats executor
        engine = SpatialEngine()
        result = engine.execute_stats_plan(operation_plan)

        # Calculate execution time
        execution_time = time.time() - start_time

        # Check if execution was successful
        if not result.get("success", False):
            return QueryResponse(
                success=False,
                query=request.question,
                result_type="error",
                data={},
                error=result.get("error", "Unknown error occurred"),
                execution_time=execution_time
            )

        # Extract layer name, operations, reasoning, and datasets from operation plan
        layer_name = operation_plan.layer_name if operation_plan else None
        # Convert operations to list of dicts for JSON serialization
        operations = [
            {
                "operation": op.operation,
                "parameters": op.parameters,
                "description": op.description
            }
            for op in (operation_plan.operations or [])
        ] if operation_plan else None
        reasoning = operation_plan.reasoning if operation_plan else None
        datasets_used = operation_plan.datasets_required if operation_plan else None

        # Return successful response
        return QueryResponse(
            success=True,
            query=request.question,
            result_type=result.get("result_type", "table"),
            data=result.get("data", []),
            layer_name=layer_name,
            metadata=result.get("metadata"),
            operations=operations,
            reasoning=reasoning,
            datasets_used=datasets_used,
            execution_time=execution_time
        )

    except Exception as e:
        execution_time = time.time() - start_time
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}"
        )


@router.get("/datasets", response_model=list[DatasetInfo])
async def list_datasets():
    """
    List all available datasets.

    Returns information about vector and raster datasets
    that can be queried.
    """
    try:
        datasets = get_available_datasets()
        return [DatasetInfo(**ds) for ds in datasets]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list datasets: {str(e)}"
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Check API and database health.

    Returns:
        Status of API and database connection
    """
    db_status = db_manager.test_connection()

    return {
        "status": "healthy" if db_status else "degraded",
        "api": "running",
        "database": "connected" if db_status else "disconnected"
    }


@router.post("/execute-sql")
async def execute_sql_query(query: Dict[str, str]) -> Dict[str, Any]:
    """
    Execute a raw SQL query (for advanced users).

    This is a power-user feature for direct PostGIS queries.

    Body:
        {
            "sql": "SELECT * FROM geo.hospitals LIMIT 10"
        }
    """
    try:
        sql = query.get("sql")
        if not sql:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SQL query is required"
            )

        # Execute the query
        result_gdf = db_manager.execute_spatial_query(sql)

        # Convert to GeoJSON
        geojson = result_gdf.__geo_interface__

        return {
            "success": True,
            "data": geojson,
            "metadata": {"count": len(result_gdf)}
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL execution failed: {str(e)}"
        )


@router.get("/load-table/{table_name}")
async def load_table(table_name: str, limit: int = 10000) -> Dict[str, Any]:
    """
    Load a complete table from PostGIS as GeoJSON.

    This endpoint allows manual selection and loading of any PostGIS table
    without requiring natural language queries.

    Parameters:
        table_name: Name of the table to load (from vector schema)
        limit: Maximum number of features to return (default: 10000)

    Returns:
        GeoJSON FeatureCollection with:
        - features: All geometries from the table
        - table_name: Name of the loaded table
        - feature_count: Number of features returned
        - geometry_type: Type of geometries (POINT, POLYGON, etc.)
        - columns: List of available columns

    Example:
        GET /api/load-table/osm_hospitals?limit=5000
    """
    try:
        # Sanitize table name to prevent SQL injection
        if not table_name or not table_name.replace('_', '').replace('-', '').isalnum():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid table name. Must contain only alphanumeric characters, underscores, and hyphens."
            )

        # Get list of available tables to validate
        available_datasets = get_available_datasets()
        available_table_names = [ds.get('table_name') or ds.get('name') for ds in available_datasets]

        # Check if requested table exists
        if table_name not in available_table_names:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Table '{table_name}' not found in available datasets. Available tables: {', '.join(available_table_names[:10])}"
            )

        # Build query with limit
        query = f"""
        SELECT *
        FROM vector.{table_name}
        LIMIT {limit}
        """

        # Execute the query
        result_gdf = db_manager.execute_spatial_query(query)

        if len(result_gdf) == 0:
            return {
                "success": True,
                "table_name": table_name,
                "feature_count": 0,
                "geometry_type": "Unknown",
                "columns": [],
                "data": {
                    "type": "FeatureCollection",
                    "features": []
                }
            }

        # Get geometry type from the first geometry
        geometry_type = result_gdf.geometry.geom_type.iloc[0] if len(result_gdf) > 0 else "Unknown"

        # Get column names
        columns = [col for col in result_gdf.columns if col != 'geometry']

        # Convert to GeoJSON
        geojson = result_gdf.__geo_interface__

        return {
            "success": True,
            "table_name": table_name,
            "feature_count": len(result_gdf),
            "geometry_type": geometry_type,
            "columns": columns,
            "data": geojson
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load table '{table_name}': {str(e)}"
        )


@router.get("/districts-geojson")
async def get_districts_geojson():
    """
    Return Berlin district boundaries as GeoJSON for visualization.

    This endpoint is used by the dashboard to render choropleth maps.
    Returns all districts with their boundaries and properties.

    Returns:
        GeoJSON FeatureCollection with district geometries and properties
    """
    try:
        # Query district boundaries
        query = """
        SELECT
            id,
            name,
            bezirk,
            oteil,
            area_ha,
            geometry
        FROM vector.berlin_districts
        ORDER BY bezirk, name
        """

        gdf = db_manager.execute_spatial_query(query)

        if len(gdf) == 0:
            return {
                "type": "FeatureCollection",
                "features": [],
                "message": "No districts found"
            }

        # Convert to GeoJSON
        geojson = gdf.__geo_interface__

        return geojson

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch district boundaries: {str(e)}"
        )


@router.post("/cache/clear")
async def clear_cache():
    """
    Clear the query response cache.

    This endpoint clears the in-memory cache that stores DeepSeek responses.
    Use this when you need to retry a query without cached results.

    Returns:
        Status message confirming cache was cleared
    """
    try:
        clear_query_cache()
        return {
            "status": "success",
            "message": "Query cache cleared successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )


@router.post("/create-temp-layer")
async def create_temp_layer(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a temporary PostGIS layer from selected feature geometry/geometries.

    Supports both single selection (geometry) and multi-selection (geometries) for context-aware queries.

    Body (single geometry):
        {
            "geometry": {GeoJSON geometry object},
            "session_id": "unique_session_id"
        }

    Body (multiple geometries for multi-select):
        {
            "geometries": [{GeoJSON geometry object}, {GeoJSON geometry object}, ...],
            "session_id": "unique_session_id"
        }

    Returns:
        {
            "success": true,
            "table_name": "temp_selected_[session_id]",
            "schema": "temp",
            "message": "Temporary layer created with N features"
        }
    """
    try:
        session_id = request.get("session_id")

        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_id is required"
            )

        # Support both single geometry (backward compatible) and multiple geometries (multi-select)
        geometry_or_geometries = request.get("geometries") or request.get("geometry")

        if not geometry_or_geometries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="geometry or geometries is required"
            )

        # Create temp layer in database (handles both single and multi)
        temp_table_name = db_manager.create_temp_layer(geometry_or_geometries, session_id, schema="temp")

        if not temp_table_name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create temporary layer"
            )

        # Determine feature count for response message
        feature_count = len(geometry_or_geometries) if isinstance(geometry_or_geometries, list) else 1

        return {
            "success": True,
            "table_name": temp_table_name,
            "schema": "temp",
            "feature_count": feature_count,
            "message": f"Temporary layer created with {feature_count} feature{'s' if feature_count != 1 else ''}: temp.{temp_table_name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create temporary layer: {str(e)}"
        )


@router.post("/drop-temp-layer")
async def drop_temp_layer(request: Dict[str, str]) -> Dict[str, Any]:
    """
    Drop a temporary PostGIS layer.

    Body:
        {
            "session_id": "unique_session_id"
        }

    Returns:
        {
            "success": true,
            "message": "Temporary layer dropped"
        }
    """
    try:
        session_id = request.get("session_id")

        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_id is required"
            )

        # Drop temp layer from database
        success = db_manager.drop_temp_layer(session_id, schema="temp")

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to drop temporary layer"
            )

        return {
            "success": True,
            "message": "Temporary layer dropped successfully"
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to drop temporary layer: {str(e)}"
        )
