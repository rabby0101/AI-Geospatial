# Setup Guide: Cognitive Geospatial Assistant API

Complete guide to set up and run the API with real geospatial data.

---

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL with PostGIS extension
- ~10 GB disk space for sample datasets
- Internet connection for data downloads

---

## 🔧 Step 1: Environment Setup

### Create Conda Environment

```bash
conda create -n geoassist python=3.11
conda activate geoassist
```

### Install Dependencies

```bash
# Core geospatial libraries
pip install fastapi uvicorn[standard]
pip install geopandas shapely rasterio fiona
pip install psycopg2-binary sqlalchemy

# Data access libraries
pip install planetary-computer pystac-client
pip install requests aiohttp

# Optional but recommended
pip install rioxarray xarray
pip install pyproj

# LLM integration
pip install openai  # Or your preferred LLM client
```

### Install PostgreSQL and PostGIS

**macOS (via Homebrew):**
```bash
brew install postgresql postgis
brew services start postgresql
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib postgis
sudo systemctl start postgresql
```

**Windows:**
Download PostgreSQL from https://www.postgresql.org/download/windows/
Enable PostGIS during installation or add it later.

---

## 🗄️ Step 2: Database Setup

### Initialize Database

```bash
# Run database setup script
python scripts/setup_database.py
```

This will:
- Create database `geoassist`
- Enable PostGIS extension
- Create schemas (vector, raster, metadata)
- Create tables for OSM, admin boundaries, etc.
- Create spatial indices

### Verify Database

```bash
psql -d geoassist -c "SELECT PostGIS_Version();"
```

Should output PostGIS version information.

---

## 📥 Step 3: Download Sample Data

### Option A: Automatic Ingestion (Recommended)

```bash
# Download and ingest data for Berlin
python scripts/ingest_data.py
```

This will download:
- OSM buildings, hospitals, roads for Berlin
- GADM administrative boundaries for Germany
- ESA WorldCover land cover tile

**Expected time**: 5-15 minutes depending on connection speed

### Option B: Manual Download

```python
from app.utils.data_loaders import OSMLoader, GADMLoader, CopernicusLoader

# 1. Download OSM data
osm = OSMLoader()
berlin_bbox = (13.088, 52.338, 13.761, 52.675)
hospitals = osm.query_overpass(berlin_bbox, ['hospital'])
hospitals.to_file('data/vector/osm/berlin_hospitals.geojson', driver='GeoJSON')

# 2. Download admin boundaries
gadm = GADMLoader()
germany = gadm.load_boundaries('DEU', admin_level=1)
germany.to_file('data/vector/gadm/germany_states.gpkg', driver='GPKG')

# 3. Download land cover
copernicus = CopernicusLoader()
copernicus.download_worldcover('N51E013', year=2021)
```

---

## ⚙️ Step 4: Configure Environment

### Create `.env` file

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=geoassist

# DeepSeek API
DEEPSEEK_API_KEY=your_key_here

# Optional API keys (all free)
OPENTOPO_API_KEY=your_key_here  # Free from opentopography.org
```

### Update `config/settings.yaml`

```yaml
database:
  url: postgresql://postgres:postgres@localhost:5432/geoassist

data:
  vector_dir: data/vector
  raster_dir: data/raster
  metadata_dir: data/metadata

api:
  host: 0.0.0.0
  port: 8000

llm:
  provider: deepseek
  model: deepseek-chat
  temperature: 0.1
```

---

## 🚀 Step 5: Run the API

### Start the server

```bash
cd /path/to/AI\ Geospatial
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Test the API

**Open browser**: http://localhost:8000/docs

**Try a query**:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Find all hospitals in Berlin within 1 km of rivers"}'
```

---

## 📊 Step 6: Verify Data Loaded

### Check database contents

```bash
psql -d geoassist
```

```sql
-- Check loaded datasets
SELECT * FROM metadata.dataset_catalog;

-- Count features
SELECT COUNT(*) FROM vector.osm_hospitals;
SELECT COUNT(*) FROM vector.osm_buildings;
SELECT COUNT(*) FROM vector.admin_boundaries;

-- Spatial query example
SELECT name, ST_AsText(geometry)
FROM vector.osm_hospitals
LIMIT 5;
```

---

## 🧪 Step 7: Test with Sample Queries

### Example 1: Hospitals in Berlin

```python
import requests

response = requests.post(
    'http://localhost:8000/query',
    json={
        'question': 'Show me all hospitals in Berlin'
    }
)

print(response.json())
```

### Example 2: Buildings near water

```python
response = requests.post(
    'http://localhost:8000/query',
    json={
        'question': 'Find residential buildings within 500m of rivers in Berlin'
    }
)
```

### Example 3: Administrative analysis

```python
response = requests.post(
    'http://localhost:8000/query',
    json={
        'question': 'Which German states have the most hospitals?'
    }
)
```

---

## 📂 Directory Structure After Setup

```
AI Geospatial/
├── app/
│   ├── main.py
│   ├── routes/
│   └── utils/
│       └── data_loaders/
│           ├── osm_loader.py
│           ├── sentinel_loader.py
│           ├── dem_loader.py
│           ├── gadm_loader.py
│           └── copernicus_loader.py
├── data/
│   ├── vector/
│   │   ├── osm/
│   │   │   ├── berlin_hospitals.geojson
│   │   │   ├── berlin_buildings.geojson
│   │   │   └── berlin_roads.geojson
│   │   └── gadm/
│   │       └── gadm41_DEU.gpkg
│   ├── raster/
│   │   ├── sentinel2/
│   │   ├── dem/
│   │   └── copernicus/
│   │       └── ESA_WorldCover_10m_2021_N51E013_Map.tif
│   └── metadata/
│       └── catalog.json
├── scripts/
│   ├── setup_database.py
│   └── ingest_data.py
├── .env
└── config/
    └── settings.yaml
```

---

## 🐛 Troubleshooting

### Issue: PostGIS not found

```bash
# Check PostgreSQL extensions
psql -d geoassist -c "SELECT * FROM pg_available_extensions WHERE name = 'postgis';"

# If not installed
sudo apt-get install postgresql-XX-postgis-3  # Ubuntu
brew install postgis  # macOS
```

### Issue: Overpass API timeout

The free Overpass API has rate limits. Solutions:

1. Reduce bbox size
2. Add timeout parameter: `timeout=300`
3. Use Geofabrik downloads for larger areas

### Issue: Planetary Computer access

No authentication required! If failing:

```bash
pip install --upgrade planetary-computer pystac-client
```

### Issue: Out of memory

Raster files are large. For low-memory systems:

1. Use smaller bboxes
2. Downsample rasters
3. Process tiles separately

---

## 📈 Next Steps

1. **Add more regions**: Edit `scripts/ingest_data.py` to add London, Paris, etc.

2. **Ingest Sentinel-2**: Uncomment Sentinel ingestion in script

3. **Build web viewer**: Add Leaflet/MapLibre frontend

4. **Expand dataset catalog**: Add more data sources from `DATA_SOURCES.md`

5. **Optimize queries**: Add more spatial indices

6. **Deploy**: Use Docker for production deployment

---

## 🔗 Useful Commands

```bash
# Check database size
psql -d geoassist -c "SELECT pg_size_pretty(pg_database_size('geoassist'));"

# List all tables
psql -d geoassist -c "\dt vector.*"

# Export data
ogr2ogr -f GeoJSON output.geojson PG:"dbname=geoassist" -sql "SELECT * FROM vector.osm_hospitals"

# Backup database
pg_dump -d geoassist -f backup.sql

# Restore database
psql -d geoassist -f backup.sql
```

---

## 📚 Resources

- [PostGIS Documentation](https://postgis.net/documentation/)
- [GeoPandas User Guide](https://geopandas.org/en/stable/docs/user_guide.html)
- [Planetary Computer Catalog](https://planetarycomputer.microsoft.com/catalog)
- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)

---

**You're all set! Your Cognitive Geospatial Assistant is ready with real, free, open-source data.**
