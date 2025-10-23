# Example Scripts - Real Data Download

These examples demonstrate how to download **free and open-source** geospatial data.

---

## 📝 Available Examples

### 01_download_osm_data.py
Download OpenStreetMap features (hospitals, schools, roads, rivers) for Berlin.

```bash
python examples/01_download_osm_data.py
```

**What it does:**
- Downloads OSM data via free Overpass API
- Saves as GeoJSON files
- No API key required

**Output:**
- `data/vector/osm/berlin_hospitals.geojson`
- `data/vector/osm/berlin_schools.geojson`
- `data/vector/osm/berlin_roads_central.geojson`
- `data/vector/osm/berlin_rivers.geojson`

---

### 02_download_admin_boundaries.py
Download administrative boundaries (countries, states) from GADM.

```bash
python examples/02_download_admin_boundaries.py
```

**What it does:**
- Downloads country and state boundaries
- Uses free GADM database
- Calculates area statistics

**Output:**
- `data/vector/gadm/gadm41_DEU.gpkg` (Germany)
- `data/vector/gadm/gadm41_FRA.gpkg` (France)
- etc.

---

### 03_download_land_cover.py
Download ESA WorldCover land cover classification (10m resolution).

```bash
python examples/03_download_land_cover.py
```

**What it does:**
- Downloads free ESA WorldCover tiles
- Analyzes land cover distribution
- Creates visualization

**Output:**
- `data/raster/copernicus/ESA_WorldCover_10m_2021_N51E013_Map.tif`
- Land cover statistics

---

## 🚀 Running Examples

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Create data directories
mkdir -p data/vector/osm
mkdir -p data/vector/gadm
mkdir -p data/raster/copernicus
```

### Run All Examples

```bash
# Download OSM data
python examples/01_download_osm_data.py

# Download admin boundaries
python examples/02_download_admin_boundaries.py

# Download land cover
python examples/03_download_land_cover.py
```

---

## 📊 Expected Results

After running all examples, you'll have:

```
data/
├── vector/
│   ├── osm/
│   │   ├── berlin_hospitals.geojson      (~50 hospitals)
│   │   ├── berlin_schools.geojson        (~800 schools)
│   │   ├── berlin_roads_central.geojson  (~thousands of road segments)
│   │   └── berlin_rivers.geojson         (~50 river segments)
│   └── gadm/
│       ├── gadm41_DEU.gpkg               (Germany - 16 states)
│       ├── gadm41_FRA.gpkg               (France - 18 regions)
│       └── ...
└── raster/
    └── copernicus/
        ├── ESA_WorldCover_10m_2021_N51E000_Map.tif  (London)
        ├── ESA_WorldCover_10m_2021_N51E013_Map.tif  (Berlin)
        └── ...
```

---

## 🔍 Viewing the Data

### QGIS (Recommended)

1. Download QGIS: https://qgis.org
2. Add vector layer: `Layer > Add Layer > Add Vector Layer`
3. Add raster layer: `Layer > Add Layer > Add Raster Layer`
4. Browse to downloaded files

### Python

```python
import geopandas as gpd
import rasterio
from rasterio.plot import show
import matplotlib.pyplot as plt

# View vector data
hospitals = gpd.read_file('data/vector/osm/berlin_hospitals.geojson')
hospitals.plot()
plt.show()

# View raster data
with rasterio.open('data/raster/copernicus/ESA_WorldCover_10m_2021_N51E013_Map.tif') as src:
    show(src)
    plt.show()
```

### Web

Use [geojson.io](https://geojson.io) to view GeoJSON files online.

---

## 🌍 Customizing Examples

### Change City/Region

Edit the bounding box in each script:

```python
# Example: London instead of Berlin
london_bbox = (-0.510, 51.286, 0.334, 51.686)

# Example: Paris
paris_bbox = (2.225, 48.815, 2.470, 48.902)
```

### Download Different Features

```python
# Available OSM features:
features = ['hospital', 'school', 'building', 'road', 'river']

# Download custom combination
data = loader.query_overpass(bbox, ['hospital', 'school'])
```

### Download Different Countries

```python
# Available country codes
countries = loader.get_available_countries()

# Download any country
india = loader.load_boundaries('IND', admin_level=1)
```

---

## ⚠️ Notes

### Rate Limits

- **Overpass API**: Free but rate-limited. Keep bbox small or add delays.
- **GADM**: No rate limits (direct file download)
- **ESA WorldCover**: No rate limits (AWS S3 hosting)

### File Sizes

- OSM data: 1-50 MB per city (depends on area)
- GADM data: 5-100 MB per country
- WorldCover tiles: 50-200 MB per tile (each tile is 3° x 3°)

### Troubleshooting

**Overpass API timeout:**
```python
# Increase timeout
loader.query_overpass(bbox, features, timeout=300)
```

**GADM download slow:**
```python
# Files are large. Be patient or download manually from gadm.org
```

**WorldCover tile not found:**
Check tile code at https://esa-worldcover.org/en/data-access

---

## 📚 Next Steps

After downloading data:

1. **Load into PostGIS**: Run `python scripts/ingest_data.py`
2. **Run spatial queries**: See main API examples
3. **Integrate with LLM**: Query data using natural language
4. **Visualize on map**: Create web viewer with Leaflet

---

**All data is FREE, OPEN-SOURCE, and ready for research!**
