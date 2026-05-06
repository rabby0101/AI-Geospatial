#!/usr/bin/env python3
"""
Download buildings from OverpassAPI by subdivision.
Queries each of 96 Berlin subdivisions sequentially with delays.
Aggregates results into a single GeoJSON file for PostGIS import.
"""

import json
import time
import requests
from pathlib import Path
from typing import List, Dict, Any
import geopandas as gpd
from shapely.geometry import shape, box
import pandas as pd
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# Configuration
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REQUEST_DELAY = 2  # 2 second delay between requests
OUTPUT_FILE = Path("data/buildings_by_subdivision.geojson")

# Database configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "geoassist")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")
POSTGRES_DB = os.getenv("POSTGRES_DB", "geoassist")

if POSTGRES_PASSWORD:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
else:
    DATABASE_URL = f"postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)


def get_subdivisions() -> List[Dict[str, Any]]:
    """Get all 96 Berlin subdivisions from database."""
    print("\n📍 Loading Berlin subdivisions from database...")

    subdivisions = []

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                name,
                ST_AsText(ST_Envelope(geometry)) as bounds_text,
                ST_XMin(ST_Envelope(geometry)) as west,
                ST_YMin(ST_Envelope(geometry)) as south,
                ST_XMax(ST_Envelope(geometry)) as east,
                ST_YMax(ST_Envelope(geometry)) as north
            FROM vector.berlin_districts
            ORDER BY name
        """))

        for row in result:
            name = row[0]
            west, south, east, north = row[2], row[3], row[4], row[5]

            subdivisions.append({
                'id': len(subdivisions) + 1,
                'name': name,
                'bbox_string': f"{south},{west},{north},{east}",  # Overpass format: south,west,north,east
                'bounds': {
                    'south': float(south),
                    'west': float(west),
                    'north': float(north),
                    'east': float(east)
                }
            })

    print(f"   ✅ Loaded {len(subdivisions)} subdivisions")
    return subdivisions


def build_overpass_query(bbox_string: str) -> str:
    """Build OverpassAPI query for buildings in a bounding box."""
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
    """Parse OSM XML response from OverpassAPI."""
    elements = []

    try:
        root = ET.fromstring(xml_text)

        # Parse nodes with building tag
        for node in root.findall('node'):
            elem_id = node.get('id')
            lat = float(node.get('lat', 0))
            lon = float(node.get('lon', 0))

            tags = {}
            for tag in node.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            if 'building' in tags:
                elements.append({
                    'type': 'node',
                    'id': elem_id,
                    'lat': lat,
                    'lon': lon,
                    'tags': tags
                })

        # Parse ways with building tag
        for way in root.findall('way'):
            elem_id = way.get('id')
            tags = {}
            for tag in way.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            if 'building' in tags:
                geometry = []
                for nd in way.findall('nd'):
                    lat = nd.get('lat')
                    lon = nd.get('lon')
                    if lat and lon:
                        geometry.append({'lat': float(lat), 'lon': float(lon)})

                if geometry:
                    elements.append({
                        'type': 'way',
                        'id': elem_id,
                        'tags': tags,
                        'geometry': geometry
                    })

        # Parse relations with building tag
        for relation in root.findall('relation'):
            elem_id = relation.get('id')
            tags = {}
            for tag in relation.findall('tag'):
                tags[tag.get('k')] = tag.get('v')

            if 'building' in tags:
                geometry = []
                for member in relation.findall('member'):
                    if member.get('type') == 'way':
                        lat = member.get('lat')
                        lon = member.get('lon')
                        if lat and lon:
                            geometry.append({'lat': float(lat), 'lon': float(lon)})

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


def download_subdivision(subdiv: Dict[str, Any], attempt: int = 1) -> Dict[str, Any]:
    """Download buildings for a single subdivision."""
    name = subdiv['name']
    bbox_string = subdiv['bbox_string']

    print(f"   📍 {subdiv['id']:3d}/96  {name:30s} ", end='', flush=True)

    try:
        query = build_overpass_query(bbox_string)
        headers = {"User-Agent": "GeoAssist-Subdivision-Download/1.0"}
        response = requests.post(OVERPASS_URL, data=query, timeout=60, headers=headers)

        if response.status_code == 200:
            elements = parse_osm_xml(response.text)
            print(f"✅ {len(elements)} features")
            return {
                'success': True,
                'name': name,
                'features': elements,
                'count': len(elements)
            }
        else:
            print(f"⚠️  HTTP {response.status_code}")

            if response.status_code in [429, 503] and attempt < 3:
                wait_time = min(30, 10 * attempt)
                print(f"      Rate limited, retrying in {wait_time}s...")
                time.sleep(wait_time)
                return download_subdivision(subdiv, attempt + 1)

            return {
                'success': False,
                'name': name,
                'error': f"HTTP {response.status_code}",
                'count': 0
            }

    except Exception as e:
        print(f"❌ {str(e)[:30]}")
        if attempt < 3:
            time.sleep(10)
            return download_subdivision(subdiv, attempt + 1)
        return {
            'success': False,
            'name': name,
            'error': str(e),
            'count': 0
        }


def convert_osm_to_geojson(osm_elements: List[Dict]) -> List[Dict]:
    """Convert OSM elements to GeoJSON features."""
    features = []

    for elem in osm_elements:
        elem_type = elem.get('type')
        tags = elem.get('tags', {})

        if 'building' not in tags:
            continue

        try:
            if elem_type == 'node':
                coords = [elem.get('lon'), elem.get('lat')]
                if coords[0] is None or coords[1] is None:
                    continue
                geometry = {'type': 'Point', 'coordinates': coords}

            elif elem_type == 'way':
                geom_data = elem.get('geometry', [])
                if not geom_data or len(geom_data) < 2:
                    continue

                coords = [[g.get('lon'), g.get('lat')] for g in geom_data]
                coords = [c for c in coords if c[0] is not None and c[1] is not None]

                if len(coords) < 2:
                    continue

                if coords[0] == coords[-1]:
                    geometry = {'type': 'Polygon', 'coordinates': [coords]}
                else:
                    geometry = {'type': 'LineString', 'coordinates': coords}

            elif elem_type == 'relation':
                geom_data = elem.get('geometry', [])
                if not geom_data or len(geom_data) < 3:
                    continue

                coords = [[g.get('lon'), g.get('lat')] for g in geom_data]
                coords = [c for c in coords if c[0] is not None and c[1] is not None]

                if len(coords) < 3:
                    continue

                if coords[0] != coords[-1]:
                    coords.append(coords[0])

                if len(coords) >= 3:
                    geometry = {'type': 'Polygon', 'coordinates': [coords]}
                else:
                    continue

            else:
                continue

            feature = {
                'type': 'Feature',
                'id': elem.get('id'),
                'geometry': geometry,
                'properties': tags
            }
            features.append(feature)

        except Exception:
            continue

    return features


def main():
    """Main execution."""
    print("\n" + "="*80)
    print("DOWNLOAD BUILDINGS BY SUBDIVISION (96 Ortsteile)")
    print("="*80)

    # Load subdivisions
    subdivisions = get_subdivisions()

    # Download buildings
    print(f"\n📥 DOWNLOADING FROM {len(subdivisions)} SUBDIVISIONS")
    print("="*80)
    results = []

    for i, subdiv in enumerate(subdivisions):
        result = download_subdivision(subdiv)
        results.append(result)

        if i < len(subdivisions) - 1:
            time.sleep(REQUEST_DELAY)

    # Aggregate
    print("\n" + "="*80)
    print("AGGREGATING RESULTS")
    print("="*80)

    all_features = []
    successful = 0
    total_downloaded = 0

    for result in results:
        if result['success']:
            successful += 1
            total_downloaded += result['count']
            features = convert_osm_to_geojson(result['features'])
            all_features.extend(features)

    print(f"✅ Successful: {successful}/{len(subdivisions)}")
    print(f"📊 Total downloaded: {total_downloaded:,} OSM elements")
    print(f"📊 Total features: {len(all_features):,} GeoJSON features")

    # Save GeoJSON
    print(f"\n💾 Saving to {OUTPUT_FILE}...")
    output_data = {
        'type': 'FeatureCollection',
        'features': all_features
    }

    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output_data, f)

    size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"   ✅ Saved {size_mb:.1f}MB")

    # Import to PostGIS
    print(f"\n📤 Importing to PostGIS...")
    if len(all_features) > 0:
        try:
            gdf = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:4326")
            gdf = gdf[gdf.geometry.notna()]
            gdf = gdf[gdf.geometry.is_valid]

            print(f"   ✅ Loading {len(gdf):,} valid features")

            # Drop existing table
            with engine.connect() as conn:
                try:
                    conn.execute(text("DROP TABLE IF EXISTS vector.osm_buildings CASCADE"))
                    conn.commit()
                except:
                    pass

            # Import
            start = time.time()
            gdf.to_postgis(
                'osm_buildings',
                engine,
                schema='vector',
                if_exists='replace',
                index=False,
                chunksize=1000,
                method='multi'
            )
            elapsed = time.time() - start
            print(f"   ✅ Import successful in {elapsed:.1f}s")

            # Create index
            with engine.connect() as conn:
                try:
                    conn.execute(text("""
                        CREATE INDEX idx_osm_buildings_geom
                        ON vector.osm_buildings USING GIST(geometry)
                    """))
                    conn.commit()
                except:
                    pass

            print(f"\n✅ COMPLETE!")
            print(f"📍 Table: vector.osm_buildings")
            print(f"📊 Features: {len(gdf):,}")
            return True
        except Exception as e:
            print(f"❌ Import failed: {e}")
            return False
    else:
        print(f"❌ No features to import")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
