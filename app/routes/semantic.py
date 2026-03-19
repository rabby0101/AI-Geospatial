"""
Semantic API Routes for Cognitive Geospatial Assistant

Provides REST endpoints for:
- Accessing datasets as JSON-LD
- Executing SPARQL queries
- Validating data with SHACL
- Retrieving the ontology
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.utils.semantic_layer import SemanticLayer, create_semantic_layer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/semantic", tags=["Semantic"])

# Initialize semantic layer (lazy loading)
_semantic_layer: Optional[SemanticLayer] = None


def get_semantic_layer() -> SemanticLayer:
    """Get or create the semantic layer singleton."""
    global _semantic_layer
    if _semantic_layer is None:
        _semantic_layer = create_semantic_layer()
    return _semantic_layer


# =============================================================================
# Request/Response Models
# =============================================================================

class SPARQLQueryRequest(BaseModel):
    """Request model for SPARQL queries."""
    query: str = Field(..., description="SPARQL query string")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
                }
            ]
        }
    }


class SPARQLQueryResponse(BaseModel):
    """Response model for SPARQL queries."""
    success: bool
    results: list
    count: int


class ValidationRequest(BaseModel):
    """Request model for SHACL validation."""
    data: Optional[Dict[str, Any]] = Field(
        None, 
        description="Optional RDF data to validate (Turtle format as string). If not provided, validates the main graph."
    )


class ValidationResponse(BaseModel):
    """Response model for SHACL validation."""
    conforms: bool
    violations: list
    warnings: list
    info: list
    total_issues: int


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/datasets", summary="List datasets as JSON-LD")
async def get_datasets() -> Dict[str, Any]:
    """
    Get all datasets in the knowledge graph with their semantic metadata.
    
    Returns datasets annotated with:
    - Type (Healthcare, Recreation, etc.)
    - Analytical purposes
    - Spatial capabilities
    """
    try:
        layer = get_semantic_layer()
        datasets = layer.get_all_datasets()
        stats = layer.get_statistics()
        
        return {
            "success": True,
            "@context": {
                "geo": "http://geoassist.ai/ontology#",
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#"
            },
            "datasets": datasets,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting datasets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/{dataset_id}", summary="Get dataset by ID")
async def get_dataset(dataset_id: str) -> Dict[str, Any]:
    """
    Get a specific dataset with its full semantic metadata.
    
    Args:
        dataset_id: The dataset identifier (e.g., osm_hospitals)
    """
    try:
        layer = get_semantic_layer()
        
        # Query for this specific dataset
        query = f"""
        PREFIX geo: <http://geoassist.ai/ontology#>
        PREFIX dct: <http://purl.org/dc/terms/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?property ?value
        WHERE {{
            geo:{dataset_id} ?property ?value .
        }}
        """
        
        results = layer.query_sparql(query)
        
        if not results:
            raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
        
        # Also get related datasets
        related = layer.get_related_datasets(dataset_id)
        
        return {
            "success": True,
            "@id": f"http://geoassist.ai/ontology#{dataset_id}",
            "properties": results,
            "related_datasets": related
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dataset {dataset_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/by-purpose/{purpose}", summary="Get datasets by analytical purpose")
async def get_datasets_by_purpose(purpose: str) -> Dict[str, Any]:
    """
    Find datasets that support a specific analytical purpose.
    
    Args:
        purpose: The analytical purpose (e.g., AccessibilityAnalysis, EmergencyPlanning)
    
    Available purposes:
    - AccessibilityAnalysis
    - EmergencyPlanning
    - UrbanPlanning
    - EnvironmentalMonitoring
    - ChangeDetection
    - ProximityAnalysis
    - CoverageAnalysis
    """
    try:
        layer = get_semantic_layer()
        datasets = layer.get_datasets_by_purpose(purpose)
        
        return {
            "success": True,
            "purpose": purpose,
            "datasets": datasets,
            "count": len(datasets)
        }
    except Exception as e:
        logger.error(f"Error querying by purpose {purpose}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ontology", summary="Get the GeoAssist ontology")
async def get_ontology(
    format: str = Query("turtle", description="Output format: turtle, xml, json-ld, n3")
) -> Dict[str, Any]:
    """
    Retrieve the GeoAssist ontology in the specified format.
    
    Useful for understanding the semantic model and available classes.
    """
    try:
        layer = get_semantic_layer()
        
        # Validate format
        valid_formats = ["turtle", "xml", "json-ld", "n3"]
        if format not in valid_formats:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid format. Choose from: {valid_formats}"
            )
        
        ontology = layer.export_graph(format=format)
        
        return {
            "success": True,
            "format": format,
            "ontology": ontology,
            "statistics": layer.get_statistics()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting ontology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sparql", summary="Execute SPARQL query")
async def execute_sparql(request: SPARQLQueryRequest) -> SPARQLQueryResponse:
    """
    Execute a SPARQL query against the knowledge graph.
    
    Example queries:
    
    1. List all dataset types:
    ```sparql
    PREFIX geo: <http://geoassist.ai/ontology#>
    SELECT DISTINCT ?type WHERE { ?s a ?type }
    ```
    
    2. Find healthcare datasets:
    ```sparql
    PREFIX geo: <http://geoassist.ai/ontology#>
    SELECT ?dataset WHERE { ?dataset a geo:HealthcareFacilityDataset }
    ```
    
    3. Get datasets for emergency planning:
    ```sparql
    PREFIX geo: <http://geoassist.ai/ontology#>
    SELECT ?dataset ?title WHERE {
        ?dataset geo:hasAnalyticalPurpose geo:EmergencyPlanning .
        ?dataset <http://purl.org/dc/terms/title> ?title .
    }
    ```
    """
    try:
        layer = get_semantic_layer()
        results = layer.query_sparql(request.query)
        
        return SPARQLQueryResponse(
            success=True,
            results=results,
            count=len(results)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"SPARQL query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", summary="Validate data with SHACL")
async def validate_data(request: ValidationRequest) -> ValidationResponse:
    """
    Validate data against SHACL shapes.
    
    If no data is provided, validates the current knowledge graph.
    """
    try:
        layer = get_semantic_layer()
        result = layer.validate_data()
        
        return ValidationResponse(
            conforms=result.conforms,
            violations=result.violations,
            warnings=result.warnings,
            info=result.info,
            total_issues=len(result.violations) + len(result.warnings) + len(result.info)
        )
    except Exception as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", summary="Get knowledge graph statistics")
async def get_statistics() -> Dict[str, Any]:
    """
    Get statistics about the knowledge graph.
    
    Returns counts of:
    - Total triples
    - Datasets by type
    - Analytical purposes
    - Spatial capabilities
    """
    try:
        layer = get_semantic_layer()
        stats = layer.get_statistics()
        
        return {
            "success": True,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load-catalog", summary="Load JSON catalog into knowledge graph")
async def load_catalog(catalog_path: str = Query(..., description="Path to JSON catalog file")) -> Dict[str, Any]:
    """
    Load a JSON catalog file and convert it to RDF triples.
    
    This populates the knowledge graph with additional dataset metadata.
    """
    try:
        layer = get_semantic_layer()
        triples_added = layer.catalog_to_rdf(catalog_path)
        
        return {
            "success": True,
            "message": f"Loaded catalog from {catalog_path}",
            "triples_added": triples_added,
            "total_triples": layer.get_statistics()["total_triples"]
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Catalog file not found: {catalog_path}")
    except Exception as e:
        logger.error(f"Error loading catalog: {e}")
        raise HTTPException(status_code=500, detail=str(e))
