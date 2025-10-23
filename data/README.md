# Data Directory

This directory contains geospatial datasets used by the Cognitive Geospatial Assistant API.

## Structure

```
data/
├── raster/              # Raster data (GeoTIFFs)
│   ├── sentinel2/       # Sentinel-2 imagery
│   ├── ndvi_timeseries/ # NDVI time series
│   └── dem/             # Digital Elevation Models
├── vector/              # Vector data (GeoJSON, Shapefiles, GeoPackages)
│   ├── osm/             # OpenStreetMap data
│   ├── gadm/            # Administrative boundaries
│   ├── hydrosheds/      # Hydrology data
│   └── urban_atlas/     # Urban area data
└── metadata/            # Dataset metadata and catalog
    ├── catalog.json     # Dataset catalog
    └── spatial_index.gpkg # Spatial index
```

## Sample Datasets Included

### Vector Data
- **hospitals_berlin.geojson**: Hospital locations in Berlin
- **flood_zones_berlin.geojson**: Simulated flood risk zones
- **urban_areas_berlin.geojson**: Urban district boundaries

### Raster Data
Note: Sample raster files are placeholders. For real analysis, you should download:
- Sentinel-2 imagery from [Copernicus Open Access Hub](https://scihub.copernicus.eu/)
- SRTM DEM from [USGS Earth Explorer](https://earthexplorer.usgs.gov/)
- ESA WorldCover from [ESA WorldCover](https://worldcover2021.esa.int/)

## Adding Your Own Data

### Vector Data
1. Place GeoJSON, Shapefile, or GeoPackage files in appropriate subdirectories
2. Update `metadata/catalog.json` with dataset information
3. Ensure CRS is EPSG:4326 or include CRS information

### Raster Data
1. Place GeoTIFF files in appropriate subdirectories
2. Update `metadata/catalog.json` with dataset information
3. Ensure proper georeferencing and CRS information

## Data Sources

### Free & Open Geospatial Data

#### Satellite Imagery
- **Sentinel-2**: https://scihub.copernicus.eu/
- **Landsat**: https://earthexplorer.usgs.gov/

#### Elevation
- **SRTM DEM**: https://earthexplorer.usgs.gov/
- **Copernicus DEM**: https://spacedata.copernicus.eu/

#### Land Cover
- **ESA WorldCover**: https://worldcover2021.esa.int/
- **Copernicus CORINE**: https://land.copernicus.eu/

#### Vector Data
- **OpenStreetMap**: https://www.geofabrik.de/
- **GADM**: https://gadm.org/
- **Natural Earth**: https://www.naturalearthdata.com/

#### Hydrology
- **HydroSHEDS**: https://www.hydrosheds.org/

## License
Sample data provided is for demonstration purposes. Please check individual dataset licenses for real-world use.
