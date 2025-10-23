import pytest
from pydantic import ValidationError
from app.models.query_model import (
    NLQuery,
    GeospatialOperation,
    OperationType,
    QueryResponse,
    DatasetInfo
)


class TestModels:
    """Test Pydantic models"""

    def test_nl_query_valid(self):
        """Test NLQuery with valid data"""
        query = NLQuery(question="Find hospitals in Berlin")
        assert query.question == "Find hospitals in Berlin"
        assert query.context is None

    def test_nl_query_with_context(self):
        """Test NLQuery with context"""
        query = NLQuery(
            question="Find hospitals",
            context={"city": "Berlin", "buffer": 2000}
        )
        assert query.context["city"] == "Berlin"

    def test_nl_query_missing_question(self):
        """Test NLQuery fails without question"""
        with pytest.raises(ValidationError):
            NLQuery()

    def test_geospatial_operation(self):
        """Test GeospatialOperation model"""
        op = GeospatialOperation(
            operation=OperationType.LOAD,
            parameters={"dataset": "hospitals"},
            description="Load hospitals"
        )
        assert op.operation == OperationType.LOAD
        assert op.parameters["dataset"] == "hospitals"

    def test_query_response_success(self):
        """Test successful QueryResponse"""
        response = QueryResponse(
            success=True,
            query="Test query",
            result_type="geojson",
            data={"type": "FeatureCollection", "features": []},
            execution_time=1.5
        )
        assert response.success is True
        assert response.execution_time == 1.5

    def test_query_response_error(self):
        """Test error QueryResponse"""
        response = QueryResponse(
            success=False,
            query="Test query",
            result_type="error",
            data={},
            error="Something went wrong"
        )
        assert response.success is False
        assert response.error == "Something went wrong"

    def test_dataset_info(self):
        """Test DatasetInfo model"""
        dataset = DatasetInfo(
            name="test_dataset",
            type="vector",
            description="Test dataset",
            path="/data/test.geojson",
            tags=["test", "sample"]
        )
        assert dataset.name == "test_dataset"
        assert "test" in dataset.tags
        assert dataset.crs == "EPSG:4326"  # Default value
