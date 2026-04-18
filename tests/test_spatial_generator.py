import pytest
from app.utils.spatial_generator import (
    voronoi_from_points,
    hexagonal_grid,
    convex_hull,
    corridor,
)


def _point_fc(coords_list):
    """Helper: build a GeoJSON FeatureCollection of Points."""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
             "properties": {"id": i}}
            for i, (lon, lat) in enumerate(coords_list)
        ],
    }


BERLIN_HOSPITALS = [
    (13.3770, 52.5200), (13.4050, 52.5170), (13.4280, 52.5300),
    (13.3900, 52.5050), (13.4500, 52.5100), (13.3600, 52.5350),
]

BERLIN_BBOX = {"min_lon": 13.088, "min_lat": 52.338, "max_lon": 13.761, "max_lat": 52.675}


def test_voronoi_returns_feature_collection():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = voronoi_from_points(fc)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0


def test_voronoi_polygons_are_polygons():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = voronoi_from_points(fc)
    for f in result["features"]:
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_voronoi_clips_to_boundary():
    fc = _point_fc(BERLIN_HOSPITALS)
    clip = {
        "type": "Polygon",
        "coordinates": [[[13.3, 52.45], [13.5, 52.45], [13.5, 52.55], [13.3, 52.55], [13.3, 52.45]]]
    }
    result = voronoi_from_points(fc, clip_geojson=clip)
    from shapely.geometry import shape
    clip_shape = shape(clip)
    for f in result["features"]:
        poly = shape(f["geometry"])
        assert clip_shape.contains(poly) or clip_shape.intersects(poly)


def test_voronoi_requires_4_points():
    fc = _point_fc([(13.4, 52.5), (13.41, 52.51), (13.42, 52.52)])
    with pytest.raises(ValueError, match="4 points"):
        voronoi_from_points(fc)


def test_hexgrid_returns_hexagons():
    result = hexagonal_grid(BERLIN_BBOX, cell_size_m=1000)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0
    for f in result["features"]:
        assert f["geometry"]["type"] == "Polygon"
        assert "hex_id" in f["properties"]
        assert "score" in f["properties"]


def test_hexgrid_cells_cover_bbox():
    result = hexagonal_grid(BERLIN_BBOX, cell_size_m=5000)
    from shapely.geometry import shape
    centroids_lons = [shape(f["geometry"]).centroid.x for f in result["features"]]
    assert min(centroids_lons) >= BERLIN_BBOX["min_lon"] - 0.05
    assert max(centroids_lons) <= BERLIN_BBOX["max_lon"] + 0.05


def test_convex_hull_returns_single_polygon():
    fc = _point_fc(BERLIN_HOSPITALS)
    result = convex_hull(fc)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_convex_hull_contains_all_points():
    pts = BERLIN_HOSPITALS
    fc = _point_fc(pts)
    result = convex_hull(fc)
    from shapely.geometry import shape, Point
    hull = shape(result["features"][0]["geometry"])
    for lon, lat in pts:
        assert hull.contains(Point(lon, lat)) or hull.touches(Point(lon, lat))


def test_corridor_returns_polygon():
    line = {
        "type": "LineString",
        "coordinates": [[13.38, 52.52], [13.40, 52.52], [13.42, 52.52]]
    }
    result = corridor(line, width_m=200)
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert result["features"][0]["properties"]["width_m"] == 200
