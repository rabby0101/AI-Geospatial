"""
Unit Tests for Semantic Layer

Tests for:
- Ontology loading
- Catalog to RDF conversion
- SPARQL query execution
- SHACL validation
- API endpoints
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.utils.semantic_layer import SemanticLayer, create_semantic_layer, ValidationResult

client = TestClient(app)


class TestSemanticLayer:
    """Test SemanticLayer core functionality."""
    
    @pytest.fixture
    def semantic_layer(self):
        """Create a fresh SemanticLayer instance."""
        return create_semantic_layer()
    
    @pytest.mark.unit
    def test_semantic_layer_initialization(self, semantic_layer):
        """Test that SemanticLayer initializes correctly."""
        assert semantic_layer is not None
        assert semantic_layer.graph is not None
        assert len(semantic_layer.graph) > 0  # Should have loaded ontology
    
    @pytest.mark.unit
    def test_ontology_loads(self, semantic_layer):
        """Test that the OWL ontology loads without errors."""
        stats = semantic_layer.get_statistics()
        assert stats["total_triples"] > 0
        assert stats["datasets"] > 0  # Should have some datasets defined
    
    @pytest.mark.unit
    def test_get_statistics(self, semantic_layer):
        """Test statistics method returns expected keys."""
        stats = semantic_layer.get_statistics()
        
        expected_keys = [
            "total_triples",
            "datasets",
            "vector_datasets",
            "raster_datasets"
        ]
        
        for key in expected_keys:
            assert key in stats, f"Missing key: {key}"
            assert isinstance(stats[key], int), f"{key} should be an integer"
    
    @pytest.mark.unit
    def test_sparql_query_basic(self, semantic_layer):
        """Test basic SPARQL query execution."""
        query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5"
        results = semantic_layer.query_sparql(query)
        
        assert isinstance(results, list)
        assert len(results) <= 5
        
        if results:
            assert "s" in results[0]
            assert "p" in results[0]
            assert "o" in results[0]
    
    @pytest.mark.unit
    def test_sparql_query_datasets(self, semantic_layer):
        """Test SPARQL query for datasets."""
        query = """
        PREFIX geo: <http://geoassist.ai/ontology#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?dataset ?type
        WHERE {
            ?dataset rdf:type ?type .
            FILTER(STRSTARTS(STR(?type), "http://geoassist.ai/ontology#"))
        }
        LIMIT 10
        """
        results = semantic_layer.query_sparql(query)
        
        assert isinstance(results, list)
        # Should find at least one dataset from the ontology
    
    @pytest.mark.unit
    def test_sparql_query_invalid(self, semantic_layer):
        """Test that invalid SPARQL query raises error."""
        invalid_query = "THIS IS NOT VALID SPARQL"
        
        with pytest.raises(ValueError):
            semantic_layer.query_sparql(invalid_query)
    
    @pytest.mark.unit
    def test_get_datasets_by_purpose(self, semantic_layer):
        """Test finding datasets by analytical purpose."""
        results = semantic_layer.get_datasets_by_purpose("AccessibilityAnalysis")
        
        assert isinstance(results, list)
        # Hospitals, pharmacies, etc. should support accessibility analysis
    
    @pytest.mark.unit
    def test_export_graph_turtle(self, semantic_layer):
        """Test exporting graph as Turtle."""
        output = semantic_layer.export_graph(format="turtle")
        
        assert isinstance(output, str)
        assert len(output) > 0
        assert "@prefix" in output or "PREFIX" in output
    
    @pytest.mark.unit
    def test_export_graph_jsonld(self, semantic_layer):
        """Test exporting graph as JSON-LD."""
        output = semantic_layer.export_graph(format="json-ld")
        
        assert isinstance(output, str)
        assert len(output) > 0
    
    @pytest.mark.unit
    def test_get_all_datasets(self, semantic_layer):
        """Test getting all datasets."""
        datasets = semantic_layer.get_all_datasets()
        
        assert isinstance(datasets, list)


class TestSemanticValidation:
    """Test SHACL validation functionality."""
    
    @pytest.fixture
    def semantic_layer(self):
        """Create a fresh SemanticLayer instance."""
        return create_semantic_layer()
    
    @pytest.mark.unit
    def test_validation_returns_result(self, semantic_layer):
        """Test that validation returns a ValidationResult."""
        result = semantic_layer.validate_data()
        
        assert isinstance(result, ValidationResult)
        assert hasattr(result, "conforms")
        assert hasattr(result, "violations")
        assert hasattr(result, "warnings")
        assert hasattr(result, "info")
    
    @pytest.mark.unit
    def test_validation_result_to_dict(self, semantic_layer):
        """Test ValidationResult.to_dict() method."""
        result = semantic_layer.validate_data()
        result_dict = result.to_dict()
        
        assert isinstance(result_dict, dict)
        assert "conforms" in result_dict
        assert "total_issues" in result_dict


class TestSemanticAPI:
    """Test semantic API endpoints."""
    
    def test_semantic_datasets_endpoint(self):
        """Test /api/semantic/datasets endpoint."""
        response = client.get("/api/semantic/datasets")
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "datasets" in data
        assert "statistics" in data
    
    def test_semantic_statistics_endpoint(self):
        """Test /api/semantic/statistics endpoint."""
        response = client.get("/api/semantic/statistics")
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "statistics" in data
    
    def test_semantic_ontology_endpoint(self):
        """Test /api/semantic/ontology endpoint."""
        response = client.get("/api/semantic/ontology")
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "ontology" in data
        assert "format" in data
    
    def test_semantic_ontology_format_param(self):
        """Test /api/semantic/ontology with format parameter."""
        response = client.get("/api/semantic/ontology?format=turtle")
        
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "turtle"
    
    def test_semantic_ontology_invalid_format(self):
        """Test /api/semantic/ontology with invalid format."""
        response = client.get("/api/semantic/ontology?format=invalid")
        
        assert response.status_code == 400
    
    def test_semantic_sparql_endpoint(self):
        """Test /api/semantic/sparql endpoint."""
        query_data = {
            "query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5"
        }
        response = client.post("/api/semantic/sparql", json=query_data)
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "results" in data
        assert "count" in data
    
    def test_semantic_sparql_invalid_query(self):
        """Test /api/semantic/sparql with invalid query."""
        query_data = {
            "query": "NOT VALID SPARQL"
        }
        response = client.post("/api/semantic/sparql", json=query_data)
        
        assert response.status_code == 400
    
    def test_semantic_validate_endpoint(self):
        """Test /api/semantic/validate endpoint."""
        response = client.post("/api/semantic/validate", json={})
        
        assert response.status_code == 200
        data = response.json()
        assert "conforms" in data
        assert "violations" in data
        assert "warnings" in data
    
    def test_semantic_datasets_by_purpose_endpoint(self):
        """Test /api/semantic/datasets/by-purpose/{purpose} endpoint."""
        response = client.get("/api/semantic/datasets/by-purpose/AccessibilityAnalysis")
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "purpose" in data
        assert "datasets" in data


class TestCatalogConversion:
    """Test catalog to RDF conversion."""
    
    @pytest.fixture
    def semantic_layer(self):
        """Create a fresh SemanticLayer instance."""
        return create_semantic_layer()
    
    @pytest.mark.unit
    def test_catalog_to_rdf(self, semantic_layer):
        """Test converting JSON catalog to RDF."""
        catalog_path = Path("data/metadata/catalog.json")
        
        if catalog_path.exists():
            initial_count = len(semantic_layer.graph)
            triples_added = semantic_layer.catalog_to_rdf(str(catalog_path))
            
            assert triples_added >= 0
            assert len(semantic_layer.graph) >= initial_count
    
    @pytest.mark.unit
    def test_berlin_osm_catalog_to_rdf(self, semantic_layer):
        """Test converting Berlin OSM catalog to RDF."""
        catalog_path = Path("data/metadata/berlin_osm_catalog.json")
        
        if catalog_path.exists():
            initial_count = len(semantic_layer.graph)
            triples_added = semantic_layer.catalog_to_rdf(str(catalog_path))
            
            assert triples_added >= 0
            assert len(semantic_layer.graph) >= initial_count
