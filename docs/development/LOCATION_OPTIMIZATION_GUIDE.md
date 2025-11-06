# Location Optimization Tool Guide

## Overview

The **Location Optimization Tool** is a sophisticated geospatial analysis system that helps you find the best locations for opening new retail outlets in Berlin. It uses Multi-Criteria Decision Analysis (MCDA) to score potential locations based on multiple factors including competition, population proximity, transportation access, parking availability, and land use suitability.

## Features

### ✨ Core Capabilities

- **Competition Analysis**: Identifies areas with fewer existing competitors
- **Population Proximity**: Finds locations near residential areas with good foot traffic potential
- **Transportation Accessibility**: Prioritizes areas with good public transit access
- **Parking Availability**: Considers nearby parking facilities for customer convenience
- **Land Use Analysis**: Avoids unsuitable areas (water, parks, forests) and prefers developed zones

### 🎯 Supported Retail Types

- **Supermarket** (REWE, Edeka, Aldi, etc.)
- **Pharmacy**
- **Restaurant**
- **Bank**
- **Gym/Fitness Center**
- **Café**

## API Endpoints

### 1. Find Optimal Sites

**Endpoint**: `POST /api/location/find-optimal-sites`

Analyzes Berlin geography and recommends the best locations for a new retail outlet.

#### Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `retail_type` | string | supermarket | - | Type of outlet (supermarket, pharmacy, restaurant, bank, gym, cafe) |
| `analysis_radius` | integer | 1000 | 500-5000 | Analysis radius in meters around each potential location |
| `top_n` | integer | 10 | 5-50 | Number of top locations to return |
| `exclude_districts` | string | null | - | Comma-separated district names to exclude (e.g., "Spandau,Köpenick") |
| `grid_size` | integer | 500 | 250-1000 | Grid cell size in meters for analysis |

#### Example Requests

**Find top 15 supermarket locations:**
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=15&analysis_radius=1200"
```

**Find pharmacy locations excluding Spandau district:**
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=pharmacy&exclude_districts=Spandau&analysis_radius=1000"
```

**Find restaurant locations with 500m grid size:**
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=restaurant&grid_size=500&analysis_radius=800"
```

#### Response Format

```json
{
  "success": true,
  "query": {
    "retail_type": "supermarket",
    "analysis_radius": 1000,
    "top_n": 10,
    "exclude_districts": null,
    "grid_size": 500
  },
  "retail_type": "supermarket",
  "analysis_radius": 1000,
  "grid_size": 500,
  "total_locations_analyzed": 2847,
  "weights": {
    "competition": 0.25,
    "population": 0.30,
    "transport": 0.20,
    "parking": 0.15,
    "landuse": 0.10
  },
  "top_locations": [
    {
      "rank": 1,
      "latitude": 52.4531,
      "longitude": 13.4205,
      "overall_score": 92.45,
      "competition_score": 88.50,
      "population_score": 95.30,
      "transport_score": 85.60,
      "parking_score": 92.10,
      "landuse_score": 98.00,
      "geometry": {
        "type": "Point",
        "coordinates": [13.4205, 52.4531]
      }
    },
    {
      "rank": 2,
      "latitude": 52.4612,
      "longitude": 13.3945,
      "overall_score": 89.23,
      ...
    }
  ]
}
```

### 2. Get Suitability Scores

**Endpoint**: `GET /api/location/suitability-scores`

Get detailed suitability scores for a specific location.

#### Parameters

| Parameter | Type | Required | Range | Description |
|-----------|------|----------|-------|-------------|
| `latitude` | float | Yes | - | Latitude of location (WGS84) |
| `longitude` | float | Yes | - | Longitude of location (WGS84) |
| `retail_type` | string | No | - | Type of retail (default: supermarket) |
| `radius` | integer | No | 500-5000 | Analysis radius in meters |

#### Example Requests

**Analyze a specific supermarket location:**
```bash
curl -X GET "http://localhost:8000/api/location/suitability-scores?latitude=52.52&longitude=13.40&retail_type=supermarket&radius=1000"
```

**Analyze a pharmacy location:**
```bash
curl -X GET "http://localhost:8000/api/location/suitability-scores?latitude=52.51&longitude=13.42&retail_type=pharmacy&radius=1200"
```

#### Response Format

```json
{
  "success": true,
  "location": {
    "latitude": 52.52,
    "longitude": 13.40,
    "retail_type": "supermarket"
  },
  "analysis_radius": 1000,
  "scores": {
    "competition": 78.50,
    "population": 89.20,
    "transportation": 92.30,
    "parking": 76.50,
    "land_use": 95.00,
    "overall": 86.30
  },
  "interpretation": {
    "0-25": "Poor suitability",
    "25-50": "Moderate suitability",
    "50-75": "Good suitability",
    "75-100": "Excellent suitability"
  }
}
```

### 3. Get Supported Retail Types

**Endpoint**: `GET /api/location/retail-types`

Lists all supported retail outlet types.

#### Example Request
```bash
curl -X GET "http://localhost:8000/api/location/retail-types"
```

#### Response
```json
{
  "success": true,
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
```

### 4. Get Methodology

**Endpoint**: `GET /api/location/methodology`

Detailed explanation of the scoring methodology and how each criterion is calculated.

#### Example Request
```bash
curl -X GET "http://localhost:8000/api/location/methodology"
```

## Scoring System

### Overall Score Calculation

The tool calculates an **Overall Suitability Score** (0-100) using a weighted combination of five criteria:

```
Overall Score =
  (0.25 × Competition Score) +
  (0.30 × Population Score) +
  (0.20 × Transportation Score) +
  (0.15 × Parking Score) +
  (0.10 × Land Use Score)
```

### Individual Criteria

#### 1. Competition Score (Weight: 25%)
- **Measures**: Distance from existing competitors
- **Scoring**: Higher distance from competitors = higher score
- **Rationale**: Reduces market saturation and cannibalization
- **Range**: 0-100

#### 2. Population Score (Weight: 30%)
- **Measures**: Proximity to residential areas and population density
- **Scoring**: More residential areas nearby = higher score
- **Rationale**: More potential foot traffic and customer accessibility
- **Range**: 0-100

#### 3. Transportation Score (Weight: 20%)
- **Measures**: Access to public transit (bus, tram, train stops)
- **Scoring**: More transit stops nearby = higher score
- **Rationale**: Better customer accessibility via public transportation
- **Range**: 0-100

#### 4. Parking Score (Weight: 15%)
- **Measures**: Availability of parking facilities in the area
- **Scoring**: More parking spaces = higher score
- **Rationale**: Convenience for customers arriving by car
- **Range**: 0-100

#### 5. Land Use Score (Weight: 10%)
- **Measures**: Suitability of land use type
- **Scoring**: Developed areas preferred; water, parks, forests avoided
- **Rationale**: Ensures location is suitable for commercial development
- **Range**: 0-100

## Use Cases

### Use Case 1: Finding the Best Location for a New REWE Supermarket

You want to open a new REWE supermarket in Berlin and need to identify the top 5 optimal locations.

```bash
# Step 1: Get top 5 locations with detailed scoring
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=5&analysis_radius=1200"

# Step 2: For each recommended location, get more detailed suitability analysis
# (for the #1 recommended location)
curl -X GET "http://localhost:8000/api/location/suitability-scores?latitude=52.4531&longitude=13.4205&retail_type=supermarket"

# Step 3: Cross-reference with the methodology to understand why each location scores well
curl -X GET "http://localhost:8000/api/location/methodology"
```

### Use Case 2: Analyzing Specific Berlin Districts

You want to find optimal pharmacy locations, but prefer to avoid certain districts.

```bash
# Find top 10 pharmacy locations, excluding Spandau and Köpenick
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=pharmacy&top_n=10&exclude_districts=Spandau,Köpenick&analysis_radius=1000"
```

### Use Case 3: Fine-Tuning Analysis Parameters

You want to do a detailed analysis with a smaller grid size for higher precision.

```bash
# Use 250m grid cells for more detailed analysis
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=restaurant&grid_size=250&top_n=20&analysis_radius=1500"
```

## Interpreting Results

### Score Ranges

| Overall Score | Interpretation | Recommendation |
|---|---|---|
| **75-100** | Excellent suitability | Prime location, strongly recommended |
| **50-75** | Good suitability | Viable location, consider further |
| **25-50** | Moderate suitability | May work with optimizations |
| **0-25** | Poor suitability | Not recommended |

### Understanding Individual Scores

When analyzing a specific location, look at each criterion:

- **High competition, high population, high transport**: Competitive market but good customer base
- **Low competition, high population, high transport**: Ideal location (underserved market with good access)
- **Low competition, low population, low transport**: Niche market, limited growth potential
- **High competition, low population, high transport**: Saturated market in less accessible area

## Implementation Details

### Database Integration

The tool uses the following PostGIS tables:
- `vector.osm_supermarkets` - Existing supermarkets
- `vector.osm_pharmacies` - Existing pharmacies
- `vector.osm_restaurants` - Existing restaurants
- `vector.osm_banks` - Existing banks
- `vector.osm_gyms` - Existing gyms
- `vector.osm_transport_stops` - Public transit stops
- `vector.osm_parking` - Parking facilities
- `vector.osm_landuse` - Land use classification
- `vector.berlin_districts` - District boundaries

### Grid-Based Analysis

The tool uses a regular grid overlay on Berlin:
- Default grid cell size: 500m
- Each grid point is scored independently
- Analysis radius can be adjusted (default: 1000m)
- Results are ranked by overall score

### Performance Considerations

- **Grid size**: Smaller grids = more precision but slower analysis
- **Analysis radius**: Larger radius = more context but slower calculations
- **Data coverage**: Results depend on completeness of underlying datasets

## Extending the Tool

### Adding New Retail Types

Edit `app/utils/location_optimizer.py` and update the `retail_mapping` dictionary:

```python
retail_mapping = {
    "supermarket": "osm_supermarkets",
    "pharmacy": "osm_pharmacies",
    "restaurant": "osm_restaurants",
    "bank": "osm_banks",
    "gym": "osm_gyms",
    "cafe": "osm_restaurants",
    "your_type": "your_table_name"  # Add new type here
}
```

### Adjusting Weights

Edit the `WEIGHTS` dictionary in `LocationOptimizer` class:

```python
WEIGHTS = {
    "competition": 0.25,      # Adjust these values
    "population": 0.30,
    "transport": 0.20,
    "parking": 0.15,
    "landuse": 0.10
}
```

## Technical Architecture

```
Frontend/Client
    ↓
/api/location/find-optimal-sites
    ↓
LocationOptimizer.analyze_retail_location()
    ↓
_create_analysis_grid() → Regular grid across Berlin
    ↓
_score_locations() → Score each grid point on 5 criteria
    ↓
PostGIS Database
├── Load competitor data (osm_supermarkets, etc.)
├── Load transport data (osm_transport_stops)
├── Load parking data (osm_parking)
└── Load land use data (osm_landuse)
    ↓
Normalize scores (0-100)
    ↓
Calculate weighted overall score
    ↓
Rank results
    ↓
Return top N locations with detailed breakdown
```

## Future Enhancements

- [ ] Visualization of heatmaps showing suitability across Berlin
- [ ] Time-of-day foot traffic analysis
- [ ] Demographic data integration (age groups, income levels)
- [ ] Seasonal demand analysis
- [ ] Integration with local zoning regulations
- [ ] Commercial rent price analysis
- [ ] Accessibility analysis for disabled customers
- [ ] Export results as GeoJSON, CSV, or PDF reports

## Troubleshooting

### Issue: "No results found"
- Ensure database connection is working
- Check that necessary tables exist in PostGIS
- Verify exclude_districts match actual district names

### Issue: All locations have low scores
- Increase analysis_radius parameter
- Check if land use data is comprehensive
- Verify that competitor data is loaded

### Issue: Results seem biased toward city center
- This is expected! City centers typically have better accessibility
- Use exclude_districts to explore other areas
- Adjust WEIGHTS to prioritize different criteria

## API Documentation

Full interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Examples

See the complete examples in the [Examples](/LOCATION_EXAMPLES.md) file.

---

**Last Updated**: 2025-11-03
**Version**: 1.0.0
