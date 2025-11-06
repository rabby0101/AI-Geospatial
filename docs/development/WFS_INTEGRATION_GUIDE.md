# WFS Integration Guide: Wasserschutzgebiete (Water Protection Areas)

## Overview

This document describes the integration of Water Protection Areas data from Berlin's GDI (Geodaten Dienste Infrastruktur) WFS service into the Geospatial Assistant application.

**Source**: https://gdi.berlin.de/services/wfs/wsg

**Dataset**: Wasserschutzgebiete (Water Protection Areas)
- **Features**: 46 water protection zones
- **Coverage**: Berlin, Germany
- **Geometry**: MultiPolygon
- **CRS**: EPSG:4326 (WGS84)
- **Size**: ~1.1 MB GeoJSON

## Setup Instructions

### 1. Download Data from WFS

```bash
python scripts/download_wasserschutzgebiete.py
```

**Output**: `data/vector/wfs/berlin_wasserschutzgebiete.geojson`

**Details**:
- Queries the WFS GetCapabilities endpoint
- Downloads the `wsg:wsg` feature type
- Converts to GeoJSON and WGS84 (EPSG:4326)
- Validates and saves locally

### 2. Load into PostGIS

```bash
python scripts/load_wasserschutzgebiete.py
```

**Details**:
- Loads GeoJSON into PostGIS table: `vector.wasserschutzgebiete`
- Creates spatial GiST index on geometry column
- Validates data integrity
- Reports statistics and bounds

### 3. Auto-Discovery

The application's auto-discovery system will automatically:
1. Detect the new `vector.wasserschutzgebiete` table
2. Generate table descriptions in schema cache
3. Make available for natural language queries

**Note**: Table descriptions are pre-populated in `data/metadata/table_descriptions.json`

## Data Schema

### Table: `vector.wasserschutzgebiete`

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Unique identifier (e.g., `wsg.05_02`) |
| `schluessel` | VARCHAR | Key code (e.g., `05_02`) |
| `wasserwerk` | VARCHAR | Water utility/waterworks name |
| `gebietsnr` | VARCHAR | Area number (e.g., `5800_01`) |
| `zone` | VARCHAR | Protection zone classification (I, II, III, etc.) |
| `verordnung` | VARCHAR | Regulation/ordinance name |
| `datum` | DATE | Date of designation |
| `gvbl` | VARCHAR | Official gazette reference |
| `veror_link` | VARCHAR | Link to regulation document |
| `ae_datum` | DATE | Last amendment date |
| `ae_gvbl` | VARCHAR | Amendment gazette reference |
| `geometry` | GEOMETRY | MultiPolygon boundary |

## Query Examples

### 1. Find water protection areas

```
"Show all water protection areas in Berlin"
"What are the water protection zones?"
```

### 2. Find water protection areas near locations

```
"Which water protection areas are near Mitte?"
"Show water protection areas around the center of Berlin"
"Water protection zones within 5 km of Spandau"
```

### 3. Filter by waterworks

```
"Which water protection areas supply Spandau waterworks?"
"Show zone II protection areas"
"List all tier 2 water protection zones"
```

### 4. Spatial queries

```
"Are there water protection areas near hospitals?"
"Show water protection areas overlapping with forests"
"Water protection zones that intersect with parks"
```

## Technical Details

### Download Script Features
- **Multi-version WFS support**: Tries WFS 2.0.0, 1.1.0, 1.0.0 in sequence
- **GeoJSON conversion**: Automatic format translation
- **CRS validation**: Ensures EPSG:4326 output
- **Error handling**: Graceful fallbacks and detailed logging

### Load Script Features
- **Schema management**: Creates `vector` schema if not exists
- **Spatial indexing**: GiST index for efficient geometric queries
- **Data validation**: Verifies successful import with statistics
- **Environmental config**: Reads credentials from `.env` file
- **SQLAlchemy 2.0 compatible**: Uses `text()` for raw SQL

### Database Configuration

From `.env`:
```
POSTGRES_USER=geoassist
POSTGRES_PASSWORD=geoassist_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=geoassist
```

## Integration with Application

### API Discovery

The table is automatically discovered on application startup via `app/utils/auto_discovery.py`:

1. Scans `vector` schema for all PostGIS tables
2. Generates descriptions from metadata
3. Caches schema in `data/metadata/schema_cache.json`

### Query Processing

When a user queries for water protection areas:

1. **DeepSeek LLM** interprets natural language question
2. **SQL Generator** creates PostGIS query:
   ```sql
   SELECT * FROM vector.wasserschutzgebiete
   WHERE ST_DWithin(geometry, <location>, <distance>)
   ```
3. **Spatial Engine** executes and formats results as GeoJSON
4. **Frontend** displays on Leaflet map

### Example Query Flow

```
User: "Show water protection areas near hospitals"
  ↓
LLM: Identifies: hospitals (osm_hospitals) + water zones (wasserschutzgebiete)
  ↓
SQL Generator: Creates spatial join query
  ↓
PostGIS: Executes ST_DWithin proximity join
  ↓
Frontend: Displays overlapped results on map
```

## Monitoring

### Check Load Status

```bash
# List all tables in vector schema
psql -h localhost -p 5433 -U geoassist -d geoassist \
  -c "\dt vector.*"

# Count features
psql -h localhost -p 5433 -U geoassist -d geoassist \
  -c "SELECT COUNT(*) FROM vector.wasserschutzgebiete;"

# Show geographic bounds
psql -h localhost -p 5433 -U geoassist -d geoassist \
  -c "SELECT ST_Extent(geometry) FROM vector.wasserschutzgebiete;"
```

### Test Query via API

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show water protection areas"}'
```

## Troubleshooting

### WFS Download Fails

**Issue**: Connection timeout or XML parsing error
**Solution**:
- Check internet connectivity
- Verify WFS endpoint: `https://gdi.berlin.de/services/wfs/wsg`
- Check for WFS service maintenance

### PostGIS Load Fails

**Issue**: Database connection error
**Solution**:
- Verify `.env` credentials
- Check PostgreSQL is running: `psql -h localhost -p 5433 -U geoassist -c "SELECT version();"`
- Ensure `vector` schema creation permissions

**Issue**: Geometry column mismatch
**Solution**:
- The loader uses `geometry` column (PostGIS standard)
- When querying with GeoPandas, specify: `geom_col='geometry'`

### Table Not Discovered

**Issue**: Table doesn't appear in schema cache
**Solution**:
- Restart the FastAPI application to trigger auto-discovery
- Check logs for auto_discovery module
- Manually verify: `SELECT * FROM vector.wasserschutzgebiete LIMIT 1;`

## Performance Notes

### Index Status

```bash
# Check spatial index
psql -h localhost -p 5433 -U geoassist -d geoassist \
  -c "SELECT * FROM pg_stat_user_indexes WHERE relname LIKE '%wasserschutz%';"
```

### Query Optimization

For large queries, these optimizations apply:
- GiST spatial index on `geometry` column
- PostGIS bounding box filtering
- Connection pooling (max 5 connections)

### Typical Query Performance
- Simple geometry: < 50ms
- Proximity query (5km): 100-200ms
- Spatial join with other layers: 200-500ms

## Future Enhancements

### Phase 2: Additional WFS Sources
- Add more GDI Berlin WFS services
- Include historical data versions
- Add update mechanism for dynamic data

### Phase 3: Performance
- Partition large tables by district
- Implement result caching
- Add tile serving for visualization

## References

- **GDI Berlin**: https://gdi.berlin.de/
- **WFS Specification**: https://www.ogc.org/standards/wfs
- **PostGIS Manual**: https://postgis.net/docs/
- **Wasserschutzgebiete Info** (German): https://www.berlin.de/umwelt/

## Files Modified/Created

- ✅ `scripts/download_wasserschutzgebiete.py` - WFS download script
- ✅ `scripts/load_wasserschutzgebiete.py` - PostGIS loader script
- ✅ `data/metadata/table_descriptions.json` - Updated with new table
- ✅ Auto-created: `data/vector/wfs/berlin_wasserschutzgebiete.geojson` - Downloaded data
- ✅ Auto-created: `vector.wasserschutzgebiete` (PostGIS table) - Loaded data

---

**Last Updated**: 2025-10-29
**Status**: ✅ Integration Complete
