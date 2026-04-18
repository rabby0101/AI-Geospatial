import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import geopandas as gpd
from app.utils.agent_tools import (
    geocode_location,
    create_buffer,
    get_schema_info,
    get_table_columns,
    TOOL_REGISTRY,
    generate_voronoi,
    generate_hexgrid,
    generate_convex_hull,
    generate_corridor,
    save_generated_layer,
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
        mock_db.execute_query.return_value = pd.DataFrame([
            {"table_name": "osm_parks", "description": "Parks in Berlin",
             "geometry_type": "MultiPolygon", "row_count": 42}
        ])
        result = get_schema_info(["parks", "green"])
    assert "catalog" in result or isinstance(result, list)


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
        "geocode_location", "create_buffer",
        "spatial_filter", "get_schema_info", "calculate_route",
        "walking_isochrone", "analyze_satellite", "score_locations",
    }
    assert expected.issubset(set(TOOL_REGISTRY.keys()))


def _mock_hospital_rows():
    import pandas as pd
    # Points spread in both lon and lat to produce a non-degenerate convex hull
    coords = [
        (13.38, 52.52), (13.39, 52.53), (13.40, 52.51),
        (13.41, 52.54), (13.42, 52.50), (13.43, 52.55),
    ]
    return pd.DataFrame([
        {"id": i, "geom": f'{{"type":"Point","coordinates":[{lon},{lat}]}}'}
        for i, (lon, lat) in enumerate(coords)
    ])


def test_generate_voronoi_returns_saved_result():
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("app.utils.agent_tools.save_generated_layer") as mock_save:
        mock_db.execute_query.return_value = _mock_hospital_rows()
        mock_save.return_value = {"saved": True, "table": "temp_layers.layer_voronoi_x",
                                   "feature_count": 5, "geojson": {"type": "FeatureCollection", "features": []}}
        result = generate_voronoi("public.osm_hospitals", id_col="id")
    assert "error" not in result or result.get("saved")


def test_generate_hexgrid_returns_feature_collection():
    result = generate_hexgrid(
        {"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55},
        cell_size_m=1000,
    )
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0


def test_generate_convex_hull_returns_polygon():
    with patch("app.utils.agent_tools.db_manager") as mock_db:
        mock_db.execute_query.return_value = _mock_hospital_rows()
        result = generate_convex_hull("public.osm_hospitals")
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_generate_corridor_returns_polygon():
    result = generate_corridor(
        {"type": "LineString", "coordinates": [[13.38, 52.52], [13.42, 52.52]]},
        width_m=200,
    )
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_save_generated_layer_writes_to_postgis():
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
            "properties": {"name": "test"},
        }],
    }
    with patch("app.utils.agent_tools.db_manager") as mock_db, \
         patch("geopandas.GeoDataFrame.to_postgis") as mock_postgis:
        mock_db.engine = MagicMock()
        result = save_generated_layer(fc, "test_layer", "A test layer")
    mock_postgis.assert_called_once()
    assert result["saved"] is True
    assert "table" in result


def test_save_generated_layer_empty_fc_returns_error():
    result = save_generated_layer({"type": "FeatureCollection", "features": []}, "empty")
    assert "error" in result
