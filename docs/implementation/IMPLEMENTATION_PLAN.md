# 📋 Comprehensive Implementation Plan for NDVI & Multi-Dataset Integration

**Project:** Cognitive Geospatial Assistant API
**Author:** Sk Fazla Rabby
**Date:** 2025-01-20
**Version:** 1.0

---

## 🎯 Objective

Extend the existing geospatial API to support:
- **NDVI analysis and vegetation change detection**
- **DEM-based terrain analysis** (slope, aspect, elevation)
- **Land cover classification** (ESA WorldCover)
- **Multi-dataset integration** for complex geospatial reasoning

---

## 📊 Current State Analysis

### ✅ What's Already Implemented

| Component | Status | File Location |
|-----------|--------|---------------|
| FastAPI Backend | ✅ Complete | `app/main.py` |
| PostGIS Integration | ✅ Complete | `app/utils/database.py` |
| Spatial Engine (Vector) | ✅ Complete | `app/utils/spatial_engine.py` |
| SQL Generator | ✅ Complete | `app/utils/sql_generator.py` |
| Sentinel-2 Loader | ✅ Complete | `app/utils/data_loaders/sentinel_loader.py` |
| NDVI Computation | ✅ Complete | `sentinel_loader.py:132-179` |
| OSM Data Integration | ✅ Complete | Berlin hospitals, schools, etc. |
| Catalog System | ✅ Basic | `data/metadata/catalog.json` |
| DeepSeek Integration | ✅ Complete | `app/utils/deepseek.py` |

### ❌ Missing Capabilities

- Raster operations in spatial engine (NDVI change detection, zonal statistics)
- PostGIS raster support
- DEM-based terrain analysis (slope, aspect, elevation queries)
- Land cover classification integration
- Temporal analysis workflows
- Raster-vector integration queries
- Multi-dataset composite analysis

---

## 🗺️ Implementation Roadmap

### **Phase 1: NDVI Analysis Pipeline** 🌿

**Priority:** 🔴 HIGH
**Duration:** 2-3 days
**Dependencies:** None (extends existing Sentinel loader)

#### 1.1 Enhanced NDVI Processing Module

**File:** `app/utils/raster_operations.py`

**Features:**
```python
class RasterOperations:
    # NDVI Computation
    - compute_ndvi(red_band, nir_band) → ndvi_raster

    # Change Detection
    - ndvi_difference(ndvi_t1, ndvi_t2) → difference_raster
    - detect_vegetation_loss(ndvi_diff, threshold=-0.2) → loss_polygons
    - detect_vegetation_gain(ndvi_diff, threshold=0.2) → gain_polygons

    # Temporal Analysis
    - ndvi_time_series(dates_list) → temporal_stats
    - compute_trends(ndvi_series) → trend_raster

    # Zonal Statistics
    - zonal_stats(raster, polygons, stats=['mean', 'min', 'max', 'std'])
    - extract_by_mask(raster, polygon) → clipped_raster
    - raster_to_points(raster, threshold) → point_geodataframe
```

**Example Workflow:**
```python
# User query: "Show residential areas in Cologne that lost vegetation since 2018"

# Step 1: Load NDVI rasters
ndvi_2018 = load_raster("data/raster/ndvi_timeseries/cologne_ndvi_2018.tif")
ndvi_2024 = load_raster("data/raster/ndvi_timeseries/cologne_ndvi_2024.tif")

# Step 2: Compute change
ndvi_diff = raster_ops.ndvi_difference(ndvi_2024, ndvi_2018)

# Step 3: Load residential polygons
residential = load_vector("osm_residential_cologne")

# Step 4: Zonal statistics
stats = raster_ops.zonal_stats(ndvi_diff, residential, stats=['mean'])

# Step 5: Filter and return
result = residential[stats['mean'] < -0.2]
```

#### 1.2 Spatial Engine - Raster Support

**File:** `app/utils/spatial_engine.py` (extend existing)

**New Methods:**
```python
class SpatialEngine:
    def execute_raster_operation(self, operation: dict) -> Any:
        """Execute raster-specific operations"""

    def clip_raster_by_vector(self, raster_path, vector_gdf) -> np.ndarray:
        """Clip raster using vector mask"""

    def raster_calculator(self, expression: str, rasters: dict) -> np.ndarray:
        """Execute raster algebra: (B8 - B4) / (B8 + B4)"""

    def vectorize_raster(self, raster, threshold=None) -> gpd.GeoDataFrame:
        """Convert raster to polygons"""
```

#### 1.3 PostGIS Raster Extension

**File:** `scripts/setup_postgis_raster.py`

```sql
-- Enable PostGIS raster
CREATE EXTENSION IF NOT EXISTS postgis_raster;

-- Create raster catalog table
CREATE TABLE raster_catalog (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    rast raster,
    acquisition_date DATE,
    dataset_type VARCHAR(50),  -- 'ndvi', 'dem', 'landcover'
    metadata JSONB
);

-- Add spatial index
CREATE INDEX raster_catalog_gist ON raster_catalog USING GIST (ST_ConvexHull(rast));

-- Example: Import NDVI raster
-- raster2pgsql -s 4326 -I -C -M ndvi_2024.tif raster_catalog | psql -d geoassist
```

**Hybrid Query Example:**
```sql
-- Find residential areas with NDVI decrease
SELECT
    r.osm_id,
    r.name,
    ST_AsGeoJSON(r.geometry) as geojson,
    AVG((ST_SummaryStats(ST_Clip(ndvi.rast, r.geometry))).mean) as avg_ndvi_change
FROM osm_residential r
JOIN raster_catalog ndvi ON ST_Intersects(r.geometry, ST_ConvexHull(ndvi.rast))
WHERE ndvi.name = 'ndvi_difference_2018_2024'
GROUP BY r.osm_id, r.name, r.geometry
HAVING AVG((ST_SummaryStats(ST_Clip(ndvi.rast, r.geometry))).mean) < -0.2;
```

#### 1.4 API Endpoints for NDVI

**File:** `app/routes/raster.py` (new)

```python
from fastapi import APIRouter

router = APIRouter(prefix="/raster", tags=["raster"])

@router.post("/ndvi/change-detection")
async def ndvi_change_detection(request: NDVIChangeRequest):
    """
    Detect vegetation change between two time periods

    Example:
    {
        "region": "cologne",
        "date_start": "2018-07-01",
        "date_end": "2024-07-01",
        "threshold": -0.2,
        "mask_vector": "osm_residential"
    }
    """

@router.post("/ndvi/zonal-stats")
async def ndvi_zonal_statistics(request: ZonalStatsRequest):
    """Compute NDVI statistics per polygon"""

@router.get("/ndvi/timeseries/{location}")
async def ndvi_timeseries(location: str, start_date: str, end_date: str):
    """Get NDVI time series for a location"""
```

#### 1.5 Example Scripts

**File:** `examples/04_ndvi_change_detection.py`

```python
"""
Example: NDVI Change Detection Workflow
Detect vegetation loss in Berlin residential areas (2018-2024)
"""

from app.utils.raster_operations import RasterOperations
from app.utils.data_loaders.sentinel_loader import SentinelLoader
import geopandas as gpd

# 1. Download Sentinel-2 data
loader = SentinelLoader()
berlin_bbox = (13.088, 52.338, 13.761, 52.675)

# Download 2018 data
scene_2018 = loader.download_for_region(
    region_name="berlin",
    bbox=berlin_bbox,
    date="2018-07-15",
    max_cloud=10.0
)

# Download 2024 data
scene_2024 = loader.download_for_region(
    region_name="berlin",
    bbox=berlin_bbox,
    date="2024-07-15",
    max_cloud=10.0
)

# 2. Compute NDVI
ndvi_2018 = loader.compute_ndvi(scene_2018)
ndvi_2024 = loader.compute_ndvi(scene_2024)

# 3. Change detection
raster_ops = RasterOperations()
ndvi_diff = raster_ops.ndvi_difference(ndvi_2024, ndvi_2018)

# 4. Load residential areas
residential = gpd.read_file("data/vector/osm/berlin_residential.geojson")

# 5. Zonal statistics
stats = raster_ops.zonal_stats(ndvi_diff, residential, stats=['mean', 'std'])

# 6. Filter areas with significant loss
residential['ndvi_change'] = stats['mean']
loss_areas = residential[residential['ndvi_change'] < -0.2]

# 7. Save results
loss_areas.to_file("data/results/berlin_vegetation_loss.geojson", driver="GeoJSON")

print(f"Found {len(loss_areas)} areas with vegetation loss > 0.2 NDVI")
```

---

### **Phase 2: DEM & Terrain Analysis** ⛰️

**Priority:** 🟡 MEDIUM
**Duration:** 2-3 days
**Dependencies:** Phase 1 (raster operations module)

#### 2.1 DEM Data Loader

**File:** `app/utils/data_loaders/dem_loader.py` (extend existing)

```python
class DEMLoader:
    """Download and process Digital Elevation Models"""

    def download_copernicus_dem(self, bbox, resolution=30):
        """
        Download Copernicus DEM (free, global coverage)
        Resolutions: 30m or 90m
        Source: AWS Open Data Registry
        """

    def download_srtm(self, bbox):
        """
        Download SRTM DEM (90m resolution)
        Alternative source for DEM data
        """

    def clip_to_region(self, dem_path, bbox_or_polygon):
        """Clip DEM to area of interest"""

    def reproject_dem(self, dem_path, target_crs):
        """Reproject DEM to local projection"""
```

#### 2.2 Terrain Analysis Module

**File:** `app/utils/terrain_analysis.py` (new)

```python
import numpy as np
import rasterio
from rasterio.transform import Affine
import richdem as rd

class TerrainAnalyzer:
    """Terrain analysis from DEM data"""

    def compute_slope(self, dem_array, resolution, units='degrees'):
        """
        Compute slope from DEM
        units: 'degrees' or 'percent'
        """

    def compute_aspect(self, dem_array):
        """
        Compute aspect (direction of slope)
        Returns: 0-360 degrees (0=North, 90=East, 180=South, 270=West)
        """

    def compute_hillshade(self, dem_array, azimuth=315, altitude=45):
        """Compute hillshade for visualization"""

    def compute_tri(self, dem_array):
        """
        Terrain Ruggedness Index
        Measure of terrain heterogeneity
        """

    def compute_twi(self, dem_array):
        """
        Topographic Wetness Index
        Useful for flood risk analysis
        """

    def extract_elevation_profile(self, dem, line_geometry):
        """Extract elevation along a line (e.g., hiking trail)"""

    def identify_peaks(self, dem_array, prominence=100):
        """Identify mountain peaks and summits"""
```

**Example Usage:**
```python
# Query: "Find hospitals on slopes > 15 degrees in Munich"

# 1. Load DEM
dem = rasterio.open("data/raster/dem/munich_dem.tif").read(1)

# 2. Compute slope
terrain = TerrainAnalyzer()
slope = terrain.compute_slope(dem, resolution=30, units='degrees')

# 3. Convert slope raster to polygons (slope > 15°)
steep_areas = raster_ops.vectorize_raster(slope, threshold=15)

# 4. Load hospitals
hospitals = gpd.read_file("data/vector/osm/munich_hospitals.geojson")

# 5. Spatial join
hospitals_on_slopes = gpd.sjoin(hospitals, steep_areas, predicate='within')
```

#### 2.3 Integration Queries

**Natural Language → SQL Examples:**

```python
# Query 1: "Find areas at risk of flooding"
# → Low elevation + near rivers + flat terrain

SELECT
    u.name,
    ST_AsGeoJSON(u.geometry) as geojson,
    AVG((ST_SummaryStats(ST_Clip(dem.rast, u.geometry))).mean) as avg_elevation
FROM urban_areas u
JOIN raster_catalog dem ON ST_Intersects(u.geometry, ST_ConvexHull(dem.rast))
JOIN rivers r ON ST_DWithin(u.geometry, r.geometry, 1000)  -- within 1km
WHERE dem.dataset_type = 'elevation'
GROUP BY u.name, u.geometry
HAVING AVG((ST_SummaryStats(ST_Clip(dem.rast, u.geometry))).mean) < 10;  -- elevation < 10m
```

```python
# Query 2: "Agricultural areas on south-facing slopes"
# → Aspect 135-225° (south-facing) + slope 5-20° + land use = agriculture

SELECT
    a.parcel_id,
    ST_AsGeoJSON(a.geometry) as geojson,
    AVG((ST_SummaryStats(ST_Clip(aspect.rast, a.geometry))).mean) as avg_aspect,
    AVG((ST_SummaryStats(ST_Clip(slope.rast, a.geometry))).mean) as avg_slope
FROM agricultural_parcels a
JOIN raster_catalog aspect ON ST_Intersects(a.geometry, ST_ConvexHull(aspect.rast))
JOIN raster_catalog slope ON ST_Intersects(a.geometry, ST_ConvexHull(slope.rast))
WHERE aspect.dataset_type = 'aspect'
  AND slope.dataset_type = 'slope'
GROUP BY a.parcel_id, a.geometry
HAVING AVG((ST_SummaryStats(ST_Clip(aspect.rast, a.geometry))).mean) BETWEEN 135 AND 225
  AND AVG((ST_SummaryStats(ST_Clip(slope.rast, a.geometry))).mean) BETWEEN 5 AND 20;
```

---

### **Phase 3: Land Cover Classification** 🏘️

**Priority:** 🟡 MEDIUM
**Duration:** 1-2 days
**Dependencies:** Phase 1 (raster operations)

#### 3.1 ESA WorldCover Loader

**File:** `app/utils/data_loaders/worldcover_loader.py` (new)

```python
class WorldCoverLoader:
    """
    Download and process ESA WorldCover data
    Resolution: 10m
    Coverage: Global
    Years: 2020, 2021
    """

    CLASSES = {
        10: 'Tree cover',
        20: 'Shrubland',
        30: 'Grassland',
        40: 'Cropland',
        50: 'Built-up',
        60: 'Bare / sparse vegetation',
        70: 'Snow and ice',
        80: 'Permanent water bodies',
        90: 'Herbaceous wetland',
        95: 'Mangroves',
        100: 'Moss and lichen'
    }

    def download_worldcover(self, bbox, year=2021):
        """
        Download WorldCover tiles for region
        Source: ESA WorldCover API
        """

    def clip_to_region(self, worldcover_path, bbox):
        """Clip to area of interest"""

    def classify_pixels(self, worldcover_array):
        """Get pixel classification"""

    def compute_class_statistics(self, worldcover_array, polygons):
        """Compute % of each land cover class per polygon"""
```

#### 3.2 Land Cover Analysis

**File:** `app/utils/landcover_analysis.py` (new)

```python
class LandCoverAnalyzer:

    def detect_landcover_change(self, lc_2020, lc_2021):
        """
        Detect land cover transitions
        Returns: Change matrix (forest → urban, etc.)
        """

    def urbanization_analysis(self, lc_t1, lc_t2):
        """
        Detect areas converted to built-up land
        """

    def deforestation_detection(self, lc_t1, lc_t2):
        """
        Detect forest loss
        """

    def compute_fragmentation(self, landcover_array, class_value):
        """
        Compute landscape fragmentation metrics
        - Patch count
        - Average patch size
        - Edge density
        """
```

**Example Queries:**

```python
# Query 1: "Find forest converted to urban in Berlin (2020-2021)"

lc_2020 = load_raster("data/raster/worldcover/berlin_2020.tif")
lc_2021 = load_raster("data/raster/worldcover/berlin_2021.tif")

analyzer = LandCoverAnalyzer()
changes = analyzer.detect_landcover_change(lc_2020, lc_2021)

# Filter: forest (10) → built-up (50)
deforestation_urban = changes[(changes['from'] == 10) & (changes['to'] == 50)]
```

```python
# Query 2: "Percentage of each land cover type in Berlin districts"

districts = gpd.read_file("data/vector/gadm/berlin_districts.gpkg")
worldcover = load_raster("data/raster/worldcover/berlin_2021.tif")

for idx, district in districts.iterrows():
    stats = raster_ops.zonal_stats(worldcover, district.geometry, categorical=True)
    print(f"{district['name']}: {stats}")
```

---

### **Phase 4: Multi-Dataset Integration** 🔗

**Priority:** 🔴 HIGH
**Duration:** 2-3 days
**Dependencies:** Phases 1, 2, 3

#### 4.1 Composite Analysis Workflows

**File:** `app/utils/composite_analysis.py` (new)

```python
class CompositeAnalyzer:
    """Execute multi-dataset integration queries"""

    def urbanization_on_slopes(self, dem, landcover, slope_threshold=20):
        """Find urban areas on steep slopes"""

    def vegetation_loss_by_landuse(self, ndvi_diff, landcover, districts):
        """Analyze NDVI change per land cover class and district"""

    def flood_risk_assessment(self, dem, rivers, landcover, urban_areas):
        """
        Composite flood risk analysis:
        - Low elevation (DEM)
        - Near rivers (buffer)
        - In urban areas (landcover or OSM)
        - Flat terrain (slope < 5°)
        """
```

**Example: Multi-Dataset Query**

```python
# User Query: "Find residential areas on steep slopes with vegetation loss
#              in forest zones near Berlin"

# Step 1: Load datasets
residential = load_vector("osm_residential_berlin")
dem = load_raster("dem_berlin.tif")
ndvi_2018 = load_raster("ndvi_berlin_2018.tif")
ndvi_2024 = load_raster("ndvi_berlin_2024.tif")
landcover = load_raster("worldcover_berlin_2021.tif")

# Step 2: Terrain analysis
slope = terrain.compute_slope(dem, resolution=30)
steep_areas = vectorize_raster(slope, threshold=20)  # slope > 20°

# Step 3: NDVI change
ndvi_diff = ndvi_2024 - ndvi_2018
veg_loss = vectorize_raster(ndvi_diff, threshold=-0.2)  # loss > 0.2

# Step 4: Extract forest areas
forest_mask = (landcover == 10)  # Tree cover
forest_areas = vectorize_raster(forest_mask)

# Step 5: Spatial intersection
result = gpd.overlay(residential, steep_areas, how='intersection')
result = gpd.overlay(result, veg_loss, how='intersection')
result = gpd.overlay(result, forest_areas, how='intersection')

# Step 6: Return GeoJSON
return result.to_json()
```

#### 4.2 Enhanced Catalog System

**File:** `data/metadata/catalog_v2.json`

```json
{
  "catalog_version": "2.0.0",
  "last_updated": "2025-01-20",
  "datasets": {
    "raster": {
      "ndvi": [
        {
          "id": "sentinel2_ndvi_berlin_2018",
          "name": "Berlin NDVI 2018",
          "source": "Sentinel-2 L2A",
          "path": "data/raster/ndvi_timeseries/berlin_ndvi_2018.tif",
          "date": "2018-07-15",
          "resolution": "10m",
          "bbox": [13.088, 52.338, 13.761, 52.675],
          "tags": ["vegetation", "temporal", "berlin"],
          "related_datasets": ["sentinel2_ndvi_berlin_2024"]
        }
      ],
      "dem": [
        {
          "id": "copernicus_dem_berlin",
          "name": "Berlin DEM (Copernicus)",
          "source": "Copernicus DEM 30m",
          "path": "data/raster/dem/berlin_dem_30m.tif",
          "resolution": "30m",
          "vertical_accuracy": "±4m",
          "derived_products": ["slope_berlin", "aspect_berlin", "hillshade_berlin"]
        }
      ],
      "landcover": [
        {
          "id": "worldcover_berlin_2021",
          "name": "ESA WorldCover Berlin 2021",
          "source": "ESA WorldCover v1.0",
          "path": "data/raster/landcover/berlin_worldcover_2021.tif",
          "year": 2021,
          "resolution": "10m",
          "classes": {
            "10": "Tree cover",
            "40": "Cropland",
            "50": "Built-up"
          }
        }
      ]
    },
    "vector": {
      "osm": [...],
      "administrative": [...]
    },
    "analysis_templates": {
      "vegetation_change": {
        "description": "NDVI change detection workflow",
        "required_datasets": ["ndvi_t1", "ndvi_t2", "mask_vector"],
        "output": "geojson with ndvi_change attribute",
        "example_query": "Find areas with vegetation loss > 0.2 in residential zones"
      },
      "flood_risk": {
        "description": "Multi-factor flood risk assessment",
        "required_datasets": ["dem", "rivers", "urban_areas", "slope"],
        "factors": ["low_elevation", "near_water", "flat_terrain"],
        "output": "flood_risk_score per polygon"
      },
      "urbanization": {
        "description": "Urban expansion analysis",
        "required_datasets": ["landcover_t1", "landcover_t2"],
        "output": "areas converted to built-up land"
      }
    }
  },
  "metadata": {
    "total_datasets": 45,
    "raster_count": 28,
    "vector_count": 17,
    "temporal_coverage": "2018-2024",
    "spatial_coverage": ["Berlin", "Munich", "Cologne", "Hamburg"]
  }
}
```

---

## 🛠️ Technical Stack Updates

### Dependencies to Add

**File:** `requirements.txt`

```txt
# Existing dependencies
fastapi==0.109.0
geopandas==0.14.2
rasterio==1.3.9
...

# NEW - Raster processing enhancements
rioxarray==0.15.1          # ✅ Already installed
xarray==2024.1.0           # For multi-dimensional raster arrays
richdem==0.3.4             # Advanced terrain analysis
rasterstats==0.19.0        # Zonal statistics
scikit-image==0.22.0       # Image processing for raster

# NEW - Data access
planetary-computer==1.0.0  # ✅ Already installed
pystac-client==0.7.5       # ✅ Already installed
elevation==1.1.3           # ✅ Already installed (SRTM download)
sentinelhub==3.9.1         # Alternative Sentinel-2 access

# NEW - Analysis
scipy==1.11.4              # Spatial statistics
numba==0.58.1              # Speed up raster operations
dask[array]==2024.1.0      # Large raster processing

# NEW - Visualization (optional)
matplotlib==3.8.2          # ✅ Already installed
plotly==5.18.0             # Interactive terrain visualization
```

### PostGIS Extensions

```sql
-- Enable in database
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_topology;  -- For complex polygon operations
```

---

## 📁 Project Structure (Updated)

```
project/
├── app/
│   ├── main.py
│   ├── routes/
│   │   ├── query.py                    # ✅ Exists
│   │   └── raster.py                   # 🆕 NEW - Raster endpoints
│   ├── utils/
│   │   ├── deepseek.py                 # ✅ Exists
│   │   ├── spatial_engine.py           # 🔄 EXTEND - Add raster ops
│   │   ├── database.py                 # ✅ Exists
│   │   ├── sql_generator.py            # ✅ Exists
│   │   ├── raster_operations.py        # 🆕 NEW - NDVI, zonal stats
│   │   ├── terrain_analysis.py         # 🆕 NEW - DEM processing
│   │   ├── landcover_analysis.py       # 🆕 NEW - WorldCover
│   │   ├── composite_analysis.py       # 🆕 NEW - Multi-dataset
│   │   └── data_loaders/
│   │       ├── sentinel_loader.py      # ✅ Exists (has NDVI)
│   │       ├── dem_loader.py           # 🔄 EXTEND
│   │       ├── worldcover_loader.py    # 🆕 NEW
│   │       ├── osm_loader.py           # ✅ Exists
│   │       └── gadm_loader.py          # ✅ Exists
│   └── models/
│       └── query_model.py              # ✅ Exists
├── data/
│   ├── raster/
│   │   ├── sentinel2/                  # ✅ Exists (empty)
│   │   ├── ndvi_timeseries/            # ✅ Exists (empty)
│   │   ├── dem/                        # ✅ Exists (empty)
│   │   ├── landcover/                  # 🆕 NEW
│   │   └── derived/                    # 🆕 NEW (slope, aspect, etc.)
│   ├── vector/
│   │   ├── osm/                        # ✅ Exists (Berlin data)
│   │   ├── gadm/                       # ✅ Exists (Germany boundaries)
│   │   └── hydrosheds/                 # 🆕 NEW (future)
│   └── metadata/
│       ├── catalog.json                # ✅ Exists
│       ├── catalog_v2.json             # 🆕 NEW (enhanced)
│       └── stac_catalog/               # 🆕 NEW (STAC metadata)
├── scripts/
│   ├── setup_database.py               # ✅ Exists
│   ├── setup_postgis_raster.py         # 🆕 NEW
│   ├── ingest_data.py                  # ✅ Exists
│   └── precompute_derived_rasters.py   # 🆕 NEW (slope, aspect)
├── examples/
│   ├── 01_download_osm_data.py         # ✅ Exists
│   ├── 02_download_admin_boundaries.py # ✅ Exists
│   ├── 03_download_land_cover.py       # ✅ Exists
│   ├── 04_ndvi_change_detection.py     # 🆕 NEW
│   ├── 05_terrain_analysis.py          # 🆕 NEW
│   ├── 06_landcover_change.py          # 🆕 NEW
│   └── 07_composite_analysis.py        # 🆕 NEW
├── tests/
│   ├── test_raster_operations.py       # 🆕 NEW
│   ├── test_terrain_analysis.py        # 🆕 NEW
│   └── test_spatial_engine.py          # ✅ Exists
├── claude.md                           # ✅ Exists
├── IMPLEMENTATION_PLAN.md              # 🆕 THIS FILE
└── requirements.txt                    # 🔄 UPDATE
```

**Legend:**
- ✅ Exists - Already implemented
- 🆕 NEW - To be created
- 🔄 EXTEND - Modify existing file

---

## 🎯 Example Queries We'll Support

### 1. NDVI Change Detection
```
User: "Find agricultural areas in Brandenburg that lost more than 30% vegetation since 2018"

LLM Plan:
1. Load NDVI 2018 and 2024 for Brandenburg
2. Compute difference
3. Load agricultural areas (OSM landuse=farm or WorldCover class=40)
4. Zonal stats: mean NDVI change per farm
5. Filter: ndvi_change < -0.3
6. Return GeoJSON with farm polygons + change values
```

### 2. Terrain + Infrastructure
```
User: "Show hospitals in Munich that are on slopes greater than 10 degrees"

LLM Plan:
1. Load Munich DEM
2. Compute slope
3. Vectorize slope > 10° areas
4. Load hospitals (OSM amenity=hospital)
5. Spatial join: hospitals within steep areas
6. Return GeoJSON
```

### 3. Multi-Dataset Integration
```
User: "Identify forest areas on slopes > 20° near urban zones in Black Forest region"

LLM Plan:
1. Load DEM → compute slope → vectorize slope > 20°
2. Load WorldCover → extract forests (class=10)
3. Load OSM urban areas or WorldCover built-up (class=50)
4. Buffer urban areas by 1km
5. Spatial intersection: forests ∩ steep_slopes ∩ near_urban
6. Return GeoJSON
```

### 4. Flood Risk Analysis
```
User: "Find residential areas at risk of flooding (elevation < 10m, within 1km of rivers)"

LLM Plan:
1. Load DEM → zonal stats for residential polygons
2. Load rivers (OSM waterway=river)
3. Buffer rivers by 1000m
4. Load residential areas (OSM landuse=residential)
5. Filter: elevation < 10m AND within river buffer
6. Return flood risk zones with risk_score
```

### 5. Urbanization Monitoring
```
User: "Calculate urban sprawl: built-up land increase from 2020 to 2021 in Munich"

LLM Plan:
1. Load WorldCover 2020 → extract built-up (class=50)
2. Load WorldCover 2021 → extract built-up (class=50)
3. Detect change: (class_2020 != 50) AND (class_2021 == 50)
4. Vectorize new urban areas
5. Compute statistics: total area, change %, spatial distribution
6. Return GeoJSON + stats
```

---

## 📋 Implementation Checklist

### Phase 1: NDVI Analysis ✅
- [ ] Create `raster_operations.py` with NDVI functions
- [ ] Extend `spatial_engine.py` for raster support
- [ ] Create `setup_postgis_raster.py` script
- [ ] Add raster routes in `routes/raster.py`
- [ ] Create `examples/04_ndvi_change_detection.py`
- [ ] Test NDVI workflow end-to-end
- [ ] Update catalog with NDVI datasets

### Phase 2: DEM & Terrain ⛰️
- [ ] Extend `dem_loader.py` with Copernicus DEM download
- [ ] Create `terrain_analysis.py` (slope, aspect, hillshade)
- [ ] Add terrain API endpoints
- [ ] Create `examples/05_terrain_analysis.py`
- [ ] Test terrain queries with PostGIS
- [ ] Generate slope/aspect rasters for test regions

### Phase 3: Land Cover 🏘️
- [ ] Create `worldcover_loader.py`
- [ ] Create `landcover_analysis.py` (change detection)
- [ ] Add land cover API endpoints
- [ ] Create `examples/06_landcover_change.py`
- [ ] Download WorldCover tiles for Berlin
- [ ] Test urbanization detection

### Phase 4: Integration 🔗
- [ ] Create `composite_analysis.py`
- [ ] Design catalog v2.0 structure
- [ ] Create `examples/07_composite_analysis.py`
- [ ] Test multi-dataset queries
- [ ] Update DeepSeek prompts for raster operations
- [ ] Performance optimization (caching, indexing)

### Documentation & Testing 📚
- [ ] Update README.md with raster capabilities
- [ ] Create RASTER_OPERATIONS.md guide
- [ ] Write unit tests for all new modules
- [ ] Integration tests for composite queries
- [ ] Performance benchmarks
- [ ] API documentation (OpenAPI/Swagger)

---

## ⚡ Performance Considerations

### Raster Processing Optimization

1. **Tiling Strategy**
   - Use Cloud-Optimized GeoTIFF (COG) format
   - Read only necessary tiles, not full raster

2. **Caching**
   ```python
   # Cache computed products (slope, NDVI diff)
   @lru_cache(maxsize=128)
   def get_slope_raster(region: str):
       # Return cached or compute
   ```

3. **Parallel Processing**
   ```python
   import dask.array as da

   # Process large rasters in chunks
   raster = da.from_array(large_array, chunks=(1024, 1024))
   result = raster.map_blocks(ndvi_function)
   ```

4. **PostGIS Raster Indexing**
   ```sql
   -- Spatial index on raster tables
   CREATE INDEX ON raster_catalog USING GIST (ST_ConvexHull(rast));

   -- Constraint for faster queries
   ALTER TABLE raster_catalog ADD CONSTRAINT enforce_srid CHECK (ST_SRID(rast) = 4326);
   ```

### Database Optimization

```sql
-- Materialized view for common queries
CREATE MATERIALIZED VIEW mv_berlin_ndvi_stats AS
SELECT
    r.osm_id,
    r.name,
    AVG((ST_SummaryStats(ST_Clip(ndvi.rast, r.geometry))).mean) as avg_ndvi
FROM osm_residential r
JOIN raster_catalog ndvi ON ST_Intersects(r.geometry, ST_ConvexHull(ndvi.rast))
GROUP BY r.osm_id, r.name;

CREATE INDEX ON mv_berlin_ndvi_stats(osm_id);
```

---

## 🎓 Research Contributions

This implementation enables:

1. **LLM-Driven Geospatial Reasoning Framework**
   - Natural language → multi-dataset spatial queries
   - Hybrid vector-raster operations
   - Temporal analysis workflows

2. **Open Geospatial Data Benchmark**
   - Reproducible datasets (all open-source)
   - Standard query templates
   - Performance metrics

3. **DeepSeek Integration for Spatial AI**
   - First implementation of DeepSeek for geospatial queries
   - Prompt engineering for spatial operations
   - Query plan optimization

4. **Multi-Modal Spatial Analysis**
   - NDVI + DEM + Land Cover integration
   - Cross-domain reasoning (vegetation + terrain + urbanization)

---

## 📊 Success Metrics

- ✅ Support 20+ example queries across 5 dataset types
- ✅ Query response time < 5 seconds for vector operations
- ✅ Query response time < 15 seconds for raster operations
- ✅ Support regions: Berlin, Munich, Cologne, Hamburg
- ✅ API documentation coverage > 90%
- ✅ Test coverage > 80%

---

## 🚀 Future Extensions

1. **Time Series Analysis**
   - NDVI trends over multiple years
   - Seasonal vegetation patterns
   - Climate change indicators

2. **Machine Learning Integration**
   - Land cover classification (custom models)
   - Vegetation anomaly detection
   - Predictive flood modeling

3. **3D Visualization**
   - Terrain rendering with DEM
   - 3D building models (LOD2 from OSM)
   - Flythrough animations

4. **Real-Time Data**
   - Live Sentinel-2 downloads
   - Weather integration (OpenWeatherMap)
   - Fire detection (FIRMS NASA)

5. **Mobile API**
   - Location-based queries
   - Offline raster processing
   - Field data collection integration

---

**Version History:**
- v1.0 (2025-01-20) - Initial comprehensive plan
- Future updates as implementation progresses

**Author:** Sk Fazla Rabby
**Contact:** [Your contact info]
**License:** MIT
