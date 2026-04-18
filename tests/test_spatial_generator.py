import pytest
from app.utils.spatial_generator import (
    voronoi_from_points,
    hexagonal_grid,
    convex_hull,
    corridor,
    coverage_gaps,
    site_suitability,
    kernel_density,
    equity_gap_analysis,
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


SMALL_BBOX = {"min_lon": 13.3, "min_lat": 52.45, "max_lon": 13.5, "max_lat": 52.55}


def test_convex_hull_empty_raises():
    with pytest.raises(ValueError):
        convex_hull({"type": "FeatureCollection", "features": []})


def test_coverage_gaps_returns_fc():
    services = _point_fc([(13.40, 52.50)])  # one service point in the middle
    clip = {
        "type": "Polygon",
        "coordinates": [[[13.3, 52.45], [13.5, 52.45], [13.5, 52.55], [13.3, 52.55], [13.3, 52.45]]]
    }
    result = coverage_gaps(services, clip, radius_m=100)  # small radius -> should have gaps
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) > 0
    for f in result["features"]:
        assert f["properties"]["gap"] is True


def test_coverage_gaps_no_gaps_when_fully_covered():
    services = _point_fc([(13.40, 52.50)])
    clip = {
        "type": "Polygon",
        "coordinates": [[[13.399, 52.499], [13.401, 52.499], [13.401, 52.501], [13.399, 52.501], [13.399, 52.499]]]
    }
    result = coverage_gaps(services, clip, radius_m=5000)  # huge radius -> no gaps
    assert result["type"] == "FeatureCollection"
    # all area is covered, should have no gaps
    assert len(result["features"]) == 0


def test_site_suitability_returns_sorted():
    grid = hexagonal_grid(SMALL_BBOX, cell_size_m=2000)
    n = len(grid["features"])
    criteria = [{"scores": list(range(n)), "weight": 1.0, "direction": "near"}]
    result = site_suitability(grid, criteria)
    assert result["type"] == "FeatureCollection"
    scores = [f["properties"]["suitability_score"] for f in result["features"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_kernel_density_scores_normalized():
    # Non-collinear points with enough spread to produce a non-singular KDE
    # covariance and meaningful density variation across the grid.
    pts = _point_fc([(13.35, 52.47), (13.40, 52.53), (13.45, 52.47),
                     (13.38, 52.50), (13.42, 52.50)])
    grid = hexagonal_grid(SMALL_BBOX, cell_size_m=500)
    result = kernel_density(pts, grid)
    assert result["type"] == "FeatureCollection"
    scores = [f["properties"]["score"] for f in result["features"]]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert max(scores) == pytest.approx(1.0, abs=0.01)


def test_equity_gap_analysis_flags_underserved():
    district_data = [
        {"name": "Rich", "geometry": {"type": "Point", "coordinates": [13.4, 52.5]}, "svc": 10},
        {"name": "Poor", "geometry": {"type": "Point", "coordinates": [13.5, 52.5]}, "svc": 1},
        {"name": "Mid",  "geometry": {"type": "Point", "coordinates": [13.45, 52.5]}, "svc": 5},
    ]
    result = equity_gap_analysis(district_data, service_col="svc")
    assert result["type"] == "FeatureCollection"
    props = {f["properties"]["name"]: f["properties"] for f in result["features"]}
    assert props["Poor"]["underserved"] is True
    assert props["Rich"]["underserved"] is False
    assert "equity_score" in props["Poor"]
    assert isinstance(props["Poor"]["equity_score"], float)


def test_equity_gap_analysis_with_population():
    district_data = [
        {"name": "Dense", "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
         "svc": 5, "pop": 100000},
        {"name": "Sparse", "geometry": {"type": "Point", "coordinates": [13.5, 52.5]},
         "svc": 5, "pop": 1000},
    ]
    result = equity_gap_analysis(district_data, service_col="svc", population_col="pop")
    props = {f["properties"]["name"]: f["properties"] for f in result["features"]}
    # Dense district has 5 services per 100k = 0.5 per 10k, Sparse = 50 per 10k
    assert props["Dense"]["underserved"] is True
    assert props["Dense"]["rate_per_10k"] is not None
