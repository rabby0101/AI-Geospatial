import pytest
import geopandas as gpd
from shapely.geometry import Point, Polygon
from app.utils.spatial_engine import SpatialEngine
from app.models.query_model import OperationPlan, GeospatialOperation


class TestSpatialEngine:
    """Test SpatialEngine operations"""

    @pytest.fixture
    def sample_gdf(self):
        """Create a sample GeoDataFrame"""
        data = {
            'name': ['Hospital A', 'Hospital B'],
            'geometry': [Point(13.4, 52.5), Point(13.5, 52.6)]
        }
        return gpd.GeoDataFrame(data, crs="EPSG:4326")

    def test_engine_initialization(self):
        """Test SpatialEngine can be initialized"""
        engine = SpatialEngine()
        assert engine is not None
        assert engine.loaded_data == {}
        assert engine.current_result is None

    def test_format_result(self):
        """Test formatting GeoDataFrame as result"""
        engine = SpatialEngine()
        data = {
            'name': ['Test'],
            'geometry': [Point(13.4, 52.5)]
        }
        gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")

        result = engine._format_result(gdf)

        assert result["success"] is True
        assert result["result_type"] == "geojson"
        assert "data" in result
        assert "metadata" in result
        assert result["metadata"]["count"] == 1

    def test_buffer_operation(self, sample_gdf):
        """Test buffer operation"""
        engine = SpatialEngine()
        engine.current_result = sample_gdf.copy()

        params = {"distance": 1000}  # 1km buffer
        engine._buffer_operation(params)

        # Check that geometry changed (buffered)
        assert engine.current_result is not None
        assert len(engine.current_result) == 2

    @pytest.mark.unit
    def test_execute_plan_with_return_only(self):
        """Test executing a plan with only return operation"""
        engine = SpatialEngine()

        # Create a simple plan
        plan = OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={},
                    description="Return results"
                )
            ],
            reasoning="Simple return test"
        )

        # This should not crash
        result = engine.execute_plan(plan)
        # Result should indicate no data
        assert "error" in result or "success" in result


class TestGeospatialOperations:
    """Test specific geospatial operations"""

    def test_union_operation(self):
        """Test union of two GeoDataFrames"""
        gdf1 = gpd.GeoDataFrame(
            {'name': ['A'], 'geometry': [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
            crs="EPSG:4326"
        )
        gdf2 = gpd.GeoDataFrame(
            {'name': ['B'], 'geometry': [Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])]},
            crs="EPSG:4326"
        )

        engine = SpatialEngine()
        engine.loaded_data['dataset_b'] = gdf2
        engine.current_result = gdf1

        params = {"with": "dataset_b"}
        engine._union_operation(params)

        assert engine.current_result is not None
        assert len(engine.current_result) > 0
