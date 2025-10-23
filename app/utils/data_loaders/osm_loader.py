"""
OpenStreetMap data loader using Overpass API and Geofabrik
"""

import os
import requests
import geopandas as gpd
from pathlib import Path
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class OSMLoader:
    """Load OpenStreetMap data for specific regions and features"""

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    GEOFABRIK_URL = "https://download.geofabrik.de"

    def __init__(self, data_dir: str = "data/vector/osm"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def query_overpass(
        self,
        bbox: tuple,
        features: List[str],
        timeout: int = 180
    ) -> gpd.GeoDataFrame:
        """
        Query OSM data using Overpass API

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            features: List of OSM features like ['hospital', 'school', 'building']
            timeout: Query timeout in seconds

        Returns:
            GeoDataFrame with OSM features
        """

        # Build Overpass QL query
        queries = []
        for feature in features:
            if feature == "building":
                queries.append(f'way["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "hospital":
                queries.append(f'node["amenity"="hospital"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="hospital"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "school":
                queries.append(f'node["amenity"="school"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="school"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "toilet":
                queries.append(f'node["amenity"="toilets"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="toilets"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "pharmacy":
                queries.append(f'node["amenity"="pharmacy"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="pharmacy"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "fire_station":
                queries.append(f'node["amenity"="fire_station"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="fire_station"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "police":
                queries.append(f'node["amenity"="police"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="police"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "park":
                queries.append(f'node["leisure"="park"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["leisure"="park"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "restaurant":
                queries.append(f'node["amenity"="restaurant"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="restaurant"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "transport_stop":
                queries.append(f'node["public_transport"="stop_position"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'node["highway"="bus_stop"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "parking":
                queries.append(f'node["amenity"="parking"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="parking"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "road":
                queries.append(f'way["highway"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "river":
                queries.append(f'way["waterway"="river"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "doctor":
                queries.append(f'node["amenity"="doctors"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="doctors"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "dentist":
                queries.append(f'node["amenity"="dentist"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="dentist"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "clinic":
                queries.append(f'node["amenity"="clinic"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="clinic"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "veterinary":
                queries.append(f'node["amenity"="veterinary"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="veterinary"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "university":
                queries.append(f'node["amenity"="university"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="university"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "library":
                queries.append(f'node["amenity"="library"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="library"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "supermarket":
                queries.append(f'node["shop"="supermarket"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["shop"="supermarket"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "bank":
                queries.append(f'node["amenity"="bank"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="bank"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "atm":
                queries.append(f'node["amenity"="atm"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "post_office":
                queries.append(f'node["amenity"="post_office"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="post_office"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "museum":
                queries.append(f'node["tourism"="museum"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["tourism"="museum"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "theatre":
                queries.append(f'node["amenity"="theatre"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'node["amenity"="cinema"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="theatre"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="cinema"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "gym":
                queries.append(f'node["leisure"="fitness_centre"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'node["amenity"="gym"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["leisure"="fitness_centre"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["amenity"="gym"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "forest":
                queries.append(f'way["landuse"="forest"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'relation["landuse"="forest"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "water_body":
                queries.append(f'way["water"="yes"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["natural"="water"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'way["natural"="lake"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
                queries.append(f'relation["water"="yes"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')
            elif feature == "district":
                queries.append(f'relation["boundary"="administrative"]["admin_level"="8"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});')

        query = f"""
        [out:json][timeout:{timeout}];
        (
            {' '.join(queries)}
        );
        out body;
        >;
        out skel qt;
        """

        logger.info(f"Querying Overpass API for {features} in bbox {bbox}")

        response = requests.post(self.OVERPASS_URL, data={'data': query})
        response.raise_for_status()

        # Convert to GeoDataFrame
        data = response.json()

        # Parse OSM elements to geometries
        from shapely.geometry import Point, LineString, Polygon

        features_list = []
        nodes = {elem['id']: (elem['lon'], elem['lat'])
                for elem in data['elements'] if elem['type'] == 'node'}

        for element in data['elements']:
            if element['type'] == 'node' and 'tags' in element:
                features_list.append({
                    'geometry': Point(element['lon'], element['lat']),
                    'osm_id': element['id'],
                    **element.get('tags', {})
                })
            elif element['type'] == 'way' and 'nodes' in element:
                coords = [nodes[n] for n in element['nodes'] if n in nodes]
                if len(coords) >= 2:
                    if coords[0] == coords[-1] and len(coords) >= 4:
                        geom = Polygon(coords)
                    else:
                        geom = LineString(coords)

                    features_list.append({
                        'geometry': geom,
                        'osm_id': element['id'],
                        **element.get('tags', {})
                    })

        gdf = gpd.GeoDataFrame(features_list, crs="EPSG:4326")
        logger.info(f"Retrieved {len(gdf)} features")

        return gdf

    def download_geofabrik(
        self,
        region: str,
        output_file: Optional[str] = None
    ) -> Path:
        """
        Download OSM data from Geofabrik

        Args:
            region: e.g., 'europe/germany/berlin'
            output_file: Optional custom output filename

        Returns:
            Path to downloaded file
        """

        url = f"{self.GEOFABRIK_URL}/{region}-latest.osm.pbf"

        if output_file is None:
            output_file = f"{region.replace('/', '_')}_latest.osm.pbf"

        output_path = self.data_dir / output_file

        logger.info(f"Downloading {url}")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to {output_path}")

        return output_path

    def load_from_file(self, filepath: str, layer: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Load OSM data from local file (GeoJSON, Shapefile, GeoPackage, etc.)

        Args:
            filepath: Path to file
            layer: Optional layer name for multi-layer formats

        Returns:
            GeoDataFrame
        """

        if layer:
            gdf = gpd.read_file(filepath, layer=layer)
        else:
            gdf = gpd.read_file(filepath)

        logger.info(f"Loaded {len(gdf)} features from {filepath}")

        return gdf

    def get_common_features(self, city: str, bbox: tuple) -> Dict[str, gpd.GeoDataFrame]:
        """
        Download common urban features for a city

        Args:
            city: City name for file naming
            bbox: Bounding box (min_lon, min_lat, max_lon, max_lat)

        Returns:
            Dictionary of GeoDataFrames by feature type
        """

        feature_types = {
            # Original 10 datasets
            'hospitals': ['hospital'],
            'toilets': ['toilet'],
            'pharmacies': ['pharmacy'],
            'fire_stations': ['fire_station'],
            'police_stations': ['police'],
            'parks': ['park'],
            'restaurants': ['restaurant'],
            'transport_stops': ['transport_stop'],
            'schools': ['school'],
            'parking': ['parking'],
            # New Medical (4)
            'doctors': ['doctor'],
            'dentists': ['dentist'],
            'clinics': ['clinic'],
            'veterinary': ['veterinary'],
            # New Education (2)
            'universities': ['university'],
            'libraries': ['library'],
            # New Commerce (4)
            'supermarkets': ['supermarket'],
            'banks': ['bank'],
            'atm': ['atm'],
            'post_offices': ['post_office'],
            # New Recreation (3)
            'museums': ['museum'],
            'theatres': ['theatre'],
            'gyms': ['gym'],
            # New Land Use (2)
            'forests': ['forest'],
            'water_bodies': ['water_body'],
            # New Administrative (1)
            'districts': ['district']
        }

        datasets = {}

        for name, features in feature_types.items():
            try:
                gdf = self.query_overpass(bbox, features)

                # Save to file
                output_file = self.data_dir / f"{city}_{name}.geojson"
                gdf.to_file(output_file, driver='GeoJSON')

                datasets[name] = gdf
                logger.info(f"Saved {name} to {output_file}")

            except Exception as e:
                logger.error(f"Failed to download {name}: {e}")

        return datasets


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    loader = OSMLoader()

    # Example: Download Berlin hospitals
    berlin_bbox = (13.088, 52.338, 13.761, 52.675)

    # Using Overpass API
    hospitals = loader.query_overpass(
        bbox=berlin_bbox,
        features=['hospital']
    )

    print(f"Downloaded {len(hospitals)} hospitals")
    print(hospitals.head())
