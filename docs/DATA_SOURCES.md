# Free and Open-Source Geospatial Data Sources

This document lists all the **100% free and open-source** geospatial datasets integrated into the Cognitive Geospatial Assistant API.

---

## 🗺️ Vector Data

### 1. OpenStreetMap (OSM)
- **Source**: https://www.openstreetmap.org
- **License**: ODbL (Open Database License) - FREE
- **What**: Roads, buildings, hospitals, schools, parks, rivers, etc.
- **Coverage**: Global
- **Access Methods**:
  - Overpass API (real-time queries)
  - Geofabrik downloads (regional extracts)
- **Resolution**: Variable (user-contributed)

**Use Cases**:
- Find hospitals within flood zones
- Analyze road networks
- Urban planning and building footprints

### 2. GADM (Administrative Boundaries)
- **Source**: https://gadm.org
- **License**: Free for academic and non-commercial use
- **What**: Country, state, county, and district boundaries
- **Coverage**: Global (all countries)
- **Format**: GeoPackage, Shapefile
- **Levels**: 0-5 (country to local administrative divisions)

**Use Cases**:
- Regional analysis
- Population statistics aggregation
- Administrative planning

---

## 🛰️ Raster Data - Satellite Imagery

### 3. Sentinel-2 (ESA Copernicus)
- **Source**: https://planetarycomputer.microsoft.com
- **License**: FREE and OPEN (ESA Copernicus)
- **What**: Multispectral satellite imagery (10-60m resolution)
- **Bands**: 13 bands including RGB, NIR, SWIR
- **Revisit**: Every 5 days
- **Coverage**: Global (land areas)

**Use Cases**:
- NDVI (vegetation health)
- Change detection
- Land use monitoring
- Agricultural assessment

**Access via Microsoft Planetary Computer** (free):
- No authentication required
- STAC API access
- Cloud-optimized GeoTIFFs

### 4. Landsat 8-9 (USGS)
- **Source**: https://landsat.usgs.gov
- **License**: FREE (U.S. Government)
- **What**: Multispectral imagery (30m resolution)
- **Coverage**: Global
- **Archive**: Since 1972 (historical data)

**Use Cases**:
- Long-term change detection
- Thermal analysis
- Land cover classification

---

## 🏔️ Raster Data - Elevation

### 5. Copernicus DEM
- **Source**: https://planetarycomputer.microsoft.com
- **License**: FREE (ESA Copernicus)
- **What**: Digital Elevation Model
- **Resolution**: 30m and 90m
- **Coverage**: Global (90°N to 56°S)

**Use Cases**:
- Terrain analysis
- Slope and aspect calculation
- Flood modeling
- Viewshed analysis

### 6. SRTM (Shuttle Radar Topography Mission)
- **Source**: https://earthexplorer.usgs.gov
- **License**: FREE (NASA/USGS)
- **Resolution**: 30m (U.S.), 90m (global)
- **Coverage**: 60°N to 56°S

**Alternative access**: `elevation` Python package (automated download)

---

## 🌍 Raster Data - Land Cover

### 7. ESA WorldCover
- **Source**: https://esa-worldcover.org
- **License**: FREE (ESA)
- **What**: Global land cover map at 10m resolution
- **Classes**: 11 land cover types (trees, crops, built-up, water, etc.)
- **Years**: 2020, 2021
- **Coverage**: Global

**Use Cases**:
- Land use analysis
- Urban expansion monitoring
- Forest cover assessment
- Agricultural land identification

### 8. CORINE Land Cover (Europe)
- **Source**: https://land.copernicus.eu
- **License**: FREE (Copernicus)
- **What**: Detailed European land cover
- **Resolution**: 100m
- **Classes**: 44 land cover classes
- **Years**: 2000, 2006, 2012, 2018

**Coverage**: European countries + some neighboring areas

### 9. Impact Observatory Land Use/Land Cover
- **Source**: Microsoft Planetary Computer
- **License**: FREE
- **What**: Annual global land use/land cover
- **Resolution**: 10m
- **Coverage**: Global

---

## 💧 Hydrological Data

### 10. JRC Global Surface Water
- **Source**: https://global-surface-water.appspot.com
- **License**: FREE (European Commission)
- **What**: Water occurrence, change, and seasonality
- **Resolution**: 30m
- **Coverage**: Global
- **Period**: 1984-2021

**Use Cases**:
- Water body detection
- Flood zone mapping
- Reservoir monitoring

### 11. HydroSHEDS
- **Source**: https://www.hydrosheds.org
- **License**: FREE (USGS/WWF)
- **What**: River networks, watersheds, drainage basins
- **Resolution**: Various (from 3 arc-seconds to 30 arc-seconds)
- **Coverage**: Global

---

## 🏙️ Population & Settlements

### 12. GHSL (Global Human Settlement Layer)
- **Source**: https://ghsl.jrc.ec.europa.eu
- **License**: FREE (European Commission)
- **What**: Built-up areas and population density
- **Resolution**: 10m-1km
- **Years**: 1975-2030 (projections)
- **Coverage**: Global

**Use Cases**:
- Urban growth analysis
- Population estimation
- Settlement patterns

### 13. WorldPop
- **Source**: https://www.worldpop.org
- **License**: FREE (CC BY 4.0)
- **What**: High-resolution population distribution
- **Resolution**: 100m
- **Coverage**: Global

---

## 📊 Data Access Summary

| Dataset | Source | License | Global Coverage | Resolution |
|---------|--------|---------|----------------|------------|
| OpenStreetMap | Overpass API / Geofabrik | ODbL | ✅ | Variable |
| GADM | GADM.org | Free | ✅ | Vector |
| Sentinel-2 | Planetary Computer | Free (ESA) | ✅ | 10-60m |
| Landsat 8-9 | USGS | Free (Gov) | ✅ | 30m |
| Copernicus DEM | Planetary Computer | Free (ESA) | ✅ | 30m/90m |
| SRTM | USGS | Free (NASA) | 60°N-56°S | 30m/90m |
| ESA WorldCover | ESA | Free | ✅ | 10m |
| CORINE | Copernicus | Free | Europe only | 100m |
| Global Surface Water | JRC | Free (EC) | ✅ | 30m |
| HydroSHEDS | USGS/WWF | Free | ✅ | Variable |
| GHSL | JRC | Free (EC) | ✅ | 10m-1km |
| WorldPop | WorldPop.org | CC BY 4.0 | ✅ | 100m |

---

## 🔑 API Keys (All Free)

Some services offer better access with free API keys:

1. **Microsoft Planetary Computer**: No key required! Just use it.
2. **OpenTopography** (optional): Free key at https://opentopography.org
3. **Copernicus Data Space** (optional): Free registration at https://dataspace.copernicus.eu

**None of these require payment - they're all 100% free for research and non-commercial use.**

---

## 📦 Installation Requirements

```bash
# Core dependencies
pip install geopandas rasterio planetary-computer pystac-client
pip install requests shapely psycopg2-binary sqlalchemy

# Optional but recommended
pip install rioxarray xarray elevation
```

---

## 🚀 Quick Start Example

```python
from app.utils.data_loaders import OSMLoader, SentinelLoader, CopernicusLoader

# Download OpenStreetMap buildings in Berlin
osm = OSMLoader()
bbox = (13.088, 52.338, 13.761, 52.675)  # Berlin
buildings = osm.query_overpass(bbox, ['building'])

# Download ESA WorldCover land cover
copernicus = CopernicusLoader()
landcover = copernicus.download_worldcover('N51E013', year=2021)

# Search for Sentinel-2 imagery
sentinel = SentinelLoader()
scenes = sentinel.search_planetary_computer(
    bbox=bbox,
    start_date='2024-06-01',
    end_date='2024-06-30',
    max_cloud_cover=15
)
```

---

## 📚 Additional Resources

- [Awesome GIS](https://github.com/sshuair/awesome-gis) - Curated list of geospatial tools
- [Awesome Satellite Imagery](https://github.com/chrieke/awesome-satellite-imagery-datasets)
- [STAC Index](https://stacindex.org/) - Searchable catalog of open geospatial data

---

**All data sources listed here are FREE, OPEN, and suitable for academic research and non-commercial use.**
