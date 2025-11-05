"""
Location Optimization Tool
Finds optimal locations for new retail outlets based on multi-criteria analysis.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from shapely.geometry import Point, box, Polygon
from shapely.ops import unary_union
import logging
from app.utils.database import db_manager

logger = logging.getLogger(__name__)


class LocationOptimizer:
    """
    Analyzes geographic locations to find optimal sites for retail outlets.

    Scoring Criteria:
    - Competition density (existing competitors)
    - Population proximity (foot traffic potential)
    - Transportation accessibility (public transit)
    - Parking availability
    - Land use suitability (avoid water/parks/forests)
    """

    # Berlin boundaries (approximate)
    BERLIN_BOUNDS = box(13.08, 52.33, 13.76, 52.67)

    # Scoring weights
    WEIGHTS = {
        "competition": 0.25,      # Lower existing supermarkets = better
        "population": 0.30,        # Higher population density = better
        "transport": 0.20,         # Closer to public transport = better
        "parking": 0.15,           # More parking nearby = better
        "landuse": 0.10            # Suitable land use = better
    }

    def __init__(self, grid_size: int = 500):
        """
        Initialize location optimizer.

        Args:
            grid_size: Grid cell size in meters for analysis
        """
        self.grid_size = grid_size
        self.berlin_gdf = None
        self.supermarkets_gdf = None
        self.transport_gdf = None
        self.parking_gdf = None
        self.landuse_gdf = None

    def analyze_retail_location(
        self,
        retail_type: str = "supermarket",
        radius: int = 1000,
        top_n: int = 10,
        exclude_areas: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Analyze and recommend optimal locations for a new retail outlet.

        Args:
            retail_type: Type of retail (supermarket, pharmacy, restaurant, etc.)
            radius: Analysis radius around grid points (meters)
            top_n: Number of top locations to return
            exclude_areas: List of district names to exclude from analysis

        Returns:
            Dictionary with recommended locations and scoring breakdown
        """
        try:
            logger.info(f"Starting location analysis for {retail_type}...")

            # Load necessary datasets
            self._load_datasets(retail_type, exclude_areas)

            # Create analysis grid
            grid_gdf = self._create_analysis_grid()
            logger.info(f"Created analysis grid with {len(grid_gdf)} cells")

            # Score each grid cell
            scores_gdf = self._score_locations(grid_gdf, radius, retail_type)

            # Get top locations
            top_locations = self._get_top_locations(scores_gdf, top_n)

            return {
                "success": True,
                "retail_type": retail_type,
                "analysis_radius": radius,
                "grid_size": self.grid_size,
                "total_locations_analyzed": len(scores_gdf),
                "top_locations": top_locations,
                "weights": self.WEIGHTS,
                "methodology": {
                    "competition": "Distance to nearest competitor (higher distance = better)",
                    "population": "Proximity to residential areas and population density",
                    "transport": "Distance to public transportation stops",
                    "parking": "Number of parking spaces within radius",
                    "landuse": "Suitable land use (not water/forest/parks)"
                }
            }

        except Exception as e:
            logger.error(f"Error in location analysis: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _load_datasets(self, retail_type: str, exclude_areas: Optional[List[str]]):
        """Load necessary datasets from database."""
        try:
            # Load Berlin districts for exclusion
            self.berlin_gdf = db_manager.load_vector_from_db("berlin_districts")

            if exclude_areas:
                self.berlin_gdf = self.berlin_gdf[
                    ~self.berlin_gdf['name'].isin(exclude_areas)
                ]

            # Load competitors (existing retail)
            self._load_competitors(retail_type)

            # Load public transportation
            self.transport_gdf = db_manager.load_vector_from_db("osm_transport_stops")

            # Load parking
            self.parking_gdf = db_manager.load_vector_from_db("osm_parking")

            # Load land use data
            self.landuse_gdf = db_manager.load_vector_from_db("osm_landuse")

            logger.info("All datasets loaded successfully")

        except Exception as e:
            logger.error(f"Error loading datasets: {e}")
            raise

    def _load_competitors(self, retail_type: str):
        """Load existing retail competitors."""
        retail_mapping = {
            "supermarket": "osm_supermarkets",
            "pharmacy": "osm_pharmacies",
            "restaurant": "osm_restaurants",
            "bank": "osm_banks",
            "gym": "osm_gyms",
            "cafe": "osm_restaurants"  # Cafes are in restaurants table
        }

        table_name = retail_mapping.get(retail_type, "osm_supermarkets")
        try:
            self.supermarkets_gdf = db_manager.load_vector_from_db(table_name)
            logger.info(f"Loaded {len(self.supermarkets_gdf)} existing {retail_type}s")
        except Exception as e:
            logger.warning(f"Could not load {table_name}: {e}")
            self.supermarkets_gdf = gpd.GeoDataFrame(columns=['geometry'])

    def _create_analysis_grid(self) -> gpd.GeoDataFrame:
        """Create hexagonal/grid analysis cells across Berlin."""
        bounds = self.BERLIN_BOUNDS
        min_x, min_y, max_x, max_y = bounds.bounds

        # Create regular grid
        points = []
        x = min_x
        while x < max_x:
            y = min_y
            while y < max_y:
                points.append(Point(x, y))
                y += self.grid_size / 111000  # Convert meters to degrees (roughly)
            x += self.grid_size / 111000

        grid_gdf = gpd.GeoDataFrame(
            geometry=points,
            crs="EPSG:4326"
        )

        # Filter to Berlin boundaries
        if self.berlin_gdf is not None:
            berlin_union = unary_union(self.berlin_gdf.geometry)
            grid_gdf = grid_gdf[grid_gdf.geometry.within(berlin_union)]

        return grid_gdf

    def _score_locations(
        self,
        grid_gdf: gpd.GeoDataFrame,
        radius: int,
        retail_type: str
    ) -> gpd.GeoDataFrame:
        """Score each grid location based on multiple criteria."""

        scores = {
            "competition_score": [],
            "population_score": [],
            "transport_score": [],
            "parking_score": [],
            "landuse_score": [],
            "overall_score": []
        }

        # Convert radius from meters to degrees (approximate)
        radius_degrees = radius / 111000

        for idx, point in grid_gdf.geometry.items():
            try:
                # Create buffer around point
                buffer = point.buffer(radius_degrees)

                # Score competition (prefer areas with fewer competitors)
                competition = self._score_competition(buffer)
                scores["competition_score"].append(competition)

                # Score population proximity (prefer high-density areas)
                population = self._score_population(buffer)
                scores["population_score"].append(population)

                # Score transportation access
                transport = self._score_transport(buffer)
                scores["transport_score"].append(transport)

                # Score parking availability
                parking = self._score_parking(buffer)
                scores["parking_score"].append(parking)

                # Score land use suitability
                landuse = self._score_landuse(buffer)
                scores["landuse_score"].append(landuse)

                # Calculate weighted overall score
                overall = (
                    self.WEIGHTS["competition"] * competition +
                    self.WEIGHTS["population"] * population +
                    self.WEIGHTS["transport"] * transport +
                    self.WEIGHTS["parking"] * parking +
                    self.WEIGHTS["landuse"] * landuse
                )
                scores["overall_score"].append(overall)

            except Exception as e:
                logger.warning(f"Error scoring point {idx}: {e}")
                for key in scores:
                    scores[key].append(0)

        # Add scores to grid
        for key, values in scores.items():
            grid_gdf[key] = values

        # Normalize scores to 0-100
        for col in ["competition_score", "population_score", "transport_score",
                    "parking_score", "landuse_score", "overall_score"]:
            max_val = grid_gdf[col].max()
            if max_val > 0:
                grid_gdf[col] = (grid_gdf[col] / max_val) * 100

        return grid_gdf

    def _score_competition(self, buffer: Polygon) -> float:
        """Score based on distance to competitors (higher = better)."""
        if self.supermarkets_gdf is None or len(self.supermarkets_gdf) == 0:
            return 1.0

        try:
            competitors_in_buffer = self.supermarkets_gdf[
                self.supermarkets_gdf.geometry.within(buffer)
            ]

            # If no competitors nearby, score is high
            if len(competitors_in_buffer) == 0:
                return 1.0

            # More competitors = lower score
            return max(0, 1.0 - (len(competitors_in_buffer) * 0.2))

        except Exception as e:
            logger.warning(f"Error scoring competition: {e}")
            return 0.5

    def _score_population(self, buffer: Polygon) -> float:
        """Score based on proximity to residential areas."""
        try:
            if self.landuse_gdf is None:
                return 0.5

            # Find residential areas in buffer
            residential_types = ['residential', 'commercial', 'mixed']
            residential = self.landuse_gdf[
                (self.landuse_gdf.geometry.intersects(buffer)) &
                (self.landuse_gdf['type'].str.lower().isin(residential_types)
                 if 'type' in self.landuse_gdf.columns else True)
            ]

            if len(residential) == 0:
                return 0.3

            # Calculate intersection area as percentage of buffer
            intersection_area = sum(
                res.intersection(buffer).area for res in residential.geometry
            )
            buffer_area = buffer.area

            if buffer_area == 0:
                return 0.5

            score = min(1.0, intersection_area / buffer_area)
            return score

        except Exception as e:
            logger.warning(f"Error scoring population: {e}")
            return 0.5

    def _score_transport(self, buffer: Polygon) -> float:
        """Score based on proximity to public transportation."""
        try:
            if self.transport_gdf is None or len(self.transport_gdf) == 0:
                return 0.5

            transport_nearby = self.transport_gdf[
                self.transport_gdf.geometry.within(buffer)
            ]

            # More transit stops = higher score
            # Normalize to 0-1 based on typical buffer
            return min(1.0, len(transport_nearby) / 5)

        except Exception as e:
            logger.warning(f"Error scoring transport: {e}")
            return 0.5

    def _score_parking(self, buffer: Polygon) -> float:
        """Score based on parking availability."""
        try:
            if self.parking_gdf is None or len(self.parking_gdf) == 0:
                return 0.5

            parking_nearby = self.parking_gdf[
                self.parking_gdf.geometry.within(buffer)
            ]

            # More parking = higher score
            return min(1.0, len(parking_nearby) / 10)

        except Exception as e:
            logger.warning(f"Error scoring parking: {e}")
            return 0.5

    def _score_landuse(self, buffer: Polygon) -> float:
        """Score based on suitable land use (avoid water, parks, forests)."""
        try:
            if self.landuse_gdf is None:
                return 0.5

            unsuitable_types = ['water', 'forest', 'park', 'meadow', 'grass']

            unsuitable = self.landuse_gdf[
                (self.landuse_gdf.geometry.intersects(buffer)) &
                (self.landuse_gdf['type'].str.lower().isin(unsuitable_types)
                 if 'type' in self.landuse_gdf.columns else False)
            ]

            if len(unsuitable) == 0:
                return 1.0

            # Calculate unsuitable area as percentage
            unsuitable_area = sum(
                unsuit.intersection(buffer).area for unsuit in unsuitable.geometry
            )
            buffer_area = buffer.area

            if buffer_area == 0:
                return 0.5

            unsuitable_ratio = unsuitable_area / buffer_area
            score = max(0, 1.0 - unsuitable_ratio)

            return score

        except Exception as e:
            logger.warning(f"Error scoring landuse: {e}")
            return 0.5

    def _get_top_locations(
        self,
        scores_gdf: gpd.GeoDataFrame,
        top_n: int
    ) -> List[Dict[str, Any]]:
        """Extract top N recommended locations."""

        # Sort by overall score
        top = scores_gdf.nlargest(top_n, "overall_score")

        locations = []
        for idx, row in top.iterrows():
            locations.append({
                "rank": len(locations) + 1,
                "latitude": row.geometry.y,
                "longitude": row.geometry.x,
                "overall_score": round(float(row["overall_score"]), 2),
                "competition_score": round(float(row["competition_score"]), 2),
                "population_score": round(float(row["population_score"]), 2),
                "transport_score": round(float(row["transport_score"]), 2),
                "parking_score": round(float(row["parking_score"]), 2),
                "landuse_score": round(float(row["landuse_score"]), 2),
                "geometry": {
                    "type": "Point",
                    "coordinates": [row.geometry.x, row.geometry.y]
                }
            })

        return locations


# Singleton instance
location_optimizer = LocationOptimizer()
