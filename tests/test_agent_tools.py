import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from app.utils.agent_tools import (
    geocode_location,
    create_buffer,
    get_schema_info,
    get_table_columns,
    TOOL_REGISTRY,
)


def test_geocode_location_returns_coords():
    mock_result = {
        "name": "Neukölln Rathaus",
        "geometry": "POINT(13.4352 52.4823)",
        "bbox": [13.42, 52.47, 13.45, 52.49],
    }
    with patch("app.utils.agent_tools.location_resolver.resolve_location", return_value=mock_result):
        result = geocode_location("Neukölln Rathaus")
    assert result["lat"] == pytest.approx(52.4823, abs=0.01)
    assert result["lon"] == pytest.approx(13.4352, abs=0.01)
    assert "error" not in result


def test_geocode_location_not_found():
    with patch("app.utils.agent_tools.location_resolver.resolve_location", return_value=None):
        result = geocode_location("NonExistentPlace99999")
    assert "error" in result


def test_create_buffer_from_coords():
    result = create_buffer({"lat": 52.48, "lon": 13.43}, 500)
    assert result.get("type") == "Polygon"
    assert "coordinates" in result


def test_create_buffer_from_geojson_point():
    point = {"type": "Point", "coordinates": [13.43, 52.48]}
    result = create_buffer(point, 200)
    assert result.get("type") == "Polygon"


def test_get_schema_info_returns_tables():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = [
            {"table_name": "osm_parks", "description": "Parks in Berlin", "geometry_type": "MultiPolygon"}
        ]
        result = get_schema_info(["parks", "green"])
    assert isinstance(result, list)


def test_get_table_columns_geom_25833_appears_first():
    """geom_25833 must appear first even when it's at a high ordinal position."""
    mock_cols = pd.DataFrame([
        {"column_name": "id", "data_type": "integer"},
        {"column_name": "name", "data_type": "text"},
        {"column_name": "amenity", "data_type": "text"},
        {"column_name": "addr_street", "data_type": "text"},
        {"column_name": "geom_25833", "data_type": "USER-DEFINED"},
    ])
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = mock_cols
        result = get_table_columns("osm_cafes")
    assert isinstance(result, list)
    assert result[0]["column"] == "geom_25833", (
        f"Expected geom_25833 first, got: {result[0]['column']}"
    )


def test_tool_registry_has_all_tools():
    expected = {
        "geocode_location", "create_buffer", "query_features",
        "spatial_filter", "get_schema_info", "calculate_route",
        "walking_isochrone", "analyze_satellite", "score_locations",
    }
    assert expected == set(TOOL_REGISTRY.keys())
