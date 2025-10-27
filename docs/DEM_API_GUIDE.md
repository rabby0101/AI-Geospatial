# DEM API Integration Guide

Complete guide to querying Berlin DEM data through the Cognitive Geospatial Assistant API.

## Quick Start

### 1. Make Sure DEM is Downloaded

```bash
python scripts/download_berlin_dem.py
```

### 2. Start the API Server

```bash
python app/main.py
# or
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Ask DEM Questions

```bash
# Via curl
curl -X POST "http://localhost:8000/api/dem/query?question=What%20is%20the%20terrain%20like%20in%20Berlin?"

# Or test with Python script
python test_dem_api.py
```

## API Endpoints

### Query Endpoint (Natural Language)

```
POST /api/dem/query?question=<your-question>
```

**Description**: Process natural language questions about DEM

**Parameters**:
- `question` (string): Natural language question about terrain/DEM

**Example Queries**:
```
"What is the terrain like in Berlin?"
"Show me the slope analysis"
"Which areas are suitable for development?"
"What are the flood risk areas?"
"Classify the terrain for me"
```

**Response**:
```json
{
  "success": true,
  "query_type": "terrain_analysis",
  "data": {
    "elevation": {
      "min": -49.9,
      "max": 193.9,
      "mean": 58.2,
      "std": 20.8
    },
    "slope": {
      "min": 0.0,
      "max": 88.5,
      "mean": 47.8,
      "std": 24.7
    },
    "relief": 243.8
  },
  "summary": "<formatted text>"
}
```

### Direct Endpoints

#### Get Terrain Statistics

```
GET /api/dem/terrain-stats
POST /api/dem/query?question=terrain%20statistics
```

Returns elevation and slope statistics for Berlin.

#### Get Slope Analysis

```
GET /api/dem/slope
POST /api/dem/query?question=slope%20analysis
```

Returns slope analysis with steepness classification.

#### Get Development Suitability

```
GET /api/dem/development-suitability
POST /api/dem/query?question=development%20suitability
```

Returns areas suitable for development (slope ≤ 20°).
- Currently finds **285,083 suitable areas**

#### Get Flood Risk

```
GET /api/dem/flood-risk
POST /api/dem/query?question=flood%20risk
```

Returns flood-prone areas. Requires full analysis to be run.

#### Get Terrain Classification

```
GET /api/dem/classification
POST /api/dem/query?question=terrain%20classification
```

Returns terrain classified into:
- 1: Flat (0-5°)
- 2: Rolling (5-15°)
- 3: Steep (15-30°)
- 4: Very Steep (30°+)

#### Get Available Files

```
GET /api/dem/available-files
```

Lists all generated DEM analysis files.

**Response**:
```json
{
  "dem_available": true,
  "dem_path": "data/raster/dem/berlin_dem.tif",
  "analysis_results": {
    "berlin_slope.tif": {"size_mb": 22.0},
    "berlin_aspect.tif": {"size_mb": 36.0},
    ...
  }
}
```

#### Get DEM Information

```
GET /api/dem/info
```

Returns general information about DEM capabilities.

**Response**:
```json
{
  "name": "Berlin Digital Elevation Model",
  "source": "Copernicus NASADEM",
  "resolution": "30 meters",
  "coverage": "Berlin, Germany",
  "available": true,
  "capabilities": [
    "Terrain statistics",
    "Slope analysis",
    "Terrain classification",
    "Development suitability",
    "Flood risk assessment",
    ...
  ]
}
```

## Usage Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8000/api/dem"

# Example 1: Get terrain statistics
response = requests.get(f"{BASE_URL}/terrain-stats").json()
print(f"Average elevation: {response['data']['elevation']['mean']} m")

# Example 2: Query with natural language
response = requests.post(
    f"{BASE_URL}/query",
    params={"question": "Which areas are suitable for development?"}
).json()
print(response['summary'])

# Example 3: Get DEM info
response = requests.get(f"{BASE_URL}/info").json()
print(f"DEM Resolution: {response['resolution']}")
```

### cURL

```bash
# Get terrain statistics
curl http://localhost:8000/api/dem/terrain-stats

# Query with natural language
curl "http://localhost:8000/api/dem/query?question=What%20is%20the%20average%20slope?"

# Get DEM info
curl http://localhost:8000/api/dem/info
```

### JavaScript/Frontend

```javascript
// Query DEM endpoint
async function queryDEM(question) {
  const response = await fetch(
    `http://localhost:8000/api/dem/query?question=${encodeURIComponent(question)}`,
    { method: 'POST' }
  );
  return await response.json();
}

// Example usage
const result = await queryDEM("What areas are suitable for development?");
console.log(result.summary);
```

## Query Examples

### Terrain Analysis
```
"What is the terrain like in Berlin?"
"Show elevation range"
"What is the relief of Berlin?"
"Terrain analysis"
```

### Slope Analysis
```
"Show me the slope analysis"
"What are the steepest areas?"
"Slope gradient analysis"
"Terrain slope"
```

### Development Planning
```
"Which areas are suitable for development?"
"Show developable land"
"Where can we build?"
"Development suitability analysis"
```

### Flood Risk
```
"What are the flood risk areas?"
"Show flood-prone regions"
"Flood risk assessment"
```

### Terrain Classification
```
"Classify the terrain"
"Terrain classification"
"How is the terrain classified?"
```

## Response Format

### Success Response

```json
{
  "success": true,
  "query_type": "terrain_analysis|slope_analysis|development_suitability|flood_risk|terrain_classification",
  "data": {
    // Type-specific data
  },
  "summary": "Human-readable summary"
}
```

### Error Response

```json
{
  "success": false,
  "error": "Error message describing what went wrong",
  "data": {}
}
```

## Available Data

### Terrain Statistics
- **Elevation**: min, max, mean, std (meters)
- **Slope**: min, max, mean, std (degrees)
- **Relief**: max - min elevation (meters)

### Slope Analysis
- Slope steepness in degrees
- Classifications: flat, rolling, steep, very steep

### Development Suitability
- 285,083 suitable areas (slope ≤ 20°)
- GeoJSON vector polygons
- Suitable for construction and urban development

### Terrain Classification
- Flat (0-5°): Suitable for development
- Rolling (5-15°): Moderate constraints
- Steep (15-30°): Limited development
- Very Steep (30°+): Challenging for development

## Integration with UI

### Dashboard Integration

Add to your HTML dashboard:

```html
<!-- DEM Query Widget -->
<div id="dem-query" class="widget">
  <h3>DEM Analysis</h3>
  <input type="text" id="dem-question" placeholder="Ask about terrain...">
  <button onclick="queryDEM()">Analyze</button>
  <div id="dem-result"></div>
</div>

<script>
async function queryDEM() {
  const question = document.getElementById('dem-question').value;
  const response = await fetch(
    `/api/dem/query?question=${encodeURIComponent(question)}`,
    { method: 'POST' }
  );
  const result = await response.json();
  document.getElementById('dem-result').innerHTML = result.summary;
}
</script>
```

## Testing

### Run Test Suite

```bash
python test_dem_api.py
```

This will test all endpoints and show example queries.

## Performance

- **Terrain Statistics**: <100ms
- **Slope Analysis**: <100ms
- **Development Suitability**: <500ms
- **Classification**: <100ms
- **Flood Risk**: Requires precomputed data

## Troubleshooting

### "DEM not available"
- Ensure `data/raster/dem/berlin_dem.tif` exists
- Run: `python scripts/download_berlin_dem.py`

### "API not running"
- Start API: `python app/main.py`
- Check port 8000 is available

### "No suitable areas found"
- Run demo first: `python scripts/demo_berlin_dem_simple.py`
- Adjust slope threshold in `app/routes/dem_query.py`

### Slow responses
- First query computes on-demand
- Results are cached in memory
- Run analysis pipeline for persistent results

## Advanced Usage

### Custom Slope Threshold

Edit `app/routes/dem_query.py`:

```python
def handle_development_query(self, query: str):
    # Change max_slope parameter
    dev_gdf = self.analyzer.analyze_development_suitability(max_slope=15.0)
```

### Add Custom Query Handler

```python
def handle_custom_query(self, query: str):
    if "custom" in query.lower():
        return {
            "success": True,
            "query_type": "custom",
            "data": {},
            "summary": "Custom analysis"
        }
```

## Related Files

- **API Route**: `app/routes/dem_query.py`
- **DEM Analysis Module**: `app/utils/dem_analysis.py`
- **Main App**: `app/main.py`
- **Test Script**: `test_dem_api.py`
- **Documentation**: `docs/DEM_ANALYSIS_GUIDE.md`

## Support

For issues or questions:
1. Check `test_dem_api.py` for working examples
2. Review `docs/DEM_ANALYSIS_GUIDE.md` for analysis details
3. Check API logs for error messages
4. Verify DEM file exists and is valid

---

**Last Updated**: 2024
**API Version**: 1.0
**DEM Source**: Copernicus NASADEM (30m resolution)
