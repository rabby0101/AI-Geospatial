"""
DEM Query Handler - Routes for Digital Elevation Model queries
Handles terrain analysis, slope analysis, flood risk, development suitability
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from shapely.geometry import box
import geopandas as gpd
import rasterio
import numpy as np

from app.utils.dem_analysis import DEMAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dem", tags=["dem"])

# DEM file paths
DEM_FILE = Path("data/raster/dem/berlin_dem.tif")
DEMO_RESULTS = Path("data/raster/dem/demo_results")
SUBDIVISIONS_FILE = Path("data/vector/osm/berlin_districts.geojson")
DEV_SUITABILITY_FILE = Path("data/raster/dem/demo_results/berlin_development_suitability.geojson")


class DEMQueryHandler:
    """Handle DEM-related natural language queries"""

    def __init__(self):
        self.dem_path = DEM_FILE
        if self.dem_path.exists():
            self.analyzer = DEMAnalyzer(str(self.dem_path))
        else:
            self.analyzer = None

    def handle_terrain_query(self, query: str) -> Dict[str, Any]:
        """Handle terrain analysis queries"""
        if not self.analyzer:
            return {
                "success": False,
                "error": "DEM data not available. Please download Berlin DEM first.",
                "data": {}
            }

        try:
            # Get terrain statistics
            stats = self.analyzer.compute_terrain_statistics()

            result = {
                "success": True,
                "query_type": "terrain_analysis",
                "data": {
                    "elevation": stats["elevation"],
                    "slope": stats["slope"],
                    "relief": stats["relief"]
                },
                "summary": f"""
                **Terrain Analysis - Berlin**

                **Elevation:**
                - Minimum: {stats['elevation']['min']:.1f}m
                - Maximum: {stats['elevation']['max']:.1f}m
                - Average: {stats['elevation']['mean']:.1f}m
                - Std Dev: {stats['elevation']['std']:.1f}m

                **Slope:**
                - Range: {stats['slope']['min']:.2f}° - {stats['slope']['max']:.2f}°
                - Average: {stats['slope']['mean']:.2f}°
                - Std Dev: {stats['slope']['std']:.2f}°

                **Relief (Elevation Range):** {stats['relief']:.1f}m
                """
            }
            return result

        except Exception as e:
            logger.error(f"Error in terrain query: {e}")
            return {"success": False, "error": str(e), "data": {}}

    def handle_slope_query(self, query: str) -> Dict[str, Any]:
        """Handle slope/steepness queries"""
        if not self.analyzer:
            return {"success": False, "error": "DEM not available", "data": {}}

        try:
            slope = self.analyzer.compute_slope()

            return {
                "success": True,
                "query_type": "slope_analysis",
                "data": {
                    "min_slope": float(slope.min()),
                    "max_slope": float(slope.max()),
                    "mean_slope": float(slope.mean()),
                    "std_slope": float(slope.std())
                },
                "summary": f"""
                **Slope Analysis - Berlin**

                Steepest areas: {slope.max():.2f}°
                Flattest areas: {slope.min():.2f}°
                Average slope: {slope.mean():.2f}°

                Interpretation:
                - Flat terrain (0-5°): Good for construction
                - Rolling terrain (5-15°): Moderate slope
                - Steep terrain (15-30°): Limited development
                - Very steep (30°+): Challenging for development
                """
            }

        except Exception as e:
            logger.error(f"Error in slope query: {e}")
            return {"success": False, "error": str(e), "data": {}}

    def handle_development_query(self, query: str) -> Dict[str, Any]:
        """Handle development suitability queries - Returns actual GeoJSON polygons"""
        if not self.analyzer:
            return {"success": False, "error": "DEM not available", "data": {}}

        try:
            # Check if development results exist
            dev_file = DEMO_RESULTS / "berlin_development_suitability.geojson"

            if dev_file.exists():
                dev_gdf = gpd.read_file(dev_file)
                num_areas = len(dev_gdf)

                # Convert to GeoJSON FeatureCollection - this is the KEY FIX!
                geojson_data = json.loads(dev_gdf.to_json())

                return {
                    "success": True,
                    "query_type": "development_suitability",
                    "data": geojson_data,  # Return actual GeoJSON with polygons
                    "metadata": {
                        "suitable_areas": num_areas,
                        "criteria": "Slope ≤ 20°",
                        "total_features": num_areas,
                        "geometry_type": "Polygon"
                    },
                    "summary": f"""
                    **Development Suitability Analysis - Berlin**

                    Total suitable areas: {num_areas:,}
                    Suitability criteria: Slope ≤ 20°

                    These areas are suitable for urban development based on:
                    - Gentle slopes (≤ 20°)
                    - Stable terrain for construction
                    - Minimal flood risk

                    The map shows all {num_areas:,} development-suitable polygons across Berlin.
                    """
                }
            else:
                # Generate on-demand
                dev_gdf = self.analyzer.analyze_development_suitability(max_slope=20.0)
                geojson_data = json.loads(dev_gdf.to_json())

                return {
                    "success": True,
                    "query_type": "development_suitability",
                    "data": geojson_data,  # Return actual GeoJSON with polygons
                    "metadata": {
                        "suitable_areas": len(dev_gdf),
                        "criteria": "Slope ≤ 20°",
                        "geometry_type": "Polygon"
                    },
                    "summary": f"Found {len(dev_gdf):,} development-suitable areas in Berlin"
                }

        except Exception as e:
            logger.error(f"Error in development query: {e}")
            return {"success": False, "error": str(e), "data": {}}

    def handle_flood_risk_query(self, query: str) -> Dict[str, Any]:
        """Handle flood risk queries"""
        if not self.analyzer:
            return {"success": False, "error": "DEM not available", "data": {}}

        try:
            # Flood risk requires flow accumulation - check if it exists
            flood_file = DEMO_RESULTS / "berlin_flood_risk.geojson"

            if flood_file.exists():
                flood_gdf = gpd.read_file(flood_file)
                return {
                    "success": True,
                    "query_type": "flood_risk",
                    "data": {
                        "flood_risk_areas": len(flood_gdf),
                        "risk_level": "Top 20% highest risk"
                    },
                    "summary": f"""
                    **Flood Risk Assessment - Berlin**

                    High-risk areas identified: {len(flood_gdf):,}
                    Risk criteria: Low elevation + High flow accumulation

                    These areas have combined risk from:
                    - Low elevation (below average)
                    - High water flow concentration
                    - Potential flooding during heavy rainfall
                    """
                }
            else:
                return {
                    "success": False,
                    "error": "Flood risk analysis not yet computed. Run full analysis.",
                    "data": {}
                }

        except Exception as e:
            logger.error(f"Error in flood risk query: {e}")
            return {"success": False, "error": str(e), "data": {}}

    def handle_classification_query(self, query: str) -> Dict[str, Any]:
        """Handle terrain classification queries"""
        if not self.analyzer:
            return {"success": False, "error": "DEM not available", "data": {}}

        try:
            # Check if classification exists
            class_file = DEMO_RESULTS / "berlin_terrain_classification.tif"

            if class_file.exists():
                with rasterio.open(class_file) as src:
                    data = src.read(1)

                unique, counts = np.unique(data, return_counts=True)
                classification = {
                    1: "Flat (0-5°)",
                    2: "Rolling (5-15°)",
                    3: "Steep (15-30°)",
                    4: "Very Steep (30°+)"
                }

                summary = "**Terrain Classification - Berlin**\n\n"
                total_pixels = data.size
                for val, count in zip(unique, counts):
                    if val > 0:
                        pct = (count / total_pixels) * 100
                        summary += f"- {classification.get(int(val), f'Class {val}')}: {pct:.1f}%\n"

                return {
                    "success": True,
                    "query_type": "terrain_classification",
                    "data": {
                        "classifications": {
                            classification.get(int(v), f"Class {v}"): int(c)
                            for v, c in zip(unique, counts) if v > 0
                        }
                    },
                    "summary": summary
                }
            else:
                terrain = self.analyzer.classify_terrain()
                return {
                    "success": True,
                    "query_type": "terrain_classification",
                    "data": {"status": "Terrain classified successfully"}
                }

        except Exception as e:
            logger.error(f"Error in classification query: {e}")
            return {"success": False, "error": str(e), "data": {}}

    def analyze_development_by_subdivisions(self) -> Dict[str, Any]:
        """
        Analyze development suitability by subdivisions (small admin areas)
        Returns: Top 3 subdivisions by count + GeoJSON of top subdivision
        """
        try:
            # Load subdivisions and development suitability areas
            if not SUBDIVISIONS_FILE.exists():
                return {"success": False, "error": "Subdivisions file not found", "data": {}}

            if not DEV_SUITABILITY_FILE.exists():
                return {"success": False, "error": "Development suitability data not found", "data": {}}

            logger.info("Loading subdivisions and development suitability data...")
            subdivisions_gdf = gpd.read_file(SUBDIVISIONS_FILE)
            dev_gdf = gpd.read_file(DEV_SUITABILITY_FILE)

            # Ensure same CRS
            if dev_gdf.crs != subdivisions_gdf.crs:
                dev_gdf = dev_gdf.to_crs(subdivisions_gdf.crs)

            logger.info(f"Analyzing {len(subdivisions_gdf)} subdivisions...")

            # Count suitable areas in each subdivision
            subdivision_counts = []
            for idx, subdivision in subdivisions_gdf.iterrows():
                # Find all development areas that intersect with this subdivision
                intersecting = dev_gdf[dev_gdf.geometry.intersects(subdivision.geometry)]
                count = len(intersecting)

                subdivision_counts.append({
                    "osm_id": subdivision.get("osm_id", f"subdivision_{idx}"),
                    "count": count,
                    "geometry": subdivision.geometry,
                    "idx": idx
                })

            # Sort by count (descending) and get top 3
            sorted_subdivisions = sorted(subdivision_counts, key=lambda x: x["count"], reverse=True)
            top_3 = sorted_subdivisions[:3]

            logger.info(f"Top 3 subdivisions: {[s['count'] for s in top_3]}")

            # Get GeoJSON of top subdivision
            top_subdivision_idx = top_3[0]["idx"]
            top_subdivision_row = subdivisions_gdf.iloc[top_subdivision_idx]

            # Get all development areas in top subdivision
            top_dev_areas = dev_gdf[dev_gdf.geometry.intersects(top_subdivision_row.geometry)]
            top_geojson = json.loads(top_dev_areas.to_json())

            # Prepare ranking info
            ranking_info = []
            for i, subdivision in enumerate(top_3, 1):
                ranking_info.append({
                    "rank": i,
                    "subdivision_id": subdivision["osm_id"],
                    "suitable_areas_count": subdivision["count"],
                    "percentage": (subdivision["count"] / len(dev_gdf)) * 100
                })

            return {
                "success": True,
                "query_type": "development_by_subdivisions",
                "data": top_geojson,  # GeoJSON of top subdivision's suitable areas
                "top_subdivision": {
                    "osm_id": top_3[0]["osm_id"],
                    "suitable_areas": top_3[0]["count"],
                    "total_dev_areas": len(dev_gdf)
                },
                "ranking": ranking_info,
                "summary": f"""
                **Development Suitability Analysis by Subdivisions**

                Top Subdivisions for Development:
                1. Subdivision {top_3[0]['osm_id']}: {top_3[0]['count']:,} suitable areas ({(top_3[0]['count']/len(dev_gdf)*100):.1f}%)
                2. Subdivision {top_3[1]['osm_id']}: {top_3[1]['count']:,} suitable areas ({(top_3[1]['count']/len(dev_gdf)*100):.1f}%)
                3. Subdivision {top_3[2]['osm_id']}: {top_3[2]['count']:,} suitable areas ({(top_3[2]['count']/len(dev_gdf)*100):.1f}%)

                Map displays: Top subdivision with {top_3[0]['count']:,} development-suitable areas
                """
            }

        except Exception as e:
            logger.error(f"Error analyzing by subdivisions: {e}")
            return {"success": False, "error": str(e), "data": {}}


# Initialize handler
dem_handler = DEMQueryHandler()


# REST API Endpoints

@router.post("/query")
async def dem_query(question: str) -> Dict[str, Any]:
    """
    Process natural language DEM queries

    Examples:
    - "What is the terrain like in Berlin?"
    - "Show me the slope analysis"
    - "Which areas are suitable for development?"
    - "What are the flood risk areas?"
    - "Terrain classification"
    """
    question_lower = question.lower()

    # Exclude waterbodies queries - these are spatial queries, not DEM queries
    if "waterbodies" in question_lower or "water bodies" in question_lower:
        return {
            "success": False,
            "error": "Waterbodies queries should use spatial endpoints. Use /api/query for spatial analysis.",
            "data": {}
        }

    # Route to appropriate handler
    if any(word in question_lower for word in ["terrain", "elevation", "relief", "topography"]):
        result = dem_handler.handle_terrain_query(question)
    elif any(word in question_lower for word in ["slope", "steep", "steepness", "gradient"]):
        result = dem_handler.handle_slope_query(question)
    elif any(word in question_lower for word in ["develop", "suitable", "construction", "build"]):
        # Check if asking by subdivision/area
        if any(word in question_lower for word in ["subdivision", "area", "district", "which subdivision", "which area", "by area", "per area"]):
            result = dem_handler.analyze_development_by_subdivisions()
        else:
            result = dem_handler.handle_development_query(question)
    elif any(word in question_lower for word in ["flood", "risk", "drainage"]):
        # Only match flood/risk/drainage, but NOT just "water" or "waterbodies"
        result = dem_handler.handle_flood_risk_query(question)
    elif any(word in question_lower for word in ["classify", "classification"]):
        result = dem_handler.handle_classification_query(question)
    else:
        # Default to terrain analysis
        result = dem_handler.handle_terrain_query(question)

    return result


@router.get("/terrain-stats")
async def get_terrain_stats() -> Dict[str, Any]:
    """Get terrain statistics"""
    return dem_handler.handle_terrain_query("terrain statistics")


@router.get("/slope")
async def get_slope() -> Dict[str, Any]:
    """Get slope analysis"""
    return dem_handler.handle_slope_query("slope analysis")


@router.get("/development-suitability")
async def get_development() -> Dict[str, Any]:
    """Get development suitability areas"""
    return dem_handler.handle_development_query("development suitability")


@router.get("/development-by-subdivisions")
async def get_development_by_subdivisions() -> Dict[str, Any]:
    """Get development suitability areas ranked by subdivisions (small admin areas)

    Returns:
    - Ranking of top 3 subdivisions by suitable area count
    - GeoJSON of top subdivision's suitable areas for map display
    """
    return dem_handler.analyze_development_by_subdivisions()


@router.get("/flood-risk")
async def get_flood_risk() -> Dict[str, Any]:
    """Get flood risk assessment"""
    return dem_handler.handle_flood_risk_query("flood risk")


@router.get("/classification")
async def get_classification() -> Dict[str, Any]:
    """Get terrain classification"""
    return dem_handler.handle_classification_query("terrain classification")


@router.get("/available-files")
async def get_available_files() -> Dict[str, Any]:
    """List available DEM analysis files"""
    files = {}
    if DEMO_RESULTS.exists():
        for file in DEMO_RESULTS.glob("*"):
            files[file.name] = {
                "size_mb": file.stat().st_size / 1024 / 1024,
                "path": str(file)
            }

    return {
        "dem_available": DEM_FILE.exists(),
        "dem_path": str(DEM_FILE),
        "analysis_results": files
    }


@router.get("/info")
async def get_dem_info() -> Dict[str, Any]:
    """Get DEM information and capabilities"""
    return {
        "name": "Berlin Digital Elevation Model",
        "source": "Copernicus NASADEM via Microsoft Planetary Computer",
        "resolution": "30 meters",
        "coverage": "Berlin, Germany (13.08-13.76°E, 52.33-52.67°N)",
        "available": DEM_FILE.exists(),
        "capabilities": [
            "Terrain statistics (elevation, slope, relief)",
            "Slope analysis and mapping",
            "Terrain classification",
            "Development suitability analysis",
            "Flood risk assessment",
            "Aspect analysis",
            "Hillshade visualization"
        ],
        "query_examples": [
            "What is the terrain like in Berlin?",
            "Show me the slope analysis",
            "Which areas are suitable for development?",
            "What are the flood risk areas?",
            "Classify the terrain for me"
        ]
    }
