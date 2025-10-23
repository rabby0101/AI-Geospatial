import time
from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
from app.models.query_model import NLQuery, QueryResponse, DatasetInfo
from app.utils.deepseek import parse_geospatial_query, get_available_datasets
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
            user_location=request.user_location
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
            execution_time=execution_time
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
