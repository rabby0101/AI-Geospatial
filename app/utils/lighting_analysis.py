"""
Street Lighting Analysis Module

Calculates coverage areas for street lights based on their type and orientation.
Supports smart coverage patterns:
- Full circular coverage for pole-mounted omnidirectional fixtures
- Directional cone/sector coverage for cantilever and attached fixtures
"""

import math
from typing import Dict, List, Any, Tuple, Optional
from shapely.geometry import Point, Polygon, MultiPolygon, LineString
from shapely import wkt
from shapely.ops import nearest_points
import geopandas as gpd
import numpy as np


def calculate_sector_polygon(
    center_lon: float,
    center_lat: float,
    radius_meters: float,
    rotation_degrees: float,
    sector_angle: float = 120.0,
    num_points: int = 32
) -> Polygon:
    """
    Calculate a directional sector (cone) polygon for a street light.

    Args:
        center_lon: Longitude of light position
        center_lat: Latitude of light position
        radius_meters: Coverage radius in meters
        rotation_degrees: Direction the light points (0-360°, 0=North, 90=East)
        sector_angle: Width of the coverage cone in degrees (default 120°)
        num_points: Number of points to approximate the arc

    Returns:
        Shapely Polygon representing the coverage sector
    """
    # Convert radius from meters to approximate degrees
    # At ~52.5°N (Berlin), 1 degree longitude ≈ 69,000m, 1 degree latitude ≈ 111,000m
    radius_lon = radius_meters / (69000 * math.cos(math.radians(center_lat)))
    radius_lat = radius_meters / 111000

    # Start angle and end angle for the sector
    # rotation_degrees is where the light points, sector spreads ±sector_angle/2
    start_angle = rotation_degrees - (sector_angle / 2)
    end_angle = rotation_degrees + (sector_angle / 2)

    # Create sector points
    points = [(center_lon, center_lat)]  # Start at center

    # Generate arc points
    for i in range(num_points + 1):
        # Calculate angle for this point
        fraction = i / num_points
        angle = start_angle + (end_angle - start_angle) * fraction
        angle_rad = math.radians(angle)

        # Convert to Cartesian-like coordinates (North=0°, clockwise)
        # Standard math: 0°=East, counter-clockwise
        # Street light convention: 0°=North, clockwise
        # Conversion: geographic_angle = 90 - math_angle
        math_angle_rad = math.radians(90 - angle)

        # Calculate point on arc
        point_lon = center_lon + radius_lon * math.cos(math_angle_rad)
        point_lat = center_lat + radius_lat * math.sin(math_angle_rad)
        points.append((point_lon, point_lat))

    # Close the polygon by returning to center
    points.append((center_lon, center_lat))

    return Polygon(points)


def calculate_elliptical_sector(
    center_lon: float,
    center_lat: float,
    forward_meters: float,
    side_meters: float,
    rotation_degrees: float,
    sector_angle: float = 120.0,
    num_points: int = 32
) -> Polygon:
    """
    Calculate an elliptical directional sector for realistic street light coverage.

    Directional street lights (cantilever, wall-mounted) cast oblong/elliptical patterns:
    - Longer reach in the forward direction (along beam axis)
    - Shorter reach to the sides

    Args:
        center_lon: Longitude of light position
        center_lat: Latitude of light position
        forward_meters: Maximum reach in forward direction (beam axis)
        side_meters: Maximum reach to the sides (perpendicular to beam)
        rotation_degrees: Direction the light points (0-360°, 0=North, 90=East)
        sector_angle: Width of the coverage cone in degrees (default 120°)
        num_points: Number of points to approximate the arc

    Returns:
        Shapely Polygon representing the elliptical coverage sector
    """
    # Start angle and end angle for the sector
    start_angle = rotation_degrees - (sector_angle / 2)
    end_angle = rotation_degrees + (sector_angle / 2)

    # Create sector points
    points = [(center_lon, center_lat)]  # Start at center

    # Generate arc points with elliptical radius
    for i in range(num_points + 1):
        # Calculate angle for this point
        fraction = i / num_points
        angle = start_angle + (end_angle - start_angle) * fraction

        # Calculate angle relative to rotation direction (0° = forward)
        relative_angle = angle - rotation_degrees
        relative_angle_rad = math.radians(relative_angle)

        # Elliptical radius calculation
        # At 0° (straight forward): use forward_meters
        # At ±90° (to the sides): use side_meters
        # Smooth interpolation in between
        cos_rel = math.cos(relative_angle_rad)
        sin_rel = math.sin(relative_angle_rad)

        # Ellipse equation: r(θ) where major axis = forward, minor axis = side
        # Use parametric form with angle-dependent radius
        ellipse_radius = (forward_meters * side_meters) / math.sqrt(
            (side_meters * cos_rel) ** 2 + (forward_meters * sin_rel) ** 2
        )

        # Convert to geographic coordinates
        radius_lon = ellipse_radius / (69000 * math.cos(math.radians(center_lat)))
        radius_lat = ellipse_radius / 111000

        # Convert angle to math convention and calculate point
        math_angle_rad = math.radians(90 - angle)
        point_lon = center_lon + radius_lon * math.cos(math_angle_rad)
        point_lat = center_lat + radius_lat * math.sin(math_angle_rad)
        points.append((point_lon, point_lat))

    # Close the polygon by returning to center
    points.append((center_lon, center_lat))

    return Polygon(points)


def calculate_circle_polygon(
    center_lon: float,
    center_lat: float,
    radius_meters: float,
    num_points: int = 64
) -> Polygon:
    """
    Calculate a circular coverage polygon for omnidirectional lights.

    Args:
        center_lon: Longitude of light position
        center_lat: Latitude of light position
        radius_meters: Coverage radius in meters
        num_points: Number of points to approximate the circle

    Returns:
        Shapely Polygon representing the circular coverage area
    """
    # Convert radius from meters to approximate degrees
    radius_lon = radius_meters / (69000 * math.cos(math.radians(center_lat)))
    radius_lat = radius_meters / 111000

    points = []
    for i in range(num_points):
        angle = (2 * math.pi * i) / num_points
        point_lon = center_lon + radius_lon * math.cos(angle)
        point_lat = center_lat + radius_lat * math.sin(angle)
        points.append((point_lon, point_lat))

    # Close the polygon
    points.append(points[0])

    return Polygon(points)


# Bulb specification-based coverage lookup
# Maps bulb type and wattage to coverage radii (forward_meters, side_meters)
BULB_COVERAGE_SPECS = {
    'LED': {
        50: {'forward': 20, 'side': 12, 'omnidirectional': 15},
        75: {'forward': 25, 'side': 15, 'omnidirectional': 20},
        100: {'forward': 30, 'side': 18, 'omnidirectional': 25},
        150: {'forward': 40, 'side': 22, 'omnidirectional': 35},
        200: {'forward': 50, 'side': 28, 'omnidirectional': 45},
    },
    'Sodium': {  # High-pressure sodium (HPS)
        70: {'forward': 25, 'side': 15, 'omnidirectional': 20},
        100: {'forward': 30, 'side': 18, 'omnidirectional': 25},
        150: {'forward': 35, 'side': 20, 'omnidirectional': 30},
        250: {'forward': 45, 'side': 25, 'omnidirectional': 40},
        400: {'forward': 55, 'side': 30, 'omnidirectional': 50},
    },
    'Metal Halide': {
        70: {'forward': 25, 'side': 15, 'omnidirectional': 20},
        100: {'forward': 30, 'side': 18, 'omnidirectional': 25},
        150: {'forward': 35, 'side': 20, 'omnidirectional': 30},
        250: {'forward': 45, 'side': 25, 'omnidirectional': 40},
    },
    'Mercury': {  # Older technology
        80: {'forward': 20, 'side': 12, 'omnidirectional': 18},
        125: {'forward': 25, 'side': 15, 'omnidirectional': 22},
        250: {'forward': 35, 'side': 20, 'omnidirectional': 30},
    }
}

# Default coverage values when bulb specs are unknown
DEFAULT_COVERAGE = {
    'directional': {'forward': 30, 'side': 15},  # 2:1 ratio
    'omnidirectional': {'radius': 20}
}


def get_bulb_coverage(bulb_type: str = None, wattage: int = None, is_directional: bool = True) -> Dict[str, float]:
    """
    Get coverage radii based on bulb specifications.

    Args:
        bulb_type: Type of bulb (LED, Sodium, Metal Halide, Mercury)
        wattage: Bulb wattage (W)
        is_directional: Whether the fixture is directional (True) or omnidirectional (False)

    Returns:
        Dictionary with coverage parameters:
        - For directional: {'forward': float, 'side': float}
        - For omnidirectional: {'radius': float}
    """
    # If no specs provided, use defaults
    if not bulb_type or not wattage:
        if is_directional:
            return DEFAULT_COVERAGE['directional']
        else:
            return DEFAULT_COVERAGE['omnidirectional']

    # Normalize bulb type
    bulb_type_normalized = None
    bulb_type_lower = bulb_type.lower()

    if 'led' in bulb_type_lower:
        bulb_type_normalized = 'LED'
    elif 'sodium' in bulb_type_lower or 'hps' in bulb_type_lower or 'natriumdampf' in bulb_type_lower:
        bulb_type_normalized = 'Sodium'
    elif 'halide' in bulb_type_lower or 'halogen' in bulb_type_lower:
        bulb_type_normalized = 'Metal Halide'
    elif 'mercury' in bulb_type_lower or 'quecksilber' in bulb_type_lower:
        bulb_type_normalized = 'Mercury'

    # If bulb type not recognized, use defaults
    if not bulb_type_normalized or bulb_type_normalized not in BULB_COVERAGE_SPECS:
        if is_directional:
            return DEFAULT_COVERAGE['directional']
        else:
            return DEFAULT_COVERAGE['omnidirectional']

    # Find closest wattage match
    wattage_options = sorted(BULB_COVERAGE_SPECS[bulb_type_normalized].keys())

    # Find the closest wattage (round to nearest available value)
    closest_wattage = min(wattage_options, key=lambda x: abs(x - wattage))

    coverage_spec = BULB_COVERAGE_SPECS[bulb_type_normalized][closest_wattage]

    if is_directional:
        return {'forward': coverage_spec['forward'], 'side': coverage_spec['side']}
    else:
        return {'radius': coverage_spec['omnidirectional']}


def determine_coverage_type(
    leuchtentyp: str,
    bulb_type: str = None,
    wattage: int = None
) -> Tuple[str, Dict[str, float], float]:
    """
    Determine coverage pattern based on light fixture type and bulb specifications.

    Args:
        leuchtentyp: Light fixture type from database
        bulb_type: Type of bulb (LED, Sodium, Metal Halide, Mercury) - optional
        wattage: Bulb wattage (W) - optional

    Returns:
        Tuple of (coverage_type, coverage_params, sector_angle)
        - coverage_type: 'circle', 'sector', or 'elliptical_sector'
        - coverage_params: Dict with coverage radii
            - For circle: {'radius': float}
            - For elliptical_sector: {'forward': float, 'side': float}
        - sector_angle: For sectors, the cone width in degrees (0 for circles)
    """
    if not leuchtentyp:
        # Default: omnidirectional circle with bulb specs if available
        coverage_params = get_bulb_coverage(bulb_type, wattage, is_directional=False)
        return ('circle', coverage_params, 0.0)

    leuchtentyp_lower = leuchtentyp.lower()

    # Pole-mounted top fixtures (Aufsatzleuchte) - omnidirectional
    if 'aufsatzleuchte' in leuchtentyp_lower or 'gas-aufsatzleuchte' in leuchtentyp_lower:
        coverage_params = get_bulb_coverage(bulb_type, wattage, is_directional=False)
        return ('circle', coverage_params, 0.0)

    # Cantilever fixtures (Auslegerleuchte) - directional, larger radius
    elif 'auslegerleuchte' in leuchtentyp_lower:
        coverage_params = get_bulb_coverage(bulb_type, wattage, is_directional=True)
        # Cantilever lights typically have wider beam angles
        return ('elliptical_sector', coverage_params, 120.0)

    # Attached/mounted fixtures (Ansatzleuchte) - directional, medium radius
    elif 'ansatzleuchte' in leuchtentyp_lower:
        coverage_params = get_bulb_coverage(bulb_type, wattage, is_directional=True)
        # Wall-mounted lights have narrower beam angles
        return ('elliptical_sector', coverage_params, 100.0)

    # Switch boxes (Schaltkasten) - no illumination, small service area
    elif 'schaltkasten' in leuchtentyp_lower:
        return ('circle', {'radius': 5.0}, 0.0)

    # Default: omnidirectional circle
    else:
        coverage_params = get_bulb_coverage(bulb_type, wattage, is_directional=False)
        return ('circle', coverage_params, 0.0)


def detect_road_bearing(
    light_point: Point,
    road_network_gdf: Optional[gpd.GeoDataFrame] = None,
    search_radius_m: float = 50.0
) -> Optional[float]:
    """
    Detect the bearing/direction of the nearest road to a street light.

    Used to auto-rotate directional lights when rotation data is missing.

    Args:
        light_point: Point geometry of the street light
        road_network_gdf: GeoDataFrame with road network geometries
        search_radius_m: Search radius for finding nearest road (default 50m)

    Returns:
        Bearing in degrees (0-360, where 0=North, 90=East) or None if no road found
    """
    if road_network_gdf is None or len(road_network_gdf) == 0:
        return None

    # Convert to projected CRS for meter-based distance calculations
    light_proj = gpd.GeoSeries([light_point], crs='EPSG:4326').to_crs('EPSG:25833')
    roads_proj = road_network_gdf.to_crs('EPSG:25833')

    # Find nearest road within search radius
    light_point_proj = light_proj.iloc[0]

    # Create buffer around light to search for roads
    search_buffer = light_point_proj.buffer(search_radius_m)

    # Find roads within buffer
    nearby_roads = roads_proj[roads_proj.geometry.intersects(search_buffer)]

    if len(nearby_roads) == 0:
        return None

    # Find the absolute nearest road
    min_distance = float('inf')
    nearest_road = None

    for idx, road in nearby_roads.iterrows():
        distance = light_point_proj.distance(road.geometry)
        if distance < min_distance:
            min_distance = distance
            nearest_road = road

    if nearest_road is None:
        return None

    # Get the road geometry
    road_geom = nearest_road.geometry

    if not isinstance(road_geom, LineString):
        # If it's a MultiLineString, get the nearest part
        if hasattr(road_geom, 'geoms'):
            nearest_part = None
            min_part_distance = float('inf')
            for part in road_geom.geoms:
                part_distance = light_point_proj.distance(part)
                if part_distance < min_part_distance:
                    min_part_distance = part_distance
                    nearest_part = part
            if nearest_part:
                road_geom = nearest_part
            else:
                return None
        else:
            return None

    # Find the point on the road closest to the light
    nearest_point_on_road = road_geom.interpolate(road_geom.project(light_point_proj))

    # Get the road segment around the nearest point
    # Sample a small section of the road to calculate bearing
    project_distance = road_geom.project(nearest_point_on_road)
    segment_length = 10.0  # 10 meters

    # Get points before and after
    point_before = road_geom.interpolate(max(0, project_distance - segment_length))
    point_after = road_geom.interpolate(min(road_geom.length, project_distance + segment_length))

    # Calculate bearing from before to after point
    dx = point_after.x - point_before.x
    dy = point_after.y - point_before.y

    # Calculate angle in radians (standard math: 0=East, counter-clockwise)
    angle_rad = math.atan2(dy, dx)

    # Convert to degrees
    angle_deg = math.degrees(angle_rad)

    # Convert to compass bearing (0=North, 90=East, clockwise)
    bearing = (90 - angle_deg) % 360

    return bearing


def calculate_light_coverage(
    lights_gdf: gpd.GeoDataFrame,
    road_network_gdf: Optional[gpd.GeoDataFrame] = None,
    auto_rotate: bool = True,
    gradient_zones: bool = True
) -> gpd.GeoDataFrame:
    """
    Calculate coverage areas for a set of street lights.

    Args:
        lights_gdf: GeoDataFrame with street light points, must include:
            - geometry: Point geometries
            - rotation: Orientation in degrees (0-360, optional)
            - leuchtentyp: Light fixture type (optional)
            - bulb_type: Type of bulb (LED, Sodium, etc.) - optional
            - wattage: Bulb wattage in watts - optional
        road_network_gdf: Optional road network for auto-rotation
        auto_rotate: Whether to auto-detect rotation from nearby roads
        gradient_zones: Create concentric zones for fade effect (default True)

    Returns:
        GeoDataFrame with coverage polygons and metadata
    """
    coverage_features = []

    for idx, light in lights_gdf.iterrows():
        # Extract position
        geom = light.geometry
        if geom.geom_type == 'MultiPoint':
            # Take first point if MultiPoint
            coords = list(geom.geoms[0].coords)[0]
        else:
            coords = (geom.x, geom.y)

        lon, lat = coords

        # Get light properties
        rotation = light.get('rotation', 0.0)
        if rotation is None or math.isnan(rotation):
            rotation = 0.0

        leuchtentyp = light.get('leuchtentyp', '')
        bulb_type = light.get('bulb_type', None) or light.get('leuchtmittel', None)
        wattage = light.get('wattage', None) or light.get('leistung', None)

        # Convert wattage to int if it's a string or float
        if wattage is not None:
            try:
                wattage = int(float(wattage))
            except (ValueError, TypeError):
                wattage = None

        # Determine coverage type and parameters
        coverage_type, coverage_params, sector_angle = determine_coverage_type(
            leuchtentyp, bulb_type, wattage
        )

        # Auto-rotate directional lights based on road alignment if rotation is missing
        rotation_source = 'database'
        if auto_rotate and coverage_type in ['sector', 'elliptical_sector']:
            if rotation == 0.0 or rotation is None:
                # Try to detect road bearing
                light_point = Point(lon, lat)
                detected_bearing = detect_road_bearing(light_point, road_network_gdf)
                if detected_bearing is not None:
                    rotation = detected_bearing
                    rotation_source = 'auto_detected'

        # Calculate coverage polygon(s)
        # If gradient_zones is enabled, create multiple concentric zones
        if gradient_zones:
            # Define gradient zones: (radius_fraction, opacity)
            # Inner zones are brighter, outer zones fade away
            zones = [
                (1.0, 0.05),   # Outermost: 100% radius, 5% opacity (very faint)
                (0.75, 0.12),  # 75% radius, 12% opacity
                (0.50, 0.25),  # 50% radius, 25% opacity
                (0.25, 0.45),  # Innermost: 25% radius, 45% opacity (brightest)
            ]

            for zone_idx, (radius_fraction, zone_opacity) in enumerate(zones):
                # Calculate polygon for this zone
                if coverage_type == 'circle':
                    radius = coverage_params.get('radius', 20.0)
                    zone_radius = radius * radius_fraction
                    coverage_poly = calculate_circle_polygon(lon, lat, zone_radius)
                    radius_display = radius
                elif coverage_type == 'elliptical_sector':
                    forward = coverage_params.get('forward', 30.0)
                    side = coverage_params.get('side', 15.0)
                    zone_forward = forward * radius_fraction
                    zone_side = side * radius_fraction
                    coverage_poly = calculate_elliptical_sector(
                        lon, lat, zone_forward, zone_side, rotation, sector_angle
                    )
                    radius_display = (forward + side) / 2
                else:  # regular sector (legacy)
                    radius = coverage_params.get('radius', 25.0) if 'radius' in coverage_params else 25.0
                    zone_radius = radius * radius_fraction
                    coverage_poly = calculate_sector_polygon(
                        lon, lat, zone_radius, rotation, sector_angle
                    )
                    radius_display = radius

                # Create feature for this zone
                feature = {
                    'geometry': coverage_poly,
                    'light_id': light.get('id', idx),
                    'leuchtentyp': leuchtentyp,
                    'bulb_type': bulb_type,
                    'wattage': wattage,
                    'coverage_type': coverage_type,
                    'radius_m': radius_display,
                    'rotation': rotation,
                    'rotation_source': rotation_source,
                    'sector_angle': sector_angle if coverage_type != 'circle' else 360.0,
                    'strasse': light.get('strasse', ''),
                    'status': light.get('status', ''),
                    'betriebsart': light.get('betriebsart', ''),
                    'gradient_zone': zone_idx,  # 0=outermost, 3=innermost
                    'gradient_opacity': zone_opacity,
                    'zone_radius_fraction': radius_fraction
                }

                # Add elliptical-specific parameters
                if coverage_type == 'elliptical_sector':
                    feature['forward_reach_m'] = coverage_params.get('forward', 30.0)
                    feature['side_reach_m'] = coverage_params.get('side', 15.0)

                coverage_features.append(feature)
        else:
            # Original single-polygon approach (no gradient)
            if coverage_type == 'circle':
                radius = coverage_params.get('radius', 20.0)
                coverage_poly = calculate_circle_polygon(lon, lat, radius)
                radius_display = radius
            elif coverage_type == 'elliptical_sector':
                forward = coverage_params.get('forward', 30.0)
                side = coverage_params.get('side', 15.0)
                coverage_poly = calculate_elliptical_sector(
                    lon, lat, forward, side, rotation, sector_angle
                )
                radius_display = (forward + side) / 2
            else:  # regular sector (legacy)
                radius = coverage_params.get('radius', 25.0) if 'radius' in coverage_params else 25.0
                coverage_poly = calculate_sector_polygon(
                    lon, lat, radius, rotation, sector_angle
                )
                radius_display = radius

            # Create single feature
            feature = {
                'geometry': coverage_poly,
                'light_id': light.get('id', idx),
                'leuchtentyp': leuchtentyp,
                'bulb_type': bulb_type,
                'wattage': wattage,
                'coverage_type': coverage_type,
                'radius_m': radius_display,
                'rotation': rotation,
                'rotation_source': rotation_source,
                'sector_angle': sector_angle if coverage_type != 'circle' else 360.0,
                'strasse': light.get('strasse', ''),
                'status': light.get('status', ''),
                'betriebsart': light.get('betriebsart', '')
            }

            # Add elliptical-specific parameters
            if coverage_type == 'elliptical_sector':
                feature['forward_reach_m'] = coverage_params.get('forward', 30.0)
                feature['side_reach_m'] = coverage_params.get('side', 15.0)

            coverage_features.append(feature)

    # Create GeoDataFrame
    coverage_gdf = gpd.GeoDataFrame(coverage_features, crs='EPSG:4326')

    return coverage_gdf


def add_coverage_to_lights_geojson(lights_geojson: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add coverage area geometries to a lights GeoJSON response.

    Args:
        lights_geojson: GeoJSON FeatureCollection with street light points

    Returns:
        Enhanced GeoJSON with coverage area features added
    """
    # Convert to GeoDataFrame
    lights_gdf = gpd.GeoDataFrame.from_features(lights_geojson['features'], crs='EPSG:4326')

    if len(lights_gdf) == 0:
        return lights_geojson

    # Calculate coverage areas
    coverage_gdf = calculate_light_coverage(lights_gdf)

    # Convert coverage to GeoJSON features
    coverage_features = []
    for idx, coverage in coverage_gdf.iterrows():
        properties = {
            'light_id': coverage.light_id,
            'leuchtentyp': coverage.leuchtentyp,
            'coverage_type': coverage.coverage_type,
            'radius_m': coverage.radius_m,
            'rotation': coverage.rotation,
            'sector_angle': coverage.sector_angle,
            'strasse': coverage.strasse,
            'status': coverage.status,
            'betriebsart': coverage.betriebsart,
            'feature_type': 'coverage_area'
        }

        # Add rotation source if available
        if hasattr(coverage, 'rotation_source'):
            properties['rotation_source'] = coverage.rotation_source

        # Add bulb specifications if available
        if hasattr(coverage, 'bulb_type') and coverage.bulb_type:
            properties['bulb_type'] = coverage.bulb_type
        if hasattr(coverage, 'wattage') and coverage.wattage:
            properties['wattage'] = coverage.wattage

        # Add elliptical parameters if available
        if hasattr(coverage, 'forward_reach_m'):
            properties['forward_reach_m'] = coverage.forward_reach_m
        if hasattr(coverage, 'side_reach_m'):
            properties['side_reach_m'] = coverage.side_reach_m

        # Add gradient zone properties if available
        if hasattr(coverage, 'gradient_zone'):
            properties['gradient_zone'] = coverage.gradient_zone
        if hasattr(coverage, 'gradient_opacity'):
            properties['gradient_opacity'] = coverage.gradient_opacity
        if hasattr(coverage, 'zone_radius_fraction'):
            properties['zone_radius_fraction'] = coverage.zone_radius_fraction

        feature = {
            'type': 'Feature',
            'geometry': coverage.geometry.__geo_interface__,
            'properties': properties
        }
        coverage_features.append(feature)

    # Add coverage features to the GeoJSON
    enhanced_geojson = {
        'type': 'FeatureCollection',
        'features': lights_geojson['features'] + coverage_features
    }

    return enhanced_geojson


def analyze_coverage_overlap(
    coverage_gdf: gpd.GeoDataFrame
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    """
    Analyze multi-fixture overlap to identify over-lit and under-lit areas.

    Args:
        coverage_gdf: GeoDataFrame with individual coverage polygons

    Returns:
        Tuple of (overlap_zones_gdf, statistics)
        - overlap_zones_gdf: GeoDataFrame with zones categorized by coverage level
        - statistics: Dict with overlap analysis results
    """
    if len(coverage_gdf) == 0:
        return gpd.GeoDataFrame(), {
            'total_lights': 0,
            'coverage_levels': {},
            'total_union_area_m2': 0
        }

    # Convert to projected CRS for accurate geometric operations
    coverage_proj = coverage_gdf.to_crs('EPSG:25833')  # UTM 33N (Berlin)

    # Calculate union of all coverage areas
    from shapely.ops import unary_union
    total_coverage_union = unary_union(coverage_proj.geometry.tolist())

    # Create overlap count grid by counting overlapping polygons at each location
    # This is computationally expensive, so we'll use a spatial index approach
    overlap_zones = []

    # For each coverage polygon, determine how many other polygons overlap it
    for idx, coverage in coverage_proj.iterrows():
        geom = coverage.geometry

        # Count overlaps
        overlap_count = 0
        for idx2, other_coverage in coverage_proj.iterrows():
            if idx != idx2 and geom.intersects(other_coverage.geometry):
                overlap_count += 1

        # Categorize coverage level
        if overlap_count == 0:
            level = 'single'
            description = 'Low light (1 fixture)'
        elif overlap_count <= 2:
            level = 'adequate'
            description = 'Adequate (2-3 fixtures)'
        else:
            level = 'well_lit'
            description = f'Well-lit ({overlap_count + 1} fixtures)'

        overlap_zones.append({
            'geometry': geom,
            'light_id': coverage.light_id,
            'overlap_count': overlap_count + 1,  # Include self
            'coverage_level': level,
            'description': description,
            'area_m2': geom.area
        })

    overlap_gdf = gpd.GeoDataFrame(overlap_zones, crs='EPSG:25833')

    # Calculate statistics
    coverage_levels = overlap_gdf['coverage_level'].value_counts().to_dict()

    statistics = {
        'total_lights': len(coverage_gdf),
        'coverage_levels': coverage_levels,
        'total_union_area_m2': float(total_coverage_union.area) if hasattr(total_coverage_union, 'area') else 0,
        'average_overlap_count': float(overlap_gdf['overlap_count'].mean()),
        'max_overlap_count': int(overlap_gdf['overlap_count'].max())
    }

    # Convert back to WGS84 for GeoJSON export
    overlap_gdf_wgs84 = overlap_gdf.to_crs('EPSG:4326')

    return overlap_gdf_wgs84, statistics


def identify_dark_areas(
    coverage_gdf: gpd.GeoDataFrame,
    road_network_gdf: gpd.GeoDataFrame = None,
    buffer_distance_m: float = 20.0
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    """
    Identify dark areas (gaps in street light coverage) along road networks.

    Args:
        coverage_gdf: GeoDataFrame with street light coverage polygons
        road_network_gdf: Optional GeoDataFrame with road network geometries
        buffer_distance_m: Buffer distance around roads to check for coverage (default 20m)

    Returns:
        Tuple of (dark_areas_gdf, statistics)
        - dark_areas_gdf: GeoDataFrame with unlit road segments
        - statistics: Dict with dark area analysis results
    """
    if len(coverage_gdf) == 0:
        return gpd.GeoDataFrame(), {'dark_segments': 0, 'total_dark_length_m': 0}

    # Convert to projected CRS
    coverage_proj = coverage_gdf.to_crs('EPSG:25833')

    # Calculate union of all coverage areas
    from shapely.ops import unary_union
    total_coverage_union = unary_union(coverage_proj.geometry.tolist())

    dark_areas = []

    if road_network_gdf is not None and len(road_network_gdf) > 0:
        # Convert roads to projected CRS
        roads_proj = road_network_gdf.to_crs('EPSG:25833')

        # Find road segments not covered by lights
        for idx, road in roads_proj.iterrows():
            road_geom = road.geometry

            # Check if road intersects with coverage area
            if not road_geom.intersects(total_coverage_union):
                # Completely unlit road segment
                dark_areas.append({
                    'geometry': road_geom,
                    'road_id': road.get('id', idx) if 'id' in road else idx,
                    'road_name': road.get('name', 'Unknown') if 'name' in road else 'Unknown',
                    'coverage_status': 'no_coverage',
                    'length_m': road_geom.length
                })
            else:
                # Partially covered - find uncovered portions
                try:
                    uncovered = road_geom.difference(total_coverage_union)
                    if not uncovered.is_empty:
                        length_uncovered = uncovered.length if hasattr(uncovered, 'length') else 0
                        if length_uncovered > 10:  # Only include segments > 10m
                            dark_areas.append({
                                'geometry': uncovered,
                                'road_id': road.get('id', idx) if 'id' in road else idx,
                                'road_name': road.get('name', 'Unknown') if 'name' in road else 'Unknown',
                                'coverage_status': 'partial_coverage',
                                'length_m': length_uncovered
                            })
                except Exception as e:
                    # Skip if difference operation fails
                    pass

    # Create GeoDataFrame
    if dark_areas:
        dark_gdf = gpd.GeoDataFrame(dark_areas, crs='EPSG:25833')
        dark_gdf_wgs84 = dark_gdf.to_crs('EPSG:4326')

        statistics = {
            'dark_segments': len(dark_gdf),
            'total_dark_length_m': float(dark_gdf['length_m'].sum()),
            'total_dark_length_km': float(dark_gdf['length_m'].sum() / 1000),
            'fully_unlit_segments': len(dark_gdf[dark_gdf['coverage_status'] == 'no_coverage']),
            'partially_unlit_segments': len(dark_gdf[dark_gdf['coverage_status'] == 'partial_coverage'])
        }

        return dark_gdf_wgs84, statistics
    else:
        return gpd.GeoDataFrame(crs='EPSG:4326'), {
            'dark_segments': 0,
            'total_dark_length_m': 0,
            'total_dark_length_km': 0,
            'fully_unlit_segments': 0,
            'partially_unlit_segments': 0
        }


def analyze_light_coverage_statistics(coverage_gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """
    Calculate statistics about light coverage.

    Args:
        coverage_gdf: GeoDataFrame with coverage polygons

    Returns:
        Dictionary with coverage statistics
    """
    if len(coverage_gdf) == 0:
        return {
            'total_lights': 0,
            'total_coverage_area_m2': 0,
            'coverage_types': {}
        }

    # Calculate total coverage area (approximate, using geographic CRS)
    # Convert to a projected CRS for accurate area calculation
    coverage_projected = coverage_gdf.to_crs('EPSG:25833')  # UTM 33N (Berlin)
    total_area_m2 = coverage_projected.geometry.area.sum()

    # Count by coverage type
    coverage_types = coverage_gdf['coverage_type'].value_counts().to_dict()

    # Count by light type
    light_types = coverage_gdf['leuchtentyp'].value_counts().to_dict()

    return {
        'total_lights': len(coverage_gdf),
        'total_coverage_area_m2': float(total_area_m2),
        'total_coverage_area_km2': float(total_area_m2 / 1_000_000),
        'coverage_types': coverage_types,
        'light_types': light_types,
        'average_radius_m': float(coverage_gdf['radius_m'].mean())
    }
