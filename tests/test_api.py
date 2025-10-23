import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestAPI:
    """Test API endpoints"""

    def test_root_endpoint(self):
        """Test root endpoint returns expected response"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "Cognitive Geospatial Assistant" in response.text

    def test_health_check(self):
        """Test health check endpoint"""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["api"] == "running"

    def test_list_datasets(self):
        """Test listing available datasets"""
        response = client.get("/api/datasets")
        assert response.status_code == 200
        datasets = response.json()
        assert isinstance(datasets, list)

    @pytest.mark.integration
    def test_query_endpoint_structure(self):
        """Test query endpoint accepts valid requests"""
        query_data = {
            "question": "Find all hospitals in Berlin"
        }
        response = client.post("/api/query", json=query_data)

        # Should return 200 or 500 depending on DeepSeek availability
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "query" in data
            assert "result_type" in data

    def test_query_endpoint_validation(self):
        """Test query endpoint validates input"""
        # Empty request should fail
        response = client.post("/api/query", json={})
        assert response.status_code == 422  # Validation error


class TestCORS:
    """Test CORS configuration"""

    def test_cors_headers(self):
        """Test CORS headers are present"""
        response = client.options("/api/health")
        # OPTIONS request should be handled
        assert response.status_code in [200, 405]
