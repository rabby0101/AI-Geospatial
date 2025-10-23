# NDVI Analysis - Quick Start Guide

**🚀 Get started with NDVI change detection in 5 minutes**

---

## 🎯 What Can You Do?

With the new NDVI capabilities, you can:

✅ Detect vegetation loss/gain between two time periods
✅ Monitor deforestation and urban expansion
✅ Analyze vegetation health per district/park/farm
✅ Combine vegetation data with infrastructure (OSM)
✅ Create change detection maps

---

## 📦 Installation

```bash
# Navigate to project
cd "/Users/skfazlarabby/projects/AI Geospatial"

# Install new dependencies
pip install rasterstats scikit-image xarray scipy

# Verify installation
python -c "import rasterio; print('✅ Rasterio ready')"
```

---

## 🚀 Quick Start

### Option 1: Run Example Script

```bash
# Run the complete NDVI change detection workflow
python examples/04_ndvi_change_detection.py
```

**What it does:**
1. Downloads Sentinel-2 data (or uses sample data)
2. Computes NDVI for 2018 and 2024
3. Detects vegetation loss areas
4. Filters by residential zones
5. Generates summary report

**Output:**
- `data/raster/ndvi_timeseries/berlin_ndvi_diff_2018_2024.tif`
- `data/results/berlin_residential_vegetation_loss.geojson`

---

### Option 2: Use the API

**Step 1: Start the server**
```bash
python -m uvicorn app.main:app --reload
```

**Step 2: Check API docs**
```
Open: http://localhost:8000/docs
Navigate to: "raster" section
```

**Step 3: Make API call**
```bash
curl -X POST "http://localhost:8000/raster/ndvi/change-detection" \
  -H "Content-Type: application/json" \
  -d '{
    "ndvi_t1": "raster/ndvi_timeseries/sample_ndvi_2018.tif",
    "ndvi_t2": "raster/ndvi_timeseries/sample_ndvi_2024.tif",
    "threshold": -0.2
  }'
```

---

### Option 3: Use Python API Directly

```python
from app.utils.raster_operations import RasterOperations
from pathlib import Path

# Initialize
ops = RasterOperations()

# Compute NDVI difference
diff = ops.ndvi_difference(
    ndvi_t1="data/raster/ndvi_timeseries/sample_ndvi_2018.tif",
    ndvi_t2="data/raster/ndvi_timeseries/sample_ndvi_2024.tif",
    output_path="data/raster/ndvi_timeseries/ndvi_diff.tif"
)

# Detect vegetation loss
loss_areas = ops.detect_vegetation_loss(
    ndvi_diff=diff,
    threshold=-0.2,
    min_area_pixels=50
)

print(f"Found {len(loss_areas)} vegetation loss areas")
loss_areas.to_file("output.geojson", driver="GeoJSON")
```

---

## 📋 Common Use Cases

### 1️⃣ Detect Deforestation

```python
# Query: "Find forest areas that lost vegetation in 2018-2024"

from app.utils.raster_operations import RasterOperations
import geopandas as gpd

ops = RasterOperations()

# NDVI change
diff = ops.ndvi_difference("ndvi_2018.tif", "ndvi_2024.tif")

# Detect loss
loss = ops.detect_vegetation_loss(diff, threshold=-0.3)

# Filter for forests (load forest polygons)
forests = gpd.read_file("forests.geojson")
deforestation = gpd.overlay(loss, forests, how='intersection')

deforestation.to_file("deforestation_2018_2024.geojson")
```

---

### 2️⃣ Monitor Park Vegetation Health

```python
# Query: "What's the average NDVI in each Berlin park?"

# API call
import requests

response = requests.post(
    "http://localhost:8000/raster/ndvi/zonal-stats",
    json={
        "raster": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
        "vector": "vector/osm/berlin_parks.geojson",
        "stats": ["mean", "min", "max"]
    }
)

result = response.json()
# Each park now has: zonal_mean, zonal_min, zonal_max
```

---

### 3️⃣ Urban Expansion Analysis

```python
# Query: "Find areas where vegetation was lost to urbanization"

# Step 1: Detect vegetation loss
ops = RasterOperations()
diff = ops.ndvi_difference("ndvi_2018.tif", "ndvi_2024.tif")
loss = ops.detect_vegetation_loss(diff, threshold=-0.4)

# Step 2: Load current urban areas
urban = gpd.read_file("urban_areas_2024.geojson")

# Step 3: Spatial join
urban_expansion = gpd.overlay(loss, urban, how='intersection')

print(f"Urban expansion: {urban_expansion.area.sum() / 1e6:.2f} km²")
```

---

### 4️⃣ Agricultural Monitoring

```python
# Query: "Which farms have declining vegetation health?"

import geopandas as gpd
from app.utils.raster_operations import RasterOperations

ops = RasterOperations()

# Load agricultural parcels
farms = gpd.read_file("agricultural_parcels.geojson")

# Compute zonal stats
stats = ops.zonal_stats(
    raster="ndvi_2024.tif",
    polygons=farms,
    stats=['mean', 'std']
)

# Add to farms GeoDataFrame
farms['ndvi_mean'] = stats['mean']
farms['ndvi_std'] = stats['std']

# Find farms with low NDVI
struggling_farms = farms[farms['ndvi_mean'] < 0.3]
print(f"{len(struggling_farms)} farms with low vegetation health")
```

---

## 🎨 Visualization Tips

### View in QGIS

```bash
# 1. Open QGIS
# 2. Layer → Add Layer → Add Raster Layer
# 3. Navigate to: data/raster/ndvi_timeseries/ndvi_diff.tif
# 4. Style with color ramp: red (loss) → green (gain)
```

### View in Python

```python
import rasterio
from rasterio.plot import show
import matplotlib.pyplot as plt

# Load NDVI difference
with rasterio.open("ndvi_diff.tif") as src:
    ndvi_diff = src.read(1)

# Plot
fig, ax = plt.subplots(figsize=(10, 8))
show(ndvi_diff, ax=ax, cmap='RdYlGn', vmin=-0.5, vmax=0.5)
plt.colorbar(ax.images[0], label='NDVI Change')
plt.title('Vegetation Change 2018-2024')
plt.show()
```

---

## 🧪 Testing

### Test 1: API Health Check
```bash
curl http://localhost:8000/raster/health
# Expected: {"status": "healthy", "service": "raster-operations"}
```

### Test 2: List Available Datasets
```bash
curl http://localhost:8000/raster/catalog
# Expected: List of raster datasets
```

### Test 3: Run Example Workflow
```bash
python examples/04_ndvi_change_detection.py
# Expected: Complete workflow with summary report
```

---

## 📊 Understanding NDVI Values

| NDVI Range | Interpretation | Example |
|------------|----------------|---------|
| < 0 | Water, clouds, snow | Rivers, lakes |
| 0 - 0.1 | Bare soil, rocks | Desert, construction sites |
| 0.1 - 0.2 | Sparse vegetation | Grassland |
| 0.2 - 0.5 | Moderate vegetation | Farmland, shrubs |
| 0.5 - 0.8 | Dense vegetation | Forests, parks |
| 0.8 - 1.0 | Very dense vegetation | Rainforests |

**Change Detection Thresholds:**
- `NDVI_diff < -0.4`: Severe vegetation loss (deforestation)
- `NDVI_diff < -0.2`: Moderate loss (urban expansion)
- `NDVI_diff > 0.2`: Vegetation recovery
- `NDVI_diff > 0.4`: Significant greening

---

## 🐛 Troubleshooting

### Error: "File not found"
```bash
# Check if data exists
ls -la data/raster/ndvi_timeseries/

# If empty, run download script or use sample data
python examples/04_ndvi_change_detection.py
```

### Error: "Module not found: rasterstats"
```bash
# Install missing dependencies
pip install rasterstats scikit-image xarray scipy
```

### Error: "Cannot connect to database"
```bash
# Start PostGIS container
docker-compose up -d

# Verify connection
psql -h localhost -p 5433 -U geoassist -d geoassist
```

### Error: "CRS mismatch"
```python
# The raster operations handle CRS automatically
# But if issues persist, manually reproject:

import geopandas as gpd
gdf = gpd.read_file("your_file.geojson")
gdf = gdf.to_crs("EPSG:4326")  # Reproject to WGS84
```

---

## 📚 API Reference

### NDVI Change Detection

**Endpoint:** `POST /raster/ndvi/change-detection`

**Request:**
```json
{
  "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_2018.tif",
  "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
  "threshold": -0.2,
  "mask_vector": "vector/osm/berlin_residential.geojson"
}
```

**Response:**
```json
{
  "success": true,
  "result_type": "geojson",
  "data": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "metadata": {
    "count": 42,
    "crs": "EPSG:4326",
    "bounds": [13.088, 52.338, 13.761, 52.675]
  }
}
```

---

### Zonal Statistics

**Endpoint:** `POST /raster/ndvi/zonal-stats`

**Request:**
```json
{
  "raster": "raster/ndvi_timeseries/berlin_ndvi_2024.tif",
  "vector": "vector/osm/berlin_parks.geojson",
  "stats": ["mean", "min", "max", "std"]
}
```

**Response:**
```json
{
  "success": true,
  "result_type": "geojson",
  "data": {
    "type": "FeatureCollection",
    "features": [
      {
        "properties": {
          "name": "Tiergarten",
          "zonal_mean": 0.65,
          "zonal_min": 0.42,
          "zonal_max": 0.81,
          "zonal_std": 0.12
        },
        "geometry": {...}
      }
    ]
  }
}
```

---

## 🎯 Next Steps

**Phase 2: DEM & Terrain Analysis** (Coming Next)
- Slope computation
- Aspect analysis
- Flood risk assessment
- Elevation-based queries

**Phase 3: Land Cover Classification**
- ESA WorldCover integration
- Urban sprawl detection
- Land use change analysis

**Phase 4: Multi-Dataset Integration**
- Combined NDVI + DEM + Land Cover queries
- Complex geospatial reasoning
- Automated workflows

---

## 📞 Support

- **Documentation:** See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- **API Docs:** http://localhost:8000/docs
- **Examples:** Check `examples/` directory
- **Issues:** Review [PHASE1_NDVI_COMPLETE.md](PHASE1_NDVI_COMPLETE.md)

---

**Happy analyzing! 🌍🛰️📊**
