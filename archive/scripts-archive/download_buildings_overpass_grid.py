#!/usr/bin/env python3
"""
Download buildings from OverpassAPI using a 4x4 grid approach.
Queries each grid cell sequentially with delays to respect API limits.
Aggregates results and exports to GeoJSON for PostGIS import.
"""

import json
import time
import requests
from pathlib import Path
from typing import List, Dict, Any
import geopandas as gpd
from shapely.geometry import shape
import pandas as pd
import xml.etree.ElementTree as ET

# OverpassAPI endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Rate limiting: delay between requests (seconds)
REQUEST_DELAY = 4


def load_grid_config(config_file: str = "data/grid_config.json") -> List[Dict[str, Any]]:
    """Load grid configuration from JSON file."""
    with open(config_file, 'r') as f:
        config = json.load(f)
    return config["cells"]


def build_overpass_query(bbox_string: str) -> str:
    """
    Build OverpassAPI query for buildings in a bounding box.
    bbox_string format: south,west,north,east
    """
    query = f"""
    [bbox:{bbox_string}];
    (
      node["building"];
      way["building"];
      relation["building"];
    );
    out geom;
    """
    return query


def parse_osm_xml(xml_text: str) -> List[Dict]:
    """
    Parse OSM XML response from OverpassAPI and extract elements with geometry.
    Returns list of element dicts compatible with convert_osm_to_geojson.
    """
    elements = []

    try:
        root = ET.fromstring(xml_text)

        # Parse nodes
        for node in root.findall('node'):
            elem_id = node.get('id')
            lat = float(node.get('lat', 0))
            lon = float(node.get('lon', 0))

            tags = {}
            for tag in node.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            # Only include nodes with building tag
            if 'building' in tags:
                elements.append({
                    'type': 'node',
                    'id': elem_id,
                    'lat': lat,
                    'lon': lon,
                    'tags': tags
                })

        # Parse ways
        for way in root.findall('way'):
            elem_id = way.get('id')

            tags = {}
            for tag in way.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            # Only include ways with building tag
            if 'building' in tags:
                geometry = []
                for nd in way.findall('nd'):
                    lat = nd.get('lat')
                    lon = nd.get('lon')
                    if lat and lon:
                        geometry.append({
                            'lat': float(lat),
                            'lon': float(lon)
                        })

                if geometry:
                    elements.append({
                        'type': 'way',
                        'id': elem_id,
                        'tags': tags,
                        'geometry': geometry
                    })

        # Parse relations (multipolygons)
        for relation in root.findall('relation'):
            elem_id = relation.get('id')

            tags = {}
            for tag in relation.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            # Only include relations with building tag
            if 'building' in tags:
                geometry = []
                for member in relation.findall('member'):
                    if member.get('type') == 'way':
                        lat = member.get('lat')
                        lon = member.get('lon')
                        # Try to get geometry from child ways
                        # For simplicity, we'll skip complex relation handling
                        if lat and lon:
                            geometry.append({
                                'lat': float(lat),
                                'lon': float(lon)
                            })

                if geometry:
                    elements.append({
                        'type': 'relation',
                        'id': elem_id,
                        'tags': tags,
                        'geometry': geometry
                    })

    except Exception as e:
        print(f"   Warning: Error parsing XML: {e}")

    return elements


def download_grid_cell(cell: Dict[str, Any], attempt: int = 1, max_attempts: int = 3) -> Dict[str, Any]:
    """
    Download buildings for a single grid cell from OverpassAPI.
    Includes retry logic for failed requests.
    """
    cell_id = cell["id"]
    bbox_string = cell["bbox_string"]

    print(f"\n📍 Cell {cell_id}/16 (Row {cell['row']}, Col {cell['col']})")
    print(f"   Bbox: {bbox_string}")

    try:
        # Build query
        query = build_overpass_query(bbox_string)

        # Make request with proper headers
        print(f"   ⏳ Querying OverpassAPI (attempt {attempt}/{max_attempts})...")
        headers = {
            "User-Agent": "GeoAssist-Berlin-Buildings-Import/1.0"
        }
        response = requests.post(OVERPASS_URL, data=query, timeout=60, headers=headers)

        if response.status_code == 200:
            try:
                # Parse XML response
                elements = parse_osm_xml(response.text)
                print(f"   ✅ Downloaded {len(elements)} features")

                return {
                    "success": True,
                    "cell_id": cell_id,
                    "features": elements,
                    "count": len(elements),
                    "bbox": cell
                }
            except Exception as parse_err:
                # Response parsing error
                print(f"   ⚠️  Error parsing response: {parse_err}")
                response_preview = response.text[:200] if response.text else "(empty)"
                print(f"   Response preview: {response_preview}")

                # Retry if this seems like a temporary server issue
                if attempt < max_attempts:
                    wait_time = min(30, 10 * attempt)
                    print(f"   ⏳ Retrying after {wait_time}s...")
                    time.sleep(wait_time)
                    return download_grid_cell(cell, attempt + 1, max_attempts)

                return {
                    "success": False,
                    "cell_id": cell_id,
                    "error": f"Parse error: {parse_err}",
                    "count": 0
                }
        else:
            print(f"   ⚠️  OverpassAPI returned status {response.status_code}")
            response_preview = response.text[:200] if response.text else "(empty)"
            print(f"   Response: {response_preview}")

            # Retry on server error (429, 503, etc.)
            if response.status_code in [429, 503] and attempt < max_attempts:
                wait_time = min(30, 5 * attempt)  # Exponential backoff
                print(f"   ⏳ Rate limited. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                return download_grid_cell(cell, attempt + 1, max_attempts)

            return {
                "success": False,
                "cell_id": cell_id,
                "error": f"HTTP {response.status_code}",
                "count": 0
            }

    except requests.exceptions.Timeout:
        print(f"   ⚠️  Request timeout")
        if attempt < max_attempts:
            wait_time = 15
            print(f"   ⏳ Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            return download_grid_cell(cell, attempt + 1, max_attempts)
        return {"success": False, "cell_id": cell_id, "error": "Timeout", "count": 0}

    except Exception as e:
        print(f"   ❌ Error: {e}")
        if attempt < max_attempts:
            print(f"   ⏳ Retrying...")
            time.sleep(10)
            return download_grid_cell(cell, attempt + 1, max_attempts)
        return {"success": False, "cell_id": cell_id, "error": str(e), "count": 0}


def convert_osm_to_geojson(osm_elements: List[Dict]) -> List[Dict]:
    """
    Convert OSM elements from OverpassAPI to GeoJSON features.
    Handles nodes, ways, and relations with geometry.
    """
    geojson_features = []

    for element in osm_elements:
        elem_type = element.get("type")
        tags = element.get("tags", {})

        # Skip elements without building tag
        if "building" not in tags:
            continue

        try:
            # Extract geometry
            if elem_type == "node":
                # Node: single point
                coords = [element.get("lon"), element.get("lat")]
                if coords[0] is None or coords[1] is None:
                    continue
                geometry = {"type": "Point", "coordinates": coords}

            elif elem_type == "way":
                # Way: linestring or polygon
                geometry_data = element.get("geometry", [])
                if not geometry_data or len(geometry_data) < 2:
                    continue

                coords = [[g.get("lon"), g.get("lat")] for g in geometry_data]
                coords = [c for c in coords if c[0] is not None and c[1] is not None]

                if len(coords) < 2:
                    continue

                # If closed, it's a polygon
                if coords[0] == coords[-1]:
                    geometry = {"type": "Polygon", "coordinates": [coords]}
                else:
                    # Otherwise linestring
                    geometry = {"type": "LineString", "coordinates": coords}

            elif elem_type == "relation":
                # Relation: treat as polygon from geometry
                geometry_data = element.get("geometry", [])
                if not geometry_data or len(geometry_data) < 3:
                    continue

                coords = [[g.get("lon"), g.get("lat")] for g in geometry_data]
                coords = [c for c in coords if c[0] is not None and c[1] is not None]

                if len(coords) < 3:
                    continue

                # If not closed, close it
                if coords[0] != coords[-1]:
                    coords.append(coords[0])

                if len(coords) >= 3:
                    geometry = {"type": "Polygon", "coordinates": [coords]}
                else:
                    continue

            else:
                continue

            # Create GeoJSON feature
            feature = {
                "type": "Feature",
                "id": element.get("id"),
                "geometry": geometry,
                "properties": tags
            }

            geojson_features.append(feature)

        except Exception as e:
            # Skip elements with geometry errors
            continue

    return geojson_features


def aggregate_grid_downloads(results: List[Dict[str, Any]]) -> List[Dict]:
    """
    Aggregate GeoJSON features from all grid cells.
    """
    all_features = []
    total_downloaded = 0
    successful_cells = 0

    print("\n" + "="*80)
    print("AGGREGATING RESULTS")
    print("="*80)

    for result in results:
        if result["success"]:
            successful_cells += 1
            total_downloaded += result["count"]
            features = convert_osm_to_geojson(result["features"])
            all_features.extend(features)
            print(f"✅ Cell {result['cell_id']:2d}: {result['count']:5d} OSM elements → {len(features):5d} GeoJSON features")
        else:
            print(f"❌ Cell {result['cell_id']:2d}: {result['error']}")

    print("="*80)
    print(f"📊 Summary:")
    print(f"   Successful cells: {successful_cells}/16")
    print(f"   Total OSM elements: {total_downloaded:,}")
    print(f"   Total GeoJSON features: {len(all_features):,}")
    print("="*80)

    return all_features


def convert_to_geodataframe(features: List[Dict]) -> gpd.GeoDataFrame:
    """
    Convert GeoJSON features to GeoDataFrame.
    """
    print("\n🔄 Converting to GeoDataFrame...")

    # Separate features by geometry type
    points = []
    lines = []
    polygons = []

    for feature in features:
        geom_type = feature["geometry"]["type"]
        props = feature.get("properties", {})

        try:
            geom = shape(feature["geometry"])

            if geom_type == "Point":
                points.append({"geometry": geom, **props})
            elif geom_type == "LineString":
                lines.append({"geometry": geom, **props})
            elif geom_type == "Polygon":
                polygons.append({"geometry": geom, **props})
        except Exception as e:
            continue

    # Create GeoDataFrames
    gdfs = []

    if points:
        gdf_points = gpd.GeoDataFrame(points, crs="EPSG:4326")
        gdfs.append(gdf_points)
        print(f"   ✅ Points: {len(points):,}")

    if lines:
        gdf_lines = gpd.GeoDataFrame(lines, crs="EPSG:4326")
        gdfs.append(gdf_lines)
        print(f"   ✅ Lines: {len(lines):,}")

    if polygons:
        gdf_polygons = gpd.GeoDataFrame(polygons, crs="EPSG:4326")
        gdfs.append(gdf_polygons)
        print(f"   ✅ Polygons: {len(polygons):,}")

    # Combine all
    if gdfs:
        gdf_all = pd.concat(gdfs, ignore_index=True)
        print(f"   ✅ Total: {len(gdf_all):,} features")
        return gdf_all
    else:
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")


def save_to_geojson(gdf: gpd.GeoDataFrame, output_file: str = "data/buildings_overpass_raw.geojson"):
    """Save GeoDataFrame to GeoJSON file."""
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    print(f"\n💾 Saving to {output_file}...")
    gdf.to_file(output_file, driver="GeoJSON")
    print(f"   ✅ Saved {len(gdf):,} features")


def main():
    """Main execution flow."""
    print("\n" + "="*80)
    print("OVERPASS API BUILDINGS DOWNLOAD - 4x4 GRID")
    print("="*80)

    # Load grid configuration
    print("\n📂 Loading grid configuration...")
    grid_cells = load_grid_config()
    print(f"   ✅ Loaded {len(grid_cells)} grid cells")

    # Download buildings from each cell
    print("\n📥 DOWNLOADING FROM GRID CELLS")
    results = []

    for i, cell in enumerate(grid_cells, 1):
        result = download_grid_cell(cell)
        results.append(result)

        # Rate limiting: wait between requests
        if i < len(grid_cells):
            print(f"   ⏳ Waiting {REQUEST_DELAY}s before next request...")
            time.sleep(REQUEST_DELAY)

    # Aggregate results
    features = aggregate_grid_downloads(results)

    # Convert to GeoDataFrame
    gdf = convert_to_geodataframe(features)

    # Save to file
    save_to_geojson(gdf)

    print("\n✅ DOWNLOAD COMPLETE!")
    print(f"   GeoDataFrame: {len(gdf):,} features")
    print(f"   Geometry types: {gdf.geometry.type.unique().tolist()}")
    print(f"   Output file: data/buildings_overpass_raw.geojson")
    print("\n   Next step: Run scripts/import_buildings_to_postgis.py")


if __name__ == "__main__":
    main()
