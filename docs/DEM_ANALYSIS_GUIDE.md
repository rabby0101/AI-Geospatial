# Berlin DEM Analysis Guide

Complete guide for downloading, analyzing, and visualizing Digital Elevation Model (DEM) data for Berlin using Copernicus NASADEM.

## Overview

This guide covers:
- **Terrain Analysis**: Slope, aspect, hillshade, terrain classification
- **Hydrological Analysis**: Flow direction, flow accumulation, stream networks, watersheds
- **Urban Planning Analysis**: Flood risk assessment, development suitability

## Quick Start

### 1. Download Berlin DEM

```bash
python scripts/download_berlin_dem.py
```

This downloads Copernicus NASADEM (30m resolution) for the Berlin area via Microsoft Planetary Computer.

**Output**: `data/raster/dem/berlin_dem.tif`

### 2. Run Comprehensive Analysis

```bash
python scripts/analyze_berlin_dem.py
```

This performs all terrain, hydrological, and urban planning analyses.

**Outputs**: `data/raster/dem/analysis_results/`
- Terrain derivatives (slope, aspect, hillshade)
- Hydrological features (flow direction, flow accumulation, streams, watersheds)
- Urban planning analyses (flood risk, development suitability)

### 3. Generate Visualizations

```bash
python scripts/visualize_dem_analysis.py
```

Creates publication-ready maps and visualizations of all analyses.

**Outputs**: `data/raster/dem/analysis_results/visualizations/`

## Detailed Analysis Breakdown

### Terrain Analysis

#### Slope
- **What**: Steepness of terrain in degrees (0-90°)
- **Use**: Urban planning, erosion risk, infrastructure design
- **Output**: `berlin_slope.tif`

#### Aspect
- **What**: Direction of terrain slopes (0-360°, where 0°=N, 90°=E, etc.)
- **Use**: Solar radiation modeling, vegetation analysis, microclimate assessment
- **Output**: `berlin_aspect.tif`

#### Hillshade
- **What**: Shaded relief visualization (0-255 grayscale)
- **Use**: Visual interpretation, 3D-like representation
- **Output**: `berlin_hillshade.tif`

#### Terrain Classification
- **What**: Categorical classification of terrain type
  - 1 = Flat (slope < 5°)
  - 2 = Rolling (5° ≤ slope < 15°)
  - 3 = Steep (15° ≤ slope < 30°)
  - 4 = Very Steep (slope ≥ 30°)
- **Use**: Land use planning, construction feasibility
- **Output**: `berlin_terrain_classification.tif`

### Hydrological Analysis

#### Flow Direction
- **What**: Direction water flows from each cell (D8 algorithm)
  - 1=E, 2=SE, 3=S, 4=SW, 5=W, 6=NW, 7=N, 8=NE
- **Use**: Watershed delineation, erosion routing
- **Output**: `berlin_flow_direction.tif`

#### Flow Accumulation
- **What**: Number of cells draining through each cell
- **Use**: Stream detection, drainage basin analysis
- **Output**: `berlin_flow_accumulation.tif`

#### Stream Networks
- **What**: Vector features of detected streams/drainage lines
- **Threshold**: Flow accumulation ≥ 1000 cells
- **Use**: Hydrological modeling, environmental planning
- **Output**: `berlin_streams.geojson`

#### Watersheds
- **What**: Vector polygons representing drainage basins
- **Use**: Water resource management, flood prediction
- **Output**: `berlin_watersheds.geojson`

### Urban Planning Analysis

#### Flood Risk Assessment
- **What**: Areas prone to flooding (low elevation + high flow accumulation)
- **Methodology**:
  - Normalized elevation: 60% weight
  - Normalized flow accumulation: 40% weight
  - Top 20% high-risk areas identified
- **Use**: Disaster planning, insurance, development restrictions
- **Output**: `berlin_flood_risk.geojson`

#### Development Suitability
- **What**: Areas suitable for urban development
- **Criteria**:
  - Maximum slope: 20° (default, configurable)
  - Above minimum elevation (optional)
- **Use**: Urban planning, infrastructure placement
- **Output**: `berlin_development_suitability.geojson`

#### Terrain Statistics
- **What**: Comprehensive elevation and slope statistics
- **Includes**:
  - Min/max/mean/std elevation
  - Slope range and averages
  - Total relief
- **Output**: `terrain_statistics.json`

## Advanced Usage

### Python API

```python
from app.utils.dem_analysis import DEMAnalyzer

# Load DEM
analyzer = DEMAnalyzer("data/raster/dem/berlin_dem.tif")

# Compute single derivative
slope = analyzer.compute_slope()
aspect = analyzer.compute_aspect()

# Hydrological analysis
flow_dir = analyzer.compute_flow_direction()
flow_accum = analyzer.compute_flow_accumulation(flow_direction=flow_dir)

# Urban planning
flood_areas = analyzer.analyze_flood_risk(flow_accumulation=flow_accum)
dev_areas = analyzer.analyze_development_suitability(max_slope=15)

# Statistics
stats = analyzer.compute_terrain_statistics()
print(f"Elevation range: {stats['elevation']['min']} - {stats['elevation']['max']} m")
```

### Custom Analysis Parameters

Modify analysis parameters in scripts:

```python
# analyze_berlin_dem.py
# Flood risk assessment
flood_areas = analyzer.analyze_flood_risk(
    flow_accumulation=flow_accum,
    output_path=flood_risk_path
)

# Development suitability (custom slope threshold)
dev_areas = analyzer.analyze_development_suitability(
    max_slope=15.0,  # Change slope threshold
    min_elevation=None,  # Add minimum elevation requirement
    output_path=dev_suit_path
)

# Stream detection (custom threshold)
streams = analyzer.identify_streams(
    flow_accumulation=flow_accum,
    threshold=500,  # Lower threshold = more streams
    output_path=streams_path
)
```

## File Structure

```
data/raster/dem/
├── berlin_dem.tif                              # Original DEM
└── analysis_results/
    ├── terrain_statistics.json                 # Elevation/slope stats
    ├── berlin_slope.tif                        # Slope in degrees
    ├── berlin_aspect.tif                       # Slope direction (0-360°)
    ├── berlin_hillshade.tif                    # 3D visualization
    ├── berlin_terrain_classification.tif       # Flat/rolling/steep/very steep
    ├── berlin_flow_direction.tif               # D8 flow direction
    ├── berlin_flow_accumulation.tif            # Water accumulation
    ├── berlin_streams.geojson                  # Stream networks
    ├── berlin_watersheds.geojson               # Drainage basins
    ├── berlin_flood_risk.geojson               # Flood-prone areas
    ├── berlin_development_suitability.geojson  # Development areas
    └── visualizations/
        ├── slope_map.png
        ├── aspect_map.png
        ├── hillshade_map.png
        ├── terrain_classification.png
        ├── flow_direction_map.png
        ├── flow_accumulation_map.png
        ├── streams_map.png
        ├── watersheds_map.png
        ├── flood_risk_map.png
        ├── development_suitability_map.png
        └── overview_map.png
```

## Dependencies

Required packages (should be installed in project):
- `rasterio` - Raster I/O
- `geopandas` - Vector data handling
- `numpy` - Array operations
- `scipy` - Scientific computing
- `scikit-image` - Image processing
- `matplotlib` - Visualization
- `planetary-computer` - Planetary Computer API
- `pystac-client` - STAC catalog access

Install missing packages:
```bash
pip install planetary-computer pystac-client scikit-image scipy
```

## Data Source

**Copernicus NASADEM**
- **Resolution**: 30 meters
- **Coverage**: Global (including Europe)
- **Source**: NASA/ESA partnership
- **License**: Open data (CC BY 4.0)
- **Provider**: Microsoft Planetary Computer

**Berlin Bounding Box**:
- West: 13.088°E
- East: 13.761°E
- South: 52.338°N
- North: 52.675°N

## Integration with API

The analysis results can be integrated with your geospatial API:

1. **Store results in PostGIS** (vector features as tables)
2. **Expose via REST endpoints** (e.g., `/api/dem/slope`, `/api/dem/flood-risk`)
3. **Query by location** (point or polygon queries)
4. **Combine with other datasets** (OSM, Sentinel, etc.)

Example endpoint structure:
```
GET /api/dem/slope?bbox=13.088,52.338,13.761,52.675
GET /api/dem/flood-risk?point=13.4,52.5
GET /api/dem/development-suitability?region=berlin
POST /api/dem/zonal-stats?polygon=<geojson>
```

## Performance Considerations

- **Flow accumulation**: Iterative algorithm, may take 1-2 minutes for full DEM
- **Flood risk**: Computationally intensive classification, ~30-60 seconds
- **Memory**: Requires sufficient RAM for full DEM (Berlin ~100 MB)

For very large regions:
- Consider tiling the DEM
- Use lower resolution input (90m instead of 30m)
- Implement streaming/chunked processing

## Troubleshooting

### DEM Download Fails
```
Error: "No items found for cop-dem-glo-30"
```
Solutions:
- Check internet connection
- Verify bounding box is correct
- Planetary Computer API may be down
- Try alternative source (SRTM, OpenTopography)

### Memory Errors
```
MemoryError: Unable to allocate memory
```
Solutions:
- Close other applications
- Use lower resolution DEM
- Process smaller tiles
- Increase system virtual memory

### Missing Dependencies
```
ImportError: No module named 'planetary_computer'
```
Solutions:
```bash
pip install planetary-computer pystac-client
```

## Examples

### Find Suitable Building Sites
```python
analyzer = DEMAnalyzer("data/raster/dem/berlin_dem.tif")
suitable = analyzer.analyze_development_suitability(max_slope=15)
# Filter by area size, proximity to amenities, etc.
large_sites = suitable[suitable.geometry.area > 10000]
```

### Identify Flood-Prone Neighborhoods
```python
flood_risk = analyzer.analyze_flood_risk(flow_accumulation=flow_accum)
# Intersect with neighborhood boundaries
risky_neighborhoods = gpd.sjoin(neighborhoods, flood_risk, how='inner')
```

### Extract Elevation Profile
```python
import geopandas as gpd
from shapely.geometry import LineString

line = LineString([(13.1, 52.4), (13.7, 52.6)])
# Sample DEM along line
elevations = analyzer.extract_elevation_profile(line, resolution=10)
```

## References

- Copernicus DEM: https://spacedata.copernicus.eu/web/cscda/dataset-details?articleId=394198
- Microsoft Planetary Computer: https://planetarycomputer.microsoft.com/
- GDAL/Rasterio Documentation: https://rasterio.readthedocs.io/
- Hydrological Modeling: https://en.wikipedia.org/wiki/Digital_elevation_model

## Citation

If using this analysis in publications, cite:
```
DEM Analysis of Berlin using Copernicus NASADEM (30m resolution)
via Microsoft Planetary Computer
Data processed with Rasterio and GeoPandas
```

## Support

For issues or questions:
1. Check troubleshooting section
2. Review log files in analysis runs
3. Check data quality (examine raw DEM)
4. Refer to dependency documentation

---

**Last Updated**: 2024
**DEM Resolution**: 30 meters
**Analysis Version**: 1.0
