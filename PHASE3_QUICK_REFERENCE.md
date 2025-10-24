# Phase 3: Quick Reference Guide

## New Endpoints Summary

### Caching
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/cache/stats` | GET | View cache hit rate and statistics |
| `/api/cache/clear` | POST | Clear all cached queries |

### Batch Processing
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/batch-query` | POST | Execute 1-20 queries in parallel |

### Exporting
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/export/formats` | GET | List available export formats |
| `/api/export` | POST | Export query results to CSV/Shapefile/Excel/KML/GeoJSON |
| `/api/query-and-export` | POST | Execute query and export in one request |

### Analytics & Logging
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/logs/recent` | GET | View recent 50-1000 queries |
| `/api/logs/analytics` | GET | View performance metrics and statistics |
| `/api/logs/feedback/{id}` | POST | Submit user feedback for a query |
| `/api/logs/improvement-data` | GET | View all user feedback for model improvement |

---

## Common Use Cases

### 1. Cache a Query Result
```bash
# First call - executes query
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals in Berlin"}'

# Second call with same question - returns from cache (instant)
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals in Berlin"}'
```

### 2. Batch Process Multiple Queries
```bash
curl -X POST http://localhost:8000/api/batch-query \
  -H "Content-Type: application/json" \
  -d '[
    {"question": "Find hospitals in Berlin"},
    {"question": "Find pharmacies in Berlin"},
    {"question": "Find schools in Berlin"}
  ]'
```

### 3. Query and Export to CSV
```bash
curl -X POST "http://localhost:8000/api/query-and-export?export_format=csv" \
  -H "Content-Type: application/json" \
  -d '{"question": "Find restaurants by district"}' \
  --output restaurants.csv
```

### 4. Export to Shapefile
```bash
# First get the query result
QUERY=$(curl -s -X POST http://localhost:8000/api/query \
  -d '{"question": "Find hospitals in Berlin"}')

# Then export
curl -X POST "http://localhost:8000/api/export?format=shapefile" \
  -H "Content-Type: application/json" \
  -d "{\"data\": $(echo $QUERY | jq .data), \"result_type\": \"geojson\"}" \
  --output hospitals.shp
```

### 5. Get Analytics
```bash
curl http://localhost:8000/api/logs/analytics | jq '.'
```

### 6. Submit Feedback on Query
```bash
# First, get query ID from logs
QUERY_ID=42

# Submit positive feedback
curl -X POST "http://localhost:8000/api/logs/feedback/$QUERY_ID?rating=5&feedback_type=helpful&comment=Excellent%20results"

# Submit negative feedback
curl -X POST "http://localhost:8000/api/logs/feedback/$QUERY_ID?rating=2&feedback_type=incorrect&comment=Missing%20some%20results"
```

### 7. View Recent Queries
```bash
curl "http://localhost:8000/api/logs/recent?limit=20" | jq '.logs'
```

### 8. Get Improvement Data for Model Training
```bash
curl http://localhost:8000/api/logs/improvement-data | jq '.feedback'
```

---

## Export Format Details

### CSV Export
- Best for: Spreadsheets, data analysis
- Contains: All properties + WKT geometry
- Max size: 50 MB

```bash
curl -X POST "http://localhost:8000/api/export?format=csv" \
  -d '{"data": {...}, "result_type": "geojson"}' \
  --output data.csv
```

### Shapefile Export
- Best for: GIS software (ArcGIS, QGIS)
- Contains: Native geometries + all properties
- Max size: 100 MB
- **Note:** Creates .shp, .shx, .dbf, .prj files

```bash
curl -X POST "http://localhost:8000/api/export?format=shapefile" \
  -d '{"data": {...}, "result_type": "geojson"}' \
  --output data.shp
```

### Excel Export
- Best for: Business reports
- Contains: Formatted tables with proper headers
- Max size: 50 MB

```bash
curl -X POST "http://localhost:8000/api/export?format=excel" \
  -d '{"data": {...}, "result_type": "geojson"}' \
  --output data.xlsx
```

### GeoJSON Export
- Best for: Web maps, data interchange
- Contains: Original GeoJSON structure
- Max size: 100 MB

```bash
curl -X POST "http://localhost:8000/api/export?format=geojson" \
  -d '{"data": {...}, "result_type": "geojson"}' \
  --output data.geojson
```

### KML Export
- Best for: Google Earth, 3D visualization
- Contains: Placemarks with properties
- Max size: 50 MB

```bash
curl -X POST "http://localhost:8000/api/export?format=kml" \
  -d '{"data": {...}, "result_type": "geojson"}' \
  --output data.kml
```

---

## Performance Tips

### 1. Use Batch Queries for Multiple Queries
**Instead of:**
```bash
# 3 sequential requests = ~6 seconds
curl -X POST http://localhost:8000/api/query -d '{"question": "Find hospitals"}'
curl -X POST http://localhost:8000/api/query -d '{"question": "Find pharmacies"}'
curl -X POST http://localhost:8000/api/query -d '{"question": "Find schools"}'
```

**Do this:**
```bash
# 3 parallel requests = ~2 seconds
curl -X POST http://localhost:8000/api/batch-query \
  -d '[
    {"question": "Find hospitals"},
    {"question": "Find pharmacies"},
    {"question": "Find schools"}
  ]'
```

### 2. Leverage Cache for Repeated Queries
- Same question always returns from cache
- Cache hit time: <100ms
- Fresh queries: 1-5 seconds

### 3. Clear Cache When Data Changes
```bash
# After database updates
curl -X POST http://localhost:8000/api/cache/clear
```

### 4. Monitor Cache Hit Rate
```bash
curl http://localhost:8000/api/cache/stats | jq '.cache.hit_rate'
```

---

## Analytics Dashboard

### View Real-Time Metrics
```bash
curl http://localhost:8000/api/logs/analytics | jq '.' > analytics.json
```

**Key Metrics:**
- `total_queries` - Total executed
- `success_rate` - Percentage that succeeded
- `avg_execution_time` - Average query time
- `cache_hit_rate` - Percentage from cache
- `slowest_queries` - Top 5 slowest
- `top_errors` - Most common errors

### Sample Analytics Output
```json
{
  "total_queries": 1523,
  "successful_queries": 1456,
  "failed_queries": 67,
  "success_rate": 95.6,
  "avg_execution_time": 1.24,
  "cache_hits": 512,
  "cache_hit_rate": 33.6,
  "queries_by_type": {
    "spatial_query": 850,
    "stats": 673
  },
  "slowest_queries": [
    {"question": "Compare hospital and pharmacy density across all districts", "time": 5.2},
    {"question": "Find restaurants within 200m of parks", "time": 3.8}
  ],
  "top_errors": [
    {"error": "No data available for this location", "count": 45},
    {"error": "Invalid geometry", "count": 15}
  ]
}
```

---

## Feedback Integration for LLM Improvement

### Collect User Feedback
```bash
# After user reviews query results
curl -X POST "http://localhost:8000/api/logs/feedback/123" \
  -d "rating=4&feedback_type=helpful&comment=Results%20are%20accurate"
```

### Analyze Feedback
```bash
curl http://localhost:8000/api/logs/improvement-data | \
  jq '.feedback[] | select(.rating < 3)'
```

### Use Data to Improve Prompts
```bash
# Export low-rated queries to improve DeepSeek prompts
curl http://localhost:8000/api/logs/improvement-data | \
  jq '.feedback[] | select(.rating < 3) | .question' \
  > low_rated_queries.txt
```

---

## Environment Setup

### 1. Install Redis (Optional but Recommended)
```bash
# macOS
brew install redis

# Linux
sudo apt-get install redis-server

# Docker
docker run -d -p 6379:6379 redis:latest
```

### 2. Configure Environment Variables
```bash
# .env file
CACHE_TYPE=redis
REDIS_URL=redis://localhost:6379/0
CACHE_TTL_SECONDS=3600
QUERY_LOG_DIR=logs/queries
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run API
```bash
python -m uvicorn app.main:app --reload
```

---

## Troubleshooting

### Cache Not Working
```bash
# Check Redis connection
redis-cli ping
# Should return: PONG

# Check cache stats
curl http://localhost:8000/api/cache/stats

# Clear cache and retry
curl -X POST http://localhost:8000/api/cache/clear
```

### Export Fails
```bash
# Reduce data size
curl -X POST "http://localhost:8000/api/export?format=csv" \
  -d '{"data": {...large...}, "result_type": "geojson"}'

# Use a smaller query instead
curl -X POST "http://localhost:8000/api/query-and-export?export_format=csv" \
  -d '{"question": "Find hospitals in Mitte district"}'
```

### Slow Batch Queries
```bash
# Check what's slow
curl http://localhost:8000/api/logs/analytics | \
  jq '.slowest_queries'

# Reduce batch size (max 20)
curl -X POST http://localhost:8000/api/batch-query -d '[...10 queries...]'
```

### Logs Not Being Created
```bash
# Check logs directory
ls -la logs/queries/

# Verify permissions
mkdir -p logs/queries
chmod 755 logs/queries

# Check database
sqlite3 logs/queries/query_log.db "SELECT COUNT(*) FROM query_logs;"
```

---

## API Response Examples

### Batch Query Response
```json
{
  "status": "success",
  "total_queries": 3,
  "successful": 3,
  "failed": 0,
  "from_cache": 1,
  "statistics": {
    "total_execution_time": 1.8,
    "avg_query_time": 0.6,
    "cache_hit_rate": 0.33
  },
  "results": [
    {
      "success": true,
      "query": "Find hospitals",
      "result_type": "geojson",
      "execution_time": 1.2,
      "_from_cache": false
    },
    {
      "success": true,
      "query": "Find hospitals",
      "result_type": "geojson",
      "execution_time": 0.05,
      "_from_cache": true
    }
  ]
}
```

### Cache Stats Response
```json
{
  "status": "success",
  "cache": {
    "type": "redis",
    "connected": true,
    "used_memory_mb": 12.5,
    "keys": 156,
    "hits": 512,
    "misses": 321,
    "hit_rate": 0.615
  }
}
```

### Analytics Response
```json
{
  "status": "success",
  "analytics": {
    "total_queries": 1523,
    "successful_queries": 1456,
    "failed_queries": 67,
    "success_rate": 95.6,
    "avg_execution_time": 1.24,
    "cache_hits": 512,
    "cache_hit_rate": 33.6,
    "queries_by_type": {"spatial_query": 850, "stats": 673},
    "slowest_queries": [...],
    "top_errors": [...]
  }
}
```

---

## Summary Table

| Feature | Endpoint | Time Saved | Use When |
|---------|----------|-----------|----------|
| **Caching** | `/api/query` | 90-95% | Repeated queries |
| **Batch Queries** | `/api/batch-query` | 60-70% | Multiple queries at once |
| **Export** | `/api/export` | N/A | Share results with others |
| **Analytics** | `/api/logs/*` | 50-70% | Find slow/failed queries |

---

**Happy querying! 🚀**
