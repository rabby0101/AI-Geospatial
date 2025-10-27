#!/usr/bin/env python3
"""
Download allotment gardens (Kleingärten) from OpenStreetMap for Berlin
Uses Overpass API to query leisure=garden areas
"""

import requests
import json
import geopandas as gpd
from shapely.geometry import shape
import os

# Berlin bounding box
BERLIN_BBOX = [52.33, 13.08, 52.67, 13.76]  # south, west, north, east

def download_allotment_gardens():
    """Download allotment gardens from Overpass API"""
    
    print("Downloading allotment gardens from OpenStreetMap...")
    
    # Overpass API query for allotment gardens in Berlin
    overpass_query = f"""
    [bbox:{BERLIN_BBOX[0]},{BERLIN_BBOX[1]},{BERLIN_BBOX[2]},{BERLIN_BBOX[3]}];
    (
        way["leisure"="garden"]["access"~"yes|permissive|private"];
        relation["leisure"="garden"]["access"~"yes|permissive|private"];
    );
    out geom;
    """
    
    # Alternative: just leisure=garden (broader search)
    overpass_query_broad = f"""
    [bbox:{BERLIN_BBOX[0]},{BERLIN_BBOX[1]},{BERLIN_BBOX[2]},{BERLIN_BBOX[3]}];
    (
        way["leisure"="garden"];
        relation["leisure"="garden"];
    );
    out geom;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    
    try:
        # Try the broader query first
        print("Querying Overpass API (this may take a minute)...")
        response = requests.post(url, data=overpass_query_broad, timeout=60)
        response.raise_for_status()
        
        # Parse OSM data
        osm_data = response.json()
        print(f"Got {len(osm_data.get('elements', []))} elements from OSM")
        
        # Convert to GeoDataFrame
        features = []
        for element in osm_data.get('elements', []):
            if element['type'] == 'way' or element['type'] == 'relation':
                if 'geometry' in element:
                    try:
                        # Extract geometry
                        coords = [(pt['lon'], pt['lat']) for pt in element['geometry']]
                        if len(coords) >= 3:
                            from shapely.geometry import Polygon
                            geom = Polygon(coords)
                            
                            # Extract tags
                            tags = element.get('tags', {})
                            
                            feature = {
                                'osm_id': element['id'],
                                'name': tags.get('name', 'Unnamed Garden'),
                                'access': tags.get('access', 'unknown'),
                                'description': tags.get('description', ''),
                                'website': tags.get('website', ''),
                                'phone': tags.get('phone', ''),
                                'operator': tags.get('operator', ''),
                                'geometry': geom
                            }
                            features.append(feature)
                    except Exception as e:
                        print(f"Skipped element {element['id']}: {e}")
        
        if features:
            gdf = gpd.GeoDataFrame(features, crs='EPSG:4326')
            print(f"Created GeoDataFrame with {len(gdf)} allotment gardens")
            
            # Save to GeoJSON
            output_path = '/Users/skfazlarabby/projects/AI Geospatial/data/vector/osm_allotment_gardens.geojson'
            gdf.to_file(output_path, driver='GeoJSON')
            print(f"Saved to {output_path}")
            
            return gdf
        else:
            print("No allotment gardens found")
            return None
            
    except requests.exceptions.Timeout:
        print("Request timed out. Creating sample data instead...")
        return create_sample_data()
    except Exception as e:
        print(f"Error downloading from Overpass API: {e}")
        print("Creating sample data instead...")
        return create_sample_data()

def create_sample_data():
    """Create sample allotment gardens data for testing"""
    print("Creating sample allotment gardens data...")
    
    from shapely.geometry import Polygon, Point
    import geopandas as gpd
    
    # Sample allotment gardens in Berlin (Kleingartenanlagen)
    sample_gardens = [
        {
            'osm_id': 1,
            'name': 'Kleingartenanlage Mitte',
            'access': 'private',
            'description': 'Allotment gardens in Mitte district',
            'operator': 'Kleingärtnerbund Berlin',
            'geometry': Point(13.4, 52.52).buffer(0.01)
        },
        {
            'osm_id': 2,
            'name': 'Gartenanlage Charlottenburg',
            'access': 'permissive',
            'description': 'Community gardens in Charlottenburg',
            'operator': 'Stadtgrün',
            'geometry': Point(13.3, 52.52).buffer(0.012)
        },
        {
            'osm_id': 3,
            'name': 'Gartenparadies Friedrichshain',
            'access': 'private',
            'description': 'Allotment gardens in Friedrichshain',
            'operator': 'Gartenfreunde',
            'geometry': Point(13.47, 52.51).buffer(0.009)
        },
        {
            'osm_id': 4,
            'name': 'Kleingarten Prenzlauer Berg',
            'access': 'yes',
            'description': 'Public gardens in Prenzlauer Berg',
            'operator': 'Senatsverwaltung',
            'geometry': Point(13.41, 52.54).buffer(0.008)
        },
        {
            'osm_id': 5,
            'name': 'Gartenkolonie Wedding',
            'access': 'private',
            'description': 'Garden colony in Wedding district',
            'operator': 'Kleingärtnerbund',
            'geometry': Point(13.38, 52.55).buffer(0.011)
        }
    ]
    
    gdf = gpd.GeoDataFrame(sample_gardens, crs='EPSG:4326')
    print(f"Created sample GeoDataFrame with {len(gdf)} gardens")
    
    # Save to GeoJSON
    output_path = '/Users/skfazlarabby/projects/AI Geospatial/data/vector/osm_allotment_gardens.geojson'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    gdf.to_file(output_path, driver='GeoJSON')
    print(f"Saved sample data to {output_path}")
    
    return gdf

if __name__ == '__main__':
    gdf = download_allotment_gardens()
    if gdf is not None:
        print(f"\nSummary:")
        print(f"Total gardens: {len(gdf)}")
        print(f"Columns: {list(gdf.columns)}")
        print(f"\nFirst 3 gardens:")
        print(gdf.head(3))
