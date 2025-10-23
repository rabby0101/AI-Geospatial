# Cognitive Geospatial Assistant API

An LLM-Integrated RESTful API for Interactive Geospatial Reasoning and Querying

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)
![PostGIS](https://img.shields.io/badge/PostGIS-3.3-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Overview

The Cognitive Geospatial Assistant API allows users to query and analyze geospatial datasets using natural language. It integrates **DeepSeek LLM** to translate natural-language questions into spatial operations and returns GeoJSON results.

### Example Query

> "Find all flood zones within 2 km of hospitals in Berlin."

The system will:
1. Parse the query using DeepSeek API
2. Generate structured geospatial operations (buffer, spatial join)
3. Execute operations using PostGIS and GeoPandas
4. Return GeoJSON results with visualization

## Features

- **Natural Language Queries**: Ask geospatial questions in plain English
- **LLM-Powered Reasoning**: DeepSeek translates queries to spatial operations
- **Multiple Data Sources**: Vector (PostGIS, GeoJSON) and raster (GeoTIFF) support
- **Interactive Map Viewer**: Leaflet-based frontend for visualization
- **RESTful API**: Well-documented endpoints with FastAPI
- **Docker Support**: Easy deployment with docker-compose

## Architecture

```
User → FastAPI → DeepSeek Reasoning → Spatial Engine → Result (GeoJSON)
                                    ↓
                            PostGIS/GeoPandas/Rasterio
```

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI |
| LLM | DeepSeek API |
| Spatial Database | PostGIS |
| Vector Processing | GeoPandas, Shapely |
| Raster Processing | Rasterio, rioxarray |
| Frontend | Leaflet, HTML/JS |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for PostGIS)
- DeepSeek API Key

### Installation

1. Clone the repository:
```bash
cd "AI Geospatial"
```

2. Create a virtual environment:
```bash
conda create -n geoassist python=3.11
conda activate geoassist
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY
```

5. Start PostGIS database:
```bash
docker-compose up -d postgis
```

6. Run the API:
```bash
python -m uvicorn app.main:app --reload
```

7. Open your browser:
- Frontend: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Usage

### Using the Web Interface

1. Navigate to http://localhost:8000
2. Enter a natural language query in the text area
3. Click "Analyze" to process the query
4. View results on the interactive map

### Using the API

#### Query Endpoint

```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals within 2 km of flood zones in Berlin"}'
```

Response:
```json
{
  "success": true,
  "query": "Find hospitals within 2 km of flood zones",
  "result_type": "geojson",
  "data": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "metadata": {
    "count": 3,
    "crs": "EPSG:4326"
  },
  "execution_time": 1.45
}
```

#### List Available Datasets

```bash
curl http://localhost:8000/api/datasets
```

#### Health Check

```bash
curl http://localhost:8000/api/health
```

## Example Queries

### Medical & Healthcare
- "Find all hospitals and clinics within 1km of each other in Mitte district"
- "Show doctors, dentists, and pharmacies near me"
- "Which district has the best hospital accessibility?"
- "Find veterinary clinics near public transport"

### Education & Recreation
- "Show universities near public transport stops"
- "Find libraries within 500m of schools"
- "List all recreation facilities (gyms, museums, theaters) in Charlottenburg"
- "Which parks are within walking distance of residential areas?"

### Commerce & Services
- "Find ATMs near supermarkets"
- "Show banks in Mitte district"
- "List all post offices within 1km of shopping centers"
- "Find ATM and bank locations near me"

### Urban Analysis
- "Show all amenities by district"
- "Find areas with highest concentration of medical facilities"
- "Identify underserved areas with few restaurants or cafes"

### Environmental Analysis
- "Show forests and water bodies in relation to residential areas"
- "Find parks with nearby forests"

### Change Detection (with raster data)
- "Find areas where NDVI decreased between 2018 and 2024"
- "Show vegetation loss in urban areas"

## Project Structure

```
project/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── routes/
│   │   └── query.py           # API endpoints
│   ├── utils/
│   │   ├── deepseek.py        # DeepSeek integration
│   │   ├── spatial_engine.py  # Geospatial operations
│   │   └── database.py        # PostGIS connection
│   └── models/
│       └── query_model.py     # Pydantic models
├── data/
│   ├── vector/                # Vector datasets
│   ├── raster/                # Raster datasets
│   └── metadata/
│       └── catalog.json       # Dataset catalog
├── frontend/
│   └── index.html            # Leaflet map viewer
├── tests/                    # Test suite
├── config/
│   └── settings.yaml         # Configuration
├── docker-compose.yml        # Docker setup
├── requirements.txt          # Python dependencies
└── README.md
```

## Documentation

Comprehensive documentation is available in the `docs/` directory:

### 📚 User Guides (`docs/guides/`)
- **[Quick Start Guide](docs/guides/QUICKSTART.md)** - Get started quickly
- **[Setup Guide](docs/guides/SETUP_GUIDE.md)** - Detailed installation instructions
- **[NDVI Quick Start](docs/guides/NDVI_QUICK_START.md)** - Working with NDVI raster data
- **[Troubleshooting](docs/guides/TROUBLESHOOTING.md)** - Common issues and solutions

### 🔧 Implementation Details (`docs/implementation/`)
- **[Implementation Plan](docs/implementation/IMPLEMENTATION_PLAN.md)** - Project architecture & design
- **[NDVI Implementation](docs/implementation/README_NDVI_IMPLEMENTATION.md)** - Raster data processing
- **[Performance Improvements](docs/implementation/PERFORMANCE_IMPROVEMENTS.md)** - Optimization strategies
- **[Sentinel-2 Results](docs/implementation/REAL_SENTINEL2_RESULTS.md)** - Real satellite data analysis

### 📊 Development Reports (`docs/development/`)
- **[Phase 1 NDVI Complete](docs/development/PHASE1_NDVI_COMPLETE.md)** - NDVI feature completion
- **[Phase 1 Test Report](docs/development/PHASE1_TEST_REPORT.md)** - Testing results
- **[Integration Success](docs/development/INTEGRATION_SUCCESS.md)** - Backend integration
- **[UI Integration](docs/development/UI_INTEGRATION_COMPLETE.md)** - Frontend integration
- **[Berlin OSM Integration](docs/development/BERLIN_OSM_INTEGRATION_SUMMARY.md)** - OSM data loading

### 📁 Other Resources
- **[Data Sources](docs/DATA_SOURCES.md)** - Information about available datasets

## Available Datasets

### Vector Data - OSM (23 Datasets, ~45,000+ features)

#### Original Amenities (10)
- `osm_hospitals` - Hospital locations
- `osm_pharmacies` - Pharmacy locations
- `osm_doctors` - Doctor practices
- `osm_dentists` - Dental clinics
- `osm_clinics` - Medical clinics & urgent care
- `osm_veterinary` - Veterinary services
- `osm_schools` - School locations
- `osm_universities` - Universities & colleges
- `osm_libraries` - Libraries & cultural centers
- `osm_restaurants` - Restaurant locations

#### Education & Recreation (5)
- `osm_museums` - Museums & galleries
- `osm_theatres` - Theaters & cinemas
- `osm_gyms` - Sports centers & fitness facilities
- `osm_parks` - Parks & leisure areas
- `osm_transport_stops` - Bus/tram/subway stops

#### Commerce & Services (4)
- `osm_supermarkets` - Grocery stores & supermarkets
- `osm_banks` - Banks & financial institutions
- `osm_atm` - ATM locations
- `osm_post_offices` - Postal services

#### Infrastructure & Utilities (3)
- `osm_fire_stations` - Fire stations
- `osm_police_stations` - Police stations
- `osm_parking` - Parking areas

#### Natural Features (2)
- `osm_forests` - Forest areas & woodlands
- `osm_water_bodies` - Lakes, rivers, water surfaces

#### Administrative (1)
- `osm_districts` - Berlin district boundaries

**Coverage**: Berlin, Germany only (13.08-13.76°E, 52.33-52.67°N)

### Raster Data
- **Sentinel-2 NDVI (2018-2024)**: Real vegetation indices from ESA Copernicus
  - `berlin_ndvi_20180716.tif` (66 MB, 10m resolution)
  - `berlin_ndvi_20240721.tif` (57 MB, 10m resolution)
  - Use for vegetation change detection & analysis

For additional data:
- [Sentinel-2](https://scihub.copernicus.eu/) - Satellite imagery
- [Copernicus DEM](https://spacedata.copernicus.eu/) - Elevation data
- [ESA WorldCover](https://worldcover2021.esa.int/) - Land cover

## Development

### Running Tests

```bash
pytest
```

Run specific test types:
```bash
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
```

### Adding New Datasets

1. Add data files to `data/vector/` or `data/raster/`
2. Update `data/metadata/catalog.json`
3. Optionally load into PostGIS using the API

### API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Docker Deployment

Deploy the entire stack with Docker:

```bash
docker-compose up -d
```

This starts:
- PostGIS database (port 5432)
- FastAPI application (port 8000)

## Configuration

Edit `config/settings.yaml` or `.env` to configure:
- Database connection
- DeepSeek API settings
- CORS origins
- Data directories

## Troubleshooting

### Database Connection Failed

```bash
# Check if PostGIS is running
docker-compose ps

# View database logs
docker-compose logs postgis

# Restart database
docker-compose restart postgis
```

### DeepSeek API Errors

- Verify your API key in `.env`
- Check API quota/limits
- Review logs for detailed error messages

### Import Errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## Research Contributions

This project provides:
1. Framework for LLM-driven geospatial reasoning
2. Benchmark for natural-language to spatial-query translation
3. Integration pattern for DeepSeek with geospatial data
4. Reproducible API and dataset catalog

## Roadmap

- [ ] Add temporal filtering ("between 2018-2024")
- [ ] Implement user feedback learning
- [ ] Support for more raster operations
- [ ] Multi-language support
- [ ] Vector tile serving for large datasets
- [ ] Query history and saved queries

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Citation

If you use this project in your research, please cite:

```
@software{geoassist2025,
  title={Cognitive Geospatial Assistant API},
  author={Sk Fazla Rabby},
  year={2025},
  url={https://github.com/yourusername/geoassist}
}
```

## Author

**Sk Fazla Rabby**
MSc in Geodesy and Geoinformation Science
Focus: AI-driven geospatial data integration and analysis

## Acknowledgments

- DeepSeek for LLM capabilities
- PostGIS for spatial database
- FastAPI framework
- Leaflet for mapping
- OpenStreetMap for sample data

---

For questions or issues, please open a GitHub issue or contact the author.
