"""
Location Suitability Analysis Routes
Provides endpoints for finding optimal retail locations based on multiple criteria.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
import logging
from app.utils.location_optimizer import location_optimizer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/location",
    tags=["location-analysis"],
    responses={404: {"description": "Not found"}}
)


@router.post("/find-optimal-sites")
async def find_optimal_sites(
    retail_type: str = Query(
        "supermarket",
        description="Type of retail outlet (supermarket, pharmacy, restaurant, bank, gym, cafe)"
    ),
    analysis_radius: int = Query(
        1000,
        ge=500,
        le=5000,
        description="Analysis radius in meters around each potential location"
    ),
    top_n: int = Query(
        10,
        ge=5,
        le=50,
        description="Number of top locations to return"
    ),
    exclude_districts: Optional[str] = Query(
        None,
        description="Comma-separated list of district names to exclude"
    ),
    grid_size: int = Query(
        500,
        ge=250,
        le=1000,
        description="Grid cell size in meters"
    )
):
    """
    Find optimal locations for a new retail outlet.

    This endpoint analyzes Berlin geography to recommend the best sites for a new
    retail business. It uses multi-criteria decision analysis (MCDA) considering:

    - **Competition**: Distance to existing competitors (higher distance = better)
    - **Population**: Proximity to residential areas and population density
    - **Transportation**: Access to public transit stops
    - **Parking**: Availability of nearby parking facilities
    - **Land Use**: Suitability (avoids water, forests, parks)

    Example request:
    ```
    POST /api/location/find-optimal-sites?retail_type=supermarket&analysis_radius=1000&top_n=10
    ```

    Returns the top N recommended locations with individual criterion scores (0-100)
    and an overall suitability score.
    """
    try:
        # Parse exclude_districts
        exclude_areas = None
        if exclude_districts:
            exclude_areas = [d.strip() for d in exclude_districts.split(",")]

        # Create a new optimizer with custom grid size
        optimizer = location_optimizer.__class__(grid_size=grid_size)

        # Run analysis
        result = optimizer.analyze_retail_location(
            retail_type=retail_type.lower(),
            radius=analysis_radius,
            top_n=top_n,
            exclude_areas=exclude_areas
        )

        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Analysis failed")
            )

        return {
            "success": True,
            "query": {
                "retail_type": retail_type,
                "analysis_radius": analysis_radius,
                "top_n": top_n,
                "exclude_districts": exclude_areas,
                "grid_size": grid_size
            },
            **result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in location analysis: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Location analysis failed: {str(e)}"
        )


@router.get("/suitability-scores")
async def get_suitability_scores(
    latitude: float = Query(..., description="Latitude of location"),
    longitude: float = Query(..., description="Longitude of location"),
    retail_type: str = Query("supermarket", description="Type of retail outlet"),
    radius: int = Query(1000, ge=500, le=5000, description="Analysis radius in meters")
):
    """
    Get suitability scores for a specific location.

    Returns detailed scoring breakdown for a given coordinate:
    - Competition score
    - Population score
    - Transportation score
    - Parking score
    - Land use score
    - Overall suitability score

    Each score ranges from 0-100 where 100 is optimal.
    """
    try:
        from shapely.geometry import Point
        from shapely.geometry import box

        # Create point and buffer
        point = Point(longitude, latitude)
        radius_degrees = radius / 111000
        buffer = point.buffer(radius_degrees)

        # Score the location
        competition = optimizer._score_competition(buffer)
        population = optimizer._score_population(buffer)
        transport = optimizer._score_transport(buffer)
        parking = optimizer._score_parking(buffer)
        landuse = optimizer._score_landuse(buffer)

        # Normalize scores to 0-100
        def normalize(score):
            return round(score * 100, 2)

        overall = (
            optimizer.WEIGHTS["competition"] * competition +
            optimizer.WEIGHTS["population"] * population +
            optimizer.WEIGHTS["transport"] * transport +
            optimizer.WEIGHTS["parking"] * parking +
            optimizer.WEIGHTS["landuse"] * landuse
        )

        return {
            "success": True,
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "retail_type": retail_type
            },
            "analysis_radius": radius,
            "scores": {
                "competition": normalize(competition),
                "population": normalize(population),
                "transportation": normalize(transport),
                "parking": normalize(parking),
                "land_use": normalize(landuse),
                "overall": normalize(overall)
            },
            "interpretation": {
                "0-25": "Poor suitability",
                "25-50": "Moderate suitability",
                "50-75": "Good suitability",
                "75-100": "Excellent suitability"
            }
        }

    except Exception as e:
        logger.error(f"Error getting suitability scores: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Suitability analysis failed: {str(e)}"
        )


@router.get("/retail-types")
async def get_supported_retail_types():
    """
    Get list of supported retail outlet types.

    Returns the retail types that can be analyzed with the location optimizer.
    """
    return {
        "success": True,
        "supported_types": [
            "supermarket",
            "pharmacy",
            "restaurant",
            "bank",
            "gym",
            "cafe"
        ],
        "description": "Each type uses real existing outlets as competitors for analysis"
    }


@router.get("/methodology")
async def get_methodology():
    """
    Get detailed explanation of the location optimization methodology.

    Returns information about:
    - Scoring criteria
    - Weights used
    - How each score is calculated
    """
    return {
        "success": True,
        "methodology": {
            "title": "Multi-Criteria Decision Analysis (MCDA) for Location Optimization",
            "criteria": {
                "competition": {
                    "weight": optimizer.WEIGHTS["competition"],
                    "description": "Distance to nearest competitor",
                    "scoring": "Higher distance from competitors = higher score",
                    "range": "0-100"
                },
                "population": {
                    "weight": optimizer.WEIGHTS["population"],
                    "description": "Proximity to residential areas and population density",
                    "scoring": "Areas with more residential zones nearby = higher score",
                    "range": "0-100"
                },
                "transportation": {
                    "weight": optimizer.WEIGHTS["transport"],
                    "description": "Access to public transportation",
                    "scoring": "More public transit stops nearby = higher score",
                    "range": "0-100"
                },
                "parking": {
                    "weight": optimizer.WEIGHTS["parking"],
                    "description": "Availability of parking facilities",
                    "scoring": "More parking spaces nearby = higher score",
                    "range": "0-100"
                },
                "land_use": {
                    "weight": optimizer.WEIGHTS["landuse"],
                    "description": "Land use suitability",
                    "scoring": "Avoids water, forests, and parks; prefers developed areas",
                    "range": "0-100"
                }
            },
            "overall_score": "Weighted sum of all criteria",
            "how_to_use": [
                "1. Call /api/location/find-optimal-sites with desired parameters",
                "2. Specify retail_type (supermarket, pharmacy, etc.)",
                "3. Receive ranked list of optimal locations",
                "4. Use /api/location/suitability-scores for detailed analysis of specific sites"
            ]
        }
    }
