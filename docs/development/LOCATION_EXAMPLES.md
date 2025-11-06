# Location Optimization Tool - Practical Examples

## Real-World Use Cases

### Example 1: REWE Supermarket Location Analysis

**Scenario**: A REWE executive wants to identify the top 10 locations for opening a new supermarket in Berlin, with preference for avoiding areas with existing heavy competition.

**Steps**:

1. **Get optimal locations**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "supermarket",
    "analysis_radius": 1200,
    "top_n": 10,
    "exclude_districts": null,
    "grid_size": 500
  }' | jq '.'
```

2. **Analyze the top recommended location in detail**:
```bash
curl -X GET "http://localhost:8000/api/location/suitability-scores" \
  --data-urlencode "latitude=52.4531" \
  --data-urlencode "longitude=13.4205" \
  --data-urlencode "retail_type=supermarket" \
  --data-urlencode "radius=1200" | jq '.'
```

**Expected Response**:
- Top locations with scores around 85-95 (excellent suitability)
- High population score (close to residential areas)
- Good transportation and parking scores
- Low competition in those areas

**Next Steps**:
- Visit the recommended locations
- Check local zoning regulations
- Evaluate commercial real estate availability
- Compare with EDEKA and ALDI locations

---

### Example 2: Pharmacy Network Expansion

**Scenario**: A pharmacy chain wants to find 5-7 locations for new pharmacies, but wants to exclude outer districts and focus on main city areas.

**Steps**:

1. **Get optimal pharmacy locations**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "pharmacy",
    "analysis_radius": 1000,
    "top_n": 7,
    "exclude_districts": "Spandau,Köpenick,Marzahn-Hellersdorf,Lichtenberg",
    "grid_size": 500
  }' | jq '.top_locations'
```

2. **Map scores for comparison**:
```bash
# Extract coordinates and scores
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=pharmacy&top_n=7&exclude_districts=Spandau,Köpenick,Marzahn-Hellersdorf,Lichtenberg" \
  | jq '.top_locations[] | {rank: .rank, lat: .latitude, lon: .longitude, score: .overall_score}'
```

**Interpretation**:
- Pharmacies have slightly different suitability patterns than supermarkets
- Population score will be high (pharmacies in busy areas)
- Transportation should be excellent (people walk to pharmacies)
- Competition matters (don't oversaturate an area)

---

### Example 3: Restaurant Location for Startup

**Scenario**: A startup wants to open 3 mid-range restaurants in Berlin and wants to:
- Explore different areas thoroughly (smaller grid)
- Focus on neighborhoods with good nightlife
- Avoid very central, competitive areas

**Steps**:

1. **Find diverse location options**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "restaurant",
    "analysis_radius": 800,
    "top_n": 15,
    "grid_size": 250,
    "exclude_districts": null
  }' | jq '.top_locations[] | select(.rank <= 5) | {rank, lat: .latitude, lon: .longitude, pop: .population_score, trans: .transport_score, comp: .competition_score}'
```

2. **Deep-dive analysis on top 3 locations**:
```bash
# For each location:
curl -X GET "http://localhost:8000/api/location/suitability-scores?latitude=52.52&longitude=13.41&retail_type=restaurant&radius=800" \
  | jq '.scores'
```

**What to Look For in Restaurants**:
- **High population score**: Walkable neighborhoods with foot traffic
- **High transportation score**: Easy to reach by public transit
- **Moderate competition score**: Some other restaurants nearby is OK (validates demand)
- **Good parking**: Customers arriving by car

---

### Example 4: Fitness Center / Gym Network

**Scenario**: A gym chain wants to expand and find 8-10 locations across Berlin's residential areas, avoiding central districts.

**Steps**:

1. **Find residential gym-friendly locations**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "gym",
    "analysis_radius": 1500,
    "top_n": 10,
    "exclude_districts": "Mitte,Charlottenburg-Wilmersdorf,Kreuzberg,Friedrichshain-Kreuzberg"
  }' > gym_locations.json
```

2. **Analyze top recommendations**:
```bash
jq '.top_locations[] | {rank, location: (.latitude | tostring) + "," + (.longitude | tostring), overall: .overall_score, pop: .population_score, comp: .competition_score}' gym_locations.json
```

**Key Metrics for Gyms**:
- **Very high population score**: Located in residential neighborhoods
- **Good transport access**: Commuters need to reach the gym
- **Moderate-to-high parking**: Many customers drive to gyms
- **Lower weight on competition**: Multiple gyms in area is OK

---

### Example 5: Bank Branch Strategy

**Scenario**: A bank wants to optimize its branch network with:
- 5 new branches in underserved areas
- Minimum 2km from existing branches
- Focus on areas with good public transport

**Steps**:

1. **Find strategic bank locations**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "bank",
    "analysis_radius": 2000,
    "top_n": 10,
    "grid_size": 750
  }' | jq '.top_locations[] | {rank, lat: .latitude, lon: .longitude, overall: .overall_score, transport: .transport_score, comp: .competition_score}'
```

2. **Export results for GIS analysis**:
```bash
# Create GeoJSON from results
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=bank&top_n=10" \
  | jq '{type: "FeatureCollection", features: .top_locations[] | {type: "Feature", geometry: .geometry, properties: {rank: .rank, score: .overall_score}}}'
```

**Bank-Specific Considerations**:
- **High transportation**: People don't drive to banks for routine transactions
- **Moderate population**: Banks serve broader areas than foot traffic
- **High land use score**: Banks need proper commercial space
- **Competition less critical**: Banks aren't as density-sensitive as other retail

---

### Example 6: Market Research - Competitive Analysis

**Scenario**: A retail analyst wants to understand market saturation and competition across different neighborhoods.

**Steps**:

1. **Generate heatmap data for supermarkets**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=50&grid_size=500" \
  | jq '.top_locations[] | {lat: .latitude, lon: .longitude, comp: .competition_score}' \
  | jq -s 'sort_by(.comp) | reverse | .[:10]' \
  > low_competition_areas.json
```

2. **Analyze which neighborhoods are underserved**:
```bash
# Neighborhoods with high population but low competition = opportunity
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=50" \
  | jq '.top_locations[] | select(.population_score > 80 and .competition_score < 40) | {lat: .latitude, lon: .longitude, pop: .population_score, comp: .competition_score, overall: .overall_score}'
```

**Market Insights**:
- Compare competition_score across locations
- High population + low competition = Market gap
- High transport + low parking = Underinvested area

---

### Example 7: Café Growth Strategy

**Scenario**: A café chain wants to add 5 new locations and is willing to accept some competition (cafés cluster naturally).

**Steps**:

1. **Get top café locations**:
```bash
curl -X POST "http://localhost:8000/api/location/find-optimal-sites" \
  -H "Content-Type: application/json" \
  --data '{
    "retail_type": "cafe",
    "analysis_radius": 800,
    "top_n": 5,
    "grid_size": 400
  }' | jq '.top_locations[] | {rank, location: "\(.latitude),\(.longitude)", overall: .overall_score, transport: .transport_score, population: .population_score}'
```

2. **Focus on high-traffic areas**:
```bash
# Prioritize locations with excellent transport and population
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=cafe&top_n=5&analysis_radius=800" \
  | jq '.top_locations[] | select(.transport_score > 85 and .population_score > 85)'
```

**Café Market Dynamics**:
- Prefers pedestrian-heavy areas (high population + transport)
- Competition is good (validates demand)
- Parking less critical (people walk to cafés)
- Land use flexibility (can adapt existing spaces)

---

## Advanced Usage

### Batch Analysis Across Multiple Retail Types

Create a shell script to analyze all retail types:

```bash
#!/bin/bash

# Array of retail types to analyze
retail_types=("supermarket" "pharmacy" "restaurant" "bank" "gym" "cafe")

for retail in "${retail_types[@]}"; do
  echo "Analyzing $retail..."
  curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=$retail&top_n=5" \
    | jq '.top_locations[] | {rank, type: "'$retail'", lat: .latitude, lon: .longitude, score: .overall_score}' \
    >> all_locations.json
done

# Create consolidated output
jq -s '.' all_locations.json > all_locations_consolidated.json
```

### Generate Geographic Visualizations

Convert API results to mapping format:

```bash
# Create GeoJSON for Leaflet visualization
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=20" \
  | jq '{
    type: "FeatureCollection",
    features: [
      .top_locations[] | {
        type: "Feature",
        geometry: .geometry,
        properties: {
          rank: .rank,
          overall_score: .overall_score,
          competition: .competition_score,
          population: .population_score,
          transport: .transport_score,
          parking: .parking_score,
          landuse: .landuse_score
        }
      }
    ]
  }' > supermarket_locations.geojson
```

Then load in web GIS or mapping tool for visualization.

### Statistical Analysis

```bash
# Get summary statistics
curl -X POST "http://localhost:8000/api/location/find-optimal-sites?retail_type=supermarket&top_n=30" \
  | jq '
  [.top_locations[].overall_score] |
  {
    count: length,
    min: min,
    max: max,
    avg: (add / length),
    median: sort[length/2]
  }'
```

---

## Integration Examples

### Python Integration

```python
import requests
import json

def find_best_retail_location(retail_type, top_n=10):
    """Find optimal retail locations using the API"""

    url = "http://localhost:8000/api/location/find-optimal-sites"
    params = {
        "retail_type": retail_type,
        "top_n": top_n,
        "analysis_radius": 1000
    }

    response = requests.post(url, params=params)
    data = response.json()

    if data['success']:
        return data['top_locations']
    else:
        raise Exception(data.get('error', 'Analysis failed'))

# Usage
supermarket_locations = find_best_retail_location("supermarket", top_n=10)
for loc in supermarket_locations:
    print(f"Rank {loc['rank']}: {loc['latitude']}, {loc['longitude']} (Score: {loc['overall_score']})")
```

### JavaScript Integration

```javascript
async function findOptimalLocations(retailType, topN = 10) {
  const url = new URL('http://localhost:8000/api/location/find-optimal-sites');
  url.searchParams.append('retail_type', retailType);
  url.searchParams.append('top_n', topN);

  const response = await fetch(url, { method: 'POST' });
  const data = await response.json();

  if (data.success) {
    return data.top_locations;
  } else {
    throw new Error(data.error);
  }
}

// Usage
const locations = await findOptimalLocations('pharmacy', 5);
locations.forEach(loc => {
  console.log(`Rank ${loc.rank}: (${loc.latitude}, ${loc.longitude}) - Score: ${loc.overall_score}`);
});
```

---

## Tips and Best Practices

1. **Start Broad, Then Narrow**: Begin with larger grid sizes and analysis radii, then refine
2. **Cross-Validate Results**: Check multiple retail types to understand area characteristics
3. **Combine with Domain Knowledge**: API scores are data-driven, not ground truth
4. **Consider Local Regulations**: Check zoning and building codes before committing
5. **Visit Sites in Person**: Always verify recommendations on the ground
6. **Monitor Competitors**: Track competitor locations over time
7. **Think Long-term**: Consider future development and demographic shifts
8. **Test Exclude Districts**: Understand why certain areas score lower

---

**For More Information**: See [LOCATION_OPTIMIZATION_GUIDE.md](LOCATION_OPTIMIZATION_GUIDE.md)
