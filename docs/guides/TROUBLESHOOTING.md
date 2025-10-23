# Troubleshooting Guide 🔧

## Common Issues and Solutions

---

## Issue 1: Queries Take Too Long ⏱️

### Symptoms
- Query takes 30-60 seconds to respond
- "Processing..." message shows for a long time
- Browser seems to hang

### Why This Happens
1. **DeepSeek API latency** (15-30 seconds per call)
2. **Complex spatial queries** in PostGIS (5-15 seconds)
3. **Network delays** (1-5 seconds)
4. **Large result sets** (thousands of features)

### Solutions

#### Short-term (For Users)
**Ask simpler questions first:**
- ✅ "Show me all hospitals" (fast - simple SELECT)
- ✅ "Find toilets" (fast - simple SELECT)
- ❌ "Which transport stops have most restaurants nearby" (slow - complex aggregation)

**Add limits to queries:**
- ✅ "Show me the top 10 transport stops with most restaurants"
- ✅ "Find 5 hospitals near Alexanderplatz"

#### Long-term (For Developers)
1. **Add caching** - Cache DeepSeek responses for common queries
2. **Add loading indicator** - Show progress bar
3. **Add query timeout** - Cancel after 60 seconds
4. **Optimize PostGIS** - Add more spatial indexes
5. **Use faster LLM** - Consider Claude or GPT-4 (faster than DeepSeek)

---

## Issue 2: "Query Missing Geometry Column" Error ❌

### Symptoms
```
Error: Spatial query failed: Query missing geometry column 'geometry'
```

### Why This Happens
When you ask **aggregation questions** like:
- "Which transport stops have the most restaurants?"
- "Count hospitals by district"
- "Show me areas with highest restaurant density"

DeepSeek generates SQL with `GROUP BY` and `COUNT()`, which **drops the geometry column**.

**Bad SQL (missing geometry):**
```sql
SELECT name, COUNT(*) as count
FROM vector.osm_transport_stops ts, vector.osm_restaurants r
WHERE ST_DWithin(ts.geometry::geography, r.geometry::geography, 200)
GROUP BY name  -- ❌ Geometry is lost!
```

**Good SQL (keeps geometry):**
```sql
SELECT ts.name, ts.geometry, COUNT(r.osm_id) as count
FROM vector.osm_transport_stops ts
LEFT JOIN vector.osm_restaurants r
  ON ST_DWithin(ts.geometry::geography, r.geometry::geography, 200)
GROUP BY ts.osm_id, ts.name, ts.geometry  -- ✅ Geometry preserved!
ORDER BY count DESC
LIMIT 20
```

### Solution
**I've already fixed this!** The DeepSeek prompt has been updated to always include geometry in GROUP BY queries.

### How to Phrase Aggregation Questions

**✅ GOOD - Will work now:**
- "Which transport stops have the most restaurants nearby?"
- "Show me the top 10 hospitals with most pharmacies around them"
- "Find parks with the highest number of restaurants within 500m"

**⚠️ BE SPECIFIC:**
- Add "top 10" or "top 20" to limit results
- Specify distance ("within 200m", "within 500m")
- Use "nearby" or "around" for spatial context

---

## Issue 3: No Results Returned 🤷

### Symptoms
- Query runs but map is empty
- "Found 0 results" message
- No error, just no data

### Why This Happens
1. **Too restrictive query** - No features match your criteria
2. **Wrong location** - Landmark doesn't exist or misspelled
3. **Distance too small** - Nothing within that radius

### Solutions

**Check your assumptions:**
```bash
# Verify data exists
docker exec geoassist_postgis psql -U geoassist -d geoassist \
  -c "SELECT COUNT(*) FROM vector.osm_hospitals"
```

**Start broad, then narrow:**
1. First: "Show me all hospitals" (verify data exists)
2. Then: "Find hospitals near Alexanderplatz" (add location filter)
3. Finally: "Find hospitals within 500m of Alexanderplatz" (add distance)

**Increase distance if needed:**
- Instead of "within 100m" try "within 500m"
- Instead of "within 1km" try "within 2km"

---

## Issue 4: Server Not Responding 🔌

### Symptoms
- Can't access http://localhost:8000
- "Connection refused" error
- Page won't load

### Solution

**Check if server is running:**
```bash
curl http://localhost:8000/api/health
```

**If not running, start it:**
```bash
cd "/Users/skfazlarabby/projects/AI Geospatial"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Check if port 8000 is blocked:**
```bash
lsof -i :8000
# If something else is using port 8000, kill it:
kill -9 <PID>
```

---

## Issue 5: Database Connection Error 🗄️

### Symptoms
```
Error: Database connection failed
status: "degraded"
database: "disconnected"
```

### Solution

**Check if PostGIS is running:**
```bash
docker ps | grep postgis
```

**If not running, start it:**
```bash
docker start geoassist_postgis
```

**Verify connection:**
```bash
docker exec geoassist_postgis psql -U geoassist -d geoassist -c "SELECT 1"
```

**Check credentials in .env:**
```bash
cat .env | grep POSTGRES
```

Should show:
```
POSTGRES_USER=geoassist
POSTGRES_PASSWORD=geoassist_password
POSTGRES_DB=geoassist
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
```

---

## Issue 6: DeepSeek API Error 🤖

### Symptoms
```
Error: DeepSeek API request failed
Error: API key invalid
```

### Solution

**Check API key:**
```bash
cat .env | grep DEEPSEEK_API_KEY
```

**Test API key:**
```bash
curl -X POST "https://api.deepseek.com/v1/chat/completions" \
  -H "Authorization: Bearer sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"test"}]}'
```

**Get new API key:**
- Visit: https://platform.deepseek.com
- Create account / login
- Generate new API key
- Update `.env` file

---

## Best Practices ✅

### 1. **Start Simple**
Always test with simple queries first:
- "Show me all hospitals"
- "Find all parks"
- "Where are the schools?"

### 2. **Add Complexity Gradually**
Build up your queries:
1. Simple: "Show me hospitals"
2. Location: "Show me hospitals in Berlin"
3. Spatial: "Find hospitals near Alexanderplatz"
4. Distance: "Find hospitals within 2km of Alexanderplatz"

### 3. **Use Limits**
For aggregation queries, always add a limit:
- "Show me the **top 10** transport stops with most restaurants"
- "Find **5** parks with most restaurants nearby"

### 4. **Be Specific with Distance**
Always specify units:
- ✅ "within 500m" or "within 2km"
- ❌ "nearby" (ambiguous)

### 5. **Use Known Landmarks**
Berlin landmarks that work well:
- Alexanderplatz
- Brandenburg Gate (Brandenburger Tor)
- Reichstag
- TV Tower (Fernsehturm)
- Potsdamer Platz
- Checkpoint Charlie

---

## Query Performance Guide 🚀

### Fast Queries (< 5 seconds)
- Simple SELECT: "Show me all hospitals"
- Single table: "Find all parks"
- With limit: "Show me 10 restaurants"

### Medium Queries (5-15 seconds)
- Proximity search: "Find toilets near transport stops"
- Distance filter: "Show hospitals within 2km of Alexanderplatz"
- Simple join: "Find pharmacies near schools"

### Slow Queries (15-60 seconds)
- Aggregation: "Which stops have most restaurants nearby?"
- Complex spatial: "Find areas with good service coverage"
- Multiple joins: "Show hospitals, pharmacies, AND schools in one area"

---

## Debug Mode 🐛

### Enable Detailed Logging

Add to `.env`:
```
LOG_LEVEL=DEBUG
API_DEBUG=True
```

### Check API Logs
The server shows all SQL queries being executed. Look for:
```
INFO:     127.0.0.1:52940 - "POST /api/query HTTP/1.1" 200 OK
SQL execution failed, falling back to GeoPandas: ...
```

### Test Queries Directly

**Test in psql:**
```bash
docker exec -it geoassist_postgis psql -U geoassist -d geoassist
```

Then run:
```sql
-- Test simple query
SELECT COUNT(*) FROM vector.osm_hospitals;

-- Test spatial query
SELECT COUNT(*) FROM vector.osm_toilets t, vector.osm_transport_stops ts
WHERE ST_DWithin(t.geometry::geography, ts.geometry::geography, 100);
```

---

## Getting Help 🆘

If you're still stuck:

1. **Check the logs**
   - Server terminal output
   - Browser console (F12)

2. **Verify data**
   - Run: `python scripts/verify_berlin_data.py`

3. **Test API directly**
   - Visit: http://localhost:8000/docs
   - Try `/api/health` endpoint

4. **Restart everything**
   ```bash
   # Restart Docker
   docker restart geoassist_postgis

   # Restart API server
   # Ctrl+C to stop, then:
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## Success Metrics ✅

**Your system is working correctly when:**
- ✅ Health check returns "healthy"
- ✅ Simple queries return in < 5 seconds
- ✅ Spatial queries return in < 15 seconds
- ✅ Results display on map
- ✅ Click markers shows attributes

---

**Last Updated:** October 19, 2025
**Version:** 1.0
