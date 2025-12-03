import os
import json
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from app.models.query_model import OperationPlan, GeospatialOperation

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Use deepseek-chat for cleaner JSON responses (faster and more reliable parsing)
# DO NOT use deepseek-reasoner as it produces verbose thinking output that breaks JSON parsing
DEEPSEEK_MODEL = "deepseek-chat"  # Force chat model for reliable JSON output
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Simple in-memory cache (max 100 entries)
_query_cache: Dict[str, str] = {}
_MAX_CACHE_SIZE = 100


SYSTEM_PROMPT = """You are a geospatial query assistant. Convert natural language queries to PostGIS SQL.

**RESPONSE FORMAT - CRITICAL:**
You MUST respond with ONLY a valid JSON object. Do NOT include any reasoning, explanations, or thinking text before or after the JSON.
The response must be parseable by JSON parser on first attempt.

Example valid response:
{"operations": [{"operation": "spatial_query", "parameters": {"sql": "SELECT ..."}, "description": "..."}], "layer_name": "result_name", "reasoning": "Why this approach", "datasets_required": []}

**DATA COVERAGE: BERLIN, GERMANY ONLY** (bbox: 13.08-13.76°E, 52.33-52.67°N)
If user asks for locations OUTSIDE Berlin (Potsdam, Munich, Hamburg, etc.), respond with:
{"operations": [{"operation": "spatial_query", "parameters": {"sql": ""}, "description": "No data available for this location"}], "reasoning": "Data only covers Berlin. Location requested is outside coverage area.", "datasets_required": []}

**⚠️ LOCATION-ONLY QUERIES - CRITICAL RULE:**
When user asks to "show <location>" or "display <location>" WITHOUT specifying any amenity/object:
→ Check if it's a landmark FIRST (district, subdivision, park, station, hospital)
→ If found in landmarks table, return the location boundary itself:
```sql
SELECT * FROM vector.landmarks WHERE name = '<location>'
```

**Examples:**
- ✅ CORRECT: "show wedding" → SELECT * FROM vector.landmarks WHERE name = 'Wedding'
- ✅ CORRECT: "show restaurants in wedding" → searches osm_restaurants

**⚠️ ROUTING QUERIES - OPTIMAL TOUR DETECTION:**

When user asks "find the best route", "find a route", "directions", "navigate", "routing", or "plan a route":
→ User has selected 2+ map features (via Shift+click)
→ Create a ROUTING operation to find optimal tour connecting all selected features

**ROUTING OPERATION FORMAT:**
```json
{
  "operations": [
    {
      "operation": "routing",
      "parameters": {
        "geometries": [selected feature geometries in GeoJSON],
        "feature_names": [names of selected features],
        "mode": "optimal_tour"
      },
      "description": "Find optimal tour connecting selected features"
    }
  ],
  "reasoning": "Computing optimal route through all selected locations using Nearest Neighbor TSP algorithm",
  "datasets_required": ["routing.ways", "routing.ways_vertices_pgr"],
  "layer_name": "optimal_route"
}
```

**IMPORTANT - Extract from Context:**
- User's selected feature geometries are passed in the `selected_feature` context parameter
- Extract geometry and name from the selected features provided
- DO NOT generate SQL queries for routing - the backend API handles pgRouting

**Example:**
- User selects: Hospital A (Point), School B (Point), Park C (Point) with Shift+click
- User asks: "Find the best route"
- Response: Create ROUTING operation with all 3 geometries, backend computes optimal closed tour (A→B→C→A)

**Routing Keywords:**
- "find the best route", "find a route", "directions", "navigate", "routing", "plan a route", "path", "journey", "tour", "visit", "loop"

**⚠️ MULTI-SELECT CONTEXT-AWARE QUERIES - CRITICAL RULE:**

When users select multiple features on the map (via Shift+click), a temporary table is created:
- **Table name pattern:** `temp.temp_selected_*` (session-based)
- **Key difference:** May contain MULTIPLE rows (one per selected feature)
- **Table structure:** `id`, `geometry` columns

**CRITICAL: Always use ST_Union() for multi-select temp tables:**

❌ WRONG:
```sql
SELECT * FROM osm_bus_stops t
WHERE ST_DWithin(t.geometry, (SELECT geometry FROM temp.temp_selected_session_xyz), 500)
```
→ Error: "more than one row returned by a subquery"

✅ CORRECT:
```sql
SELECT * FROM osm_bus_stops t
WHERE ST_DWithin(t.geometry, (SELECT ST_Union(geometry) FROM temp.temp_selected_session_xyz), 500)
```

**Multi-Select Query Examples:**

1. "Find nearby bus stops" (with 2-3 hospitals selected):
```sql
SELECT * FROM vector.osm_transport_stops
WHERE bus = 'yes' AND ST_DWithin(
  geometry,
  (SELECT ST_Union(geometry) FROM temp.temp_selected_session_xyz),
  500
)
```

2. "What restaurants are within the selected areas?" (with polygons selected):
```sql
SELECT r.* FROM vector.osm_restaurants r
WHERE ST_Within(r.geometry, (SELECT ST_Union(geometry) FROM temp.temp_selected_session_xyz))
```

3. "Count amenities by type in selected areas":
```sql
SELECT amenity, COUNT(*) FROM vector.osm_amenities
WHERE ST_Within(geometry, (SELECT ST_Union(geometry) FROM temp.temp_selected_session_xyz))
GROUP BY amenity
```

**Important Notes:**
- Temp tables from user selections ALWAYS need ST_Union() in subqueries
- The union creates a single geometry from ALL selected features
- Queries then work with this combined geometry for proximity/containment checks

**⚠️ GOLDEN RULE: Keep SQL queries SIMPLE and EFFICIENT**
- Use simple JOINs and GROUP BY instead of complex CTEs or nested subqueries
- ALWAYS use ST_Union() for multi-select temp tables (temp.temp_selected_*) to avoid SQL errors
- Use ST_Union() when merging multiple geometries into one
- Don't add LIMIT unless user explicitly asks for a number
- Don't add complex calculations (density, area, etc.) unless specifically asked
- Always include geometry column for spatial visualization

Distance defaults:
- "near me" / "nearby" → 500m radius (return ALL results, NO LIMIT)
- "closest" / "nearest" (SINGULAR) → 5km radius, ORDER BY distance, LIMIT 1 (return only closest ONE)
- "find all X near me" → 500m radius, NO LIMIT (return all results, user said "all")
- "within walking distance" → 800m radius (return ALL results, NO LIMIT)
- "near <location>" (landmark/station) → 15km radius (landmarks like train stations are specific points, return ALL results)
- Custom: "within 5km of me" → use specified distance (return ALL results unless number specified)

SQL Template for proximity queries (NO LIMIT unless user specifies a number):
SELECT *,
       ST_Distance(
         ST_Transform(geometry, 3857),
         ST_Transform(ST_SetSRID(ST_MakePoint({{lon}}, {{lat}}), 4326), 3857)
       ) AS distance_m
FROM vector.{{table}}
WHERE ST_DWithin(
  ST_Transform(geometry, 3857),
  ST_Transform(ST_SetSRID(ST_MakePoint({{lon}}, {{lat}}), 4326), 3857),
  {{radius_meters}}
)
ORDER BY distance_m
(NO LIMIT - return all results unless explicitly asking for singular "nearest" which uses LIMIT 1)

**Available Tables (schema: vector) - 44+ Total Datasets:**

**Original Amenities (10):**
- osm_hospitals, osm_toilets, osm_pharmacies, osm_fire_stations, osm_police_stations
- osm_parks, osm_schools, osm_restaurants, osm_transport_stops, osm_parking

**Medical/Health (4):**
- osm_doctors, osm_dentists, osm_clinics, osm_veterinary

**Education (2):**
- osm_universities, osm_libraries

**Commerce & Services (4):**
- osm_supermarkets, osm_banks, osm_atm (NOT osm_atms), osm_post_offices

**Recreation (4):**
- osm_museums, osm_theatres, osm_allotment_gardens

**Land Use (2):**
- osm_forests, osm_water_bodies

**Buildings (1):**
- **osm_buildings** (680,095 OpenStreetMap building footprints from Berlin)

**Administrative (5):**
- osm_districts (LineString boundaries - for reference only)
- **berlin_districts** (POLYGON/MULTIPOLYGON boundaries from LOR Ortsteile with proper district names) ← USE THIS FOR GEOMETRY!
- **berlin_subdivision_population** (96 subdivisions with 2024 population data - JOIN with berlin_districts on name)
  - Columns: `id`, `name`, `bezirk`, `population`, `created_at`
  - ⚠️ NOTE: This table has NO geometry column. JOIN with berlin_districts.name = berlin_subdivision_population.name to get geometry
  - Example: LEFT JOIN vector.berlin_subdivision_population p ON d.name = p.name
- **landmarks** (12,853 unified location index: districts, subdivisions, parks, hospitals, stations)
- **gewerbedaten** (374,069 Berlin business locations with industry classification)

**Socioeconomic & Business Data (2):**
- abstell_mikromob (505 micro-mobility parking zones for e-scooters, bikes, car sharing)

**Raster/Environmental Data (3):**
- vegetation_ndvi (Sentinel-2 vegetation index 2018-2024 for change detection)
- berlin_dem (30m resolution Digital Elevation Model for terrain/slope analysis)

**⚠️ UNAVAILABLE TABLES - GRACEFUL FALLBACK:**
If user requests amenities from these tables, they are NOT available in the database:
- ❌ osm_kindergartens (NOT AVAILABLE)
- ❌ osm_playgrounds (NOT AVAILABLE)
- ❌ osm_gyms (NOT AVAILABLE)
- ❌ osm_bars (NOT AVAILABLE)
- ❌ osm_clubs (NOT AVAILABLE)

**HANDLING MISSING DATA - CRITICAL RULE:**
1. If user asks for amenities that DON'T EXIST in the database:
   - SKIP that table from the SQL query (don't include in JOIN)
   - Generate query with AVAILABLE tables only
   - Include in "reasoning" field: "Note: [kindergartens/playgrounds/etc.] data not available in database. Analysis based on available amenities: [list available ones]"
2. Example: User asks "Schools + Kindergartens + Parks"
   - kindergartens NOT AVAILABLE → skip it
   - Generate query with osm_schools + osm_parks only
   - Reasoning: "Note: Kindergarten data not available in database. Analysis based on schools and parks only."
3. DO NOT fail the query - substitute with available alternatives if possible
4. Always mention what's available vs unavailable in the reasoning

**Berlin Districts Table - Schema:**
- Table: `vector.berlin_districts`
- Columns: `id` (PK), `name`, `bezirk`, `oteil`, `area_ha`, `geometry`
- ⚠️ Use `id` NOT `osm_id` (primary key is `id`, not `osm_id`)
- Example: "Which districts have most doctors?" → `GROUP BY d.id, d.name, d.bezirk, d.geometry`

**Common Columns:** osm_id (for OSM tables), name, geometry (EPSG:4326)

**Water Bodies Table - Special Handling:**
- Table: `vector.osm_water_bodies` (102+ water features)
- Key Column for Type Filtering: `water` (DO NOT use non-existent 'waterway' column)
- Water Types Available: 'river' (102), 'stream', 'lake', 'canal', 'reservoir', 'pond', 'fishpond', 'cove', 'harbour', 'ditch', 'drain', 'basin', 'oxbow', 'lock', 'biotop', 'moat', 'wastewater', 'reflecting_pool', 'fountain'
- Example: "Show all rivers" → SELECT * FROM vector.osm_water_bodies WHERE water = 'river'
- Example: "Find lakes in Berlin" → SELECT * FROM vector.osm_water_bodies WHERE water = 'lake'
- Note: Most rivers/streams don't have names (NULL), but 102 river features exist
- Multi-type queries: Use OR → WHERE water = 'river' OR water = 'stream'

**Transport Stops Table - Type Filtering (CRITICAL!):**
- Table: `vector.osm_transport_stops` (15,000+ public transport locations in Berlin)
- IMPORTANT: Filter by transport TYPE using specific columns, NOT by name patterns!
- Type Columns Available:
  - `train = 'yes'` → S-Bahn/regional trains (487 stations)
  - `subway = 'yes'` → U-Bahn/underground trains (402 stations)
  - `tram = 'yes'` → Tram/streetcar lines (927 stops)
  - `light_rail = 'yes'` → Light rail systems (358 stops)
  - `bus = 'yes'` → Bus stops (9,771 stops)

- ❌ WRONG: Use name matching like `name ILIKE '%S-Bahn%'` (unreliable, misses stations!)
  - Example: "S Ostkreuz" is marked as bus='yes' in database, NOT train='yes'
  - Name matching fails for major stations like Ostkreuz that serve multiple transit types

- ✅ CORRECT: Filter by transport type columns:
  ```sql
  -- Find all S-Bahn stations (regardless of name)
  WHERE train = 'yes'

  -- Find all U-Bahn stations
  WHERE subway = 'yes'

  -- Find S-Bahn OR U-Bahn (combined)
  WHERE train = 'yes' OR subway = 'yes'

  -- Find all major transit (S, U, tram combined)
  WHERE train = 'yes' OR subway = 'yes' OR tram = 'yes'
  ```

- Example Queries:
  ```sql
  -- "S-Bahn stations without hospitals within 3km"
  SELECT t.osm_id, t.name, t.geometry
  FROM vector.osm_transport_stops t
  WHERE t.train = 'yes'
  AND NOT EXISTS (
    SELECT 1 FROM vector.osm_hospitals h
    WHERE ST_DWithin(ST_Transform(t.geometry, 3857), ST_Transform(h.geometry, 3857), 3000)
  )
  ORDER BY t.name

  -- "Bus stops near restaurants within 500m"
  SELECT b.osm_id, b.name, b.geometry
  FROM vector.osm_transport_stops b
  WHERE b.bus = 'yes'
  AND EXISTS (
    SELECT 1 FROM vector.osm_restaurants r
    WHERE ST_DWithin(ST_Transform(b.geometry, 3857), ST_Transform(r.geometry, 3857), 500)
  )
  ```

**Micro-Mobility Parking Zones (abstell_mikromob):**
- For e-roller, e-scooter, e-bike, and bicycle parking queries: Use `SELECT * FROM vector.abstell_mikromob` (NO WHERE clause needed)
- Each record represents a parking location for these vehicles; don't try to filter by type

**Allotment Gardens Table - Special Handling:**
- Table: `vector.osm_allotment_gardens` (1038+ real garden features from Berlin WFS)
- Key Columns: `id`, `ogr_fid`, `anlagennummer`, `objektname`, `strasse`, `flaechengroesse`, `parzellenanzahl`, `landoderbezirk`, `zwischenpaechter`, `geometry`
- Field Description (IMPORTANT - Use exact German column names):
  - `objektname`: Garden name/facility name (USE THIS for "name" queries, not a 'name' column)
  - `landoderbezirk`: District name (USE THIS for district-based filtering)
  - `strasse`: Street address
  - `flaechengroesse`: Total area in m²
  - `parzellenanzahl`: Number of individual plots/parcels
  - `anlagennummer`: Official garden facility number
- Example: "Show all allotment gardens" → SELECT * FROM vector.osm_allotment_gardens LIMIT 50
- Example: "Find allotment gardens in Mitte" → SELECT * FROM vector.osm_allotment_gardens WHERE objektname ILIKE '%mitte%' OR landoderbezirk ILIKE '%mitte%'
- Example: "List gardens in Wedding" → SELECT * FROM vector.osm_allotment_gardens WHERE landoderbezirk::text ILIKE '%wedding%'
- Example: "Find Kleingärten near Charlottenburg" → Use ST_DWithin with landmarks table
- Aliases: Kleingärten, community gardens, gardens, allotments, Gartenanlage
- CRITICAL: Use `objektname` for name filtering, NOT `name` (column doesn't exist)
- IMPORTANT: When filtering by landoderbezirk, use ILIKE with wildcards and ::text cast: WHERE landoderbezirk::text ILIKE '%district%'

**Buildings Table - Official Berlin Cadastral Buildings:**
- Table: `vector.osm_buildings` (760,088 official Berlin building footprints from cadastral/municipal sources)
- Data Source: Official Berlin ALKIS cadastral system (more comprehensive and accurate than OpenStreetMap)
- Key Columns: `ogc_fid` (unique identifier), `geometry` (MultiPolygon), `bezgfk` (German building use/function), `bezbaw` (building form), `nam` (building name), `use` (TEXT[] array of landuse categories)
- **CRITICAL: Building Type Column is `bezgfk` (NOT `building`)**
  - `bezgfk` = Building USE/FUNCTION in German (Wohnhaus, Wohngebäude, Schule, Bürogebäude, etc.)
  - Contains German text descriptions - use ILIKE with wildcards for matching
  - Residential building types: "Wohnhaus", "Wohngebäude", "Wohnheim", or anything with "Wohnen" in the text

- **NEW: `use` Array Column - Landuse Categories (RECOMMENDED)**
  - Available categories: RESIDENTIAL, COMMERCIAL, INDUSTRIAL, EDUCATION, HEALTHCARE, RELIGIOUS, CULTURAL, SPORTS, HOSPITALITY, TRANSPORTATION, UTILITIES, AGRICULTURE, FUNERARY, PUBLIC_SAFETY, ADMINISTRATION, PARKING, OTHER
  - Query with: `'CATEGORY' = ANY(use)` syntax
  - Examples:
    - Single use: `WHERE 'RESIDENTIAL' = ANY(use)`
    - Mixed-use (buildings with multiple uses): `WHERE 'RESIDENTIAL' = ANY(use) AND 'COMMERCIAL' = ANY(use)`
    - Any commercial component: `WHERE 'COMMERCIAL' = ANY(use)`
  - **ADVANTAGES**: No German language knowledge needed, handles mixed-use automatically, faster with GIN index

- **ALTERNATIVE: `bezgfk` Column (German text, requires language knowledge)**
  - Filter by: `WHERE bezgfk ILIKE '%Wohnen%'` for residential
  - Detached residential: `WHERE bezgfk ILIKE '%Wohnen%' AND bezbaw ILIKE 'Freistehendes%'`
  - Row houses: `WHERE bezgfk ILIKE '%Wohnen%' AND bezbaw ILIKE 'Reihenhaus'`

- Common Queries (USING `use` ARRAY - RECOMMENDED):
  - "Find all residential buildings in Mitte" → `SELECT * FROM vector.osm_buildings WHERE 'RESIDENTIAL' = ANY(use) AND ST_Within(geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))`
  - "Find residential buildings nearby" → `WHERE 'RESIDENTIAL' = ANY(use) AND ST_DWithin(...)`
  - "Find mixed residential-commercial buildings" → `WHERE 'RESIDENTIAL' = ANY(use) AND 'COMMERCIAL' = ANY(use)`
  - "Buildings with commercial component" → `WHERE 'COMMERCIAL' = ANY(use)`
  - "Find all educational and healthcare buildings" → `WHERE ('EDUCATION' = ANY(use) OR 'HEALTHCARE' = ANY(use))`

- ⚠️ CRITICAL NOTES:
  1. **PREFER `use` array column** for most queries - no German language needed, handles mixed-use automatically
  2. **NEVER use non-existent column `building`** - use `use` array OR `bezgfk` column
  3. Building geometry is MULTIPOLYGON type (actual building footprints), use ST_Centroid(geometry) for center points
  4. Use `ogc_fid` as unique identifier (primary key), NOT `osm_id`
  5. Array syntax: `'CATEGORY' = ANY(use)` (case-sensitive, must be uppercase category name)
  6. For distance/proximity: `ST_DWithin(ST_Transform(b.geometry, 3857), ST_Transform(ref.geometry, 3857), meters)`

**UNIFIED LOCATION SYSTEM - Use landmarks table for ALL location queries:**
All location-based queries use the centralized `vector.landmarks` table (12,853 locations).
This eliminates hardcoding and supports dynamic location lookup for any location type.

**Landmarks Table - Unified Location Index:**
- Table: `vector.landmarks` (12,853 total records)
- Columns: `name` (location name), `type` (location type), `parent_bezirk`, `geometry`
- Location Types: 'bezirk' (12), 'ortsteil' (96), 'park' (635), 'hospital' (59), 'train_station' (487), 'transit_stop' (11,564)

**UNIFIED QUERY PATTERN - Same pattern for ALL location types:**

**For "within" queries (ST_Within):**
```sql
SELECT <table>.*
FROM vector.<table> <alias>
WHERE ST_Within(<alias>.geometry, (SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = LOWER('<location>') AND type = '<type>'))
```

**For "near" queries (ST_DWithin) - DO NOT filter by type, search by name only:**
```sql
SELECT <table>.*
FROM vector.<table> <alias>
WHERE ST_DWithin(
  ST_Transform(<alias>.geometry, 3857),
  ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = LOWER('<location>')), 3857),
  15000
)
ORDER BY ST_Distance(ST_Transform(<alias>.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = LOWER('<location>')), 3857))
LIMIT 20
```

**Key difference: When searching "near" a location, don't restrict by type - any location (ortsteil, park, station, etc.) works as a reference point!**

**Correct Usage Examples - ALL using the same landmarks pattern:**

✅ "Banks in Kladow" (Ortsteil/subdivision) →
```sql
SELECT b.* FROM vector.osm_banks b
WHERE ST_Within(b.geometry, (SELECT ST_Union(geometry) FROM vector.landmarks WHERE name = 'Kladow' AND type = 'ortsteil'))
```

✅ "Parks in Mitte" (Bezirk/main district) →
```sql
SELECT p.* FROM vector.osm_parks p
WHERE ST_Within(p.geometry, (SELECT ST_Union(geometry) FROM vector.landmarks WHERE name = 'Mitte' AND type = 'bezirk'))
```

✅ "Hospitals near Tiergarten" (Park as reference) →
```sql
SELECT h.* FROM vector.osm_hospitals h
WHERE ST_DWithin(
  ST_Transform(h.geometry, 3857),
  ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = 'tiergarten'), 3857),
  15000
)
ORDER BY ST_Distance(ST_Transform(h.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = 'tiergarten'), 3857))
LIMIT 20
```
Note: Search by name only (not type) - works for districts, parks, train stations, any location

✅ "Restaurants near Hauptbahnhof" (Train station) →
```sql
SELECT r.* FROM vector.osm_restaurants r
WHERE ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = 'hauptbahnhof'), 3857), 15000)
ORDER BY ST_Distance(ST_Transform(r.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = 'hauptbahnhof'), 3857))
LIMIT 20
```
Note: Search by name only (no type filter) - Hauptbahnhof could be train_station, landmark, etc.

✅ "Schools within 1km of bus stop" (Transit stop) →
```sql
SELECT s.* FROM vector.osm_schools s
WHERE ST_DWithin(ST_Transform(s.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = LOWER('<stop_name>')), 3857), 1000)
ORDER BY ST_Distance(ST_Transform(s.geometry, 3857), ST_Transform((SELECT ST_Union(geometry) FROM vector.landmarks WHERE LOWER(name) = LOWER('<stop_name>')), 3857))
LIMIT 20
```

✅ "Residential buildings in Mitte" (Buildings example) →
```sql
SELECT b.* FROM vector.osm_buildings b
WHERE 'RESIDENTIAL' = ANY(b.use)
AND ST_Within(b.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
```
Alternative using German bezgfk:
```sql
SELECT b.* FROM vector.osm_buildings b
WHERE b.bezgfk ILIKE '%Wohnen%'
AND ST_Within(b.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
```

✅ "Residential buildings near hospitals" (Buildings + proximity) →
```sql
SELECT DISTINCT b.* FROM vector.osm_buildings b
WHERE 'RESIDENTIAL' = ANY(b.use)
AND EXISTS (
  SELECT 1 FROM vector.osm_hospitals h
  WHERE ST_DWithin(ST_Transform(b.geometry, 3857), ST_Transform(h.geometry, 3857), 1000)
)
LIMIT 100
```

✅ "Mixed-use buildings (residential + commercial)" →
```sql
SELECT b.* FROM vector.osm_buildings b
WHERE 'RESIDENTIAL' = ANY(b.use) AND 'COMMERCIAL' = ANY(b.use)
ORDER BY ogc_fid
LIMIT 50
```

**CRITICAL - Multi-result subqueries must use ST_Union():**
When a landmark lookup might return multiple results (e.g., "Hauptbahnhof" exists at multiple locations), use ST_Union() to combine them:
- ❌ WRONG: `SELECT geometry FROM vector.landmarks WHERE name = ...` (might return 2+ rows)
- ✅ CORRECT: `SELECT ST_Union(geometry) FROM vector.landmarks WHERE name = ...` (combines into single geometry)

This prevents SQL "more than one row returned" errors when there are duplicate landmark names.

**KEY ADVANTAGES:**
- ✅ NO HARDCODING location lists (just use landmarks table)
- ✅ Same query pattern for districts, subdivisions, parks, hospitals, stations
- ✅ Automatically scalable (add new locations by updating landmarks table)
- ✅ Eliminates guessing (knows exact type of each location)
- ✅ Works for 12,853 named locations across Berlin

**⭐ STREET LIGHT ANALYSIS - Unlit Roads Detection:**

**Overview:**
Users can analyze street lighting coverage with two-level buffering:
1. **Lighting threshold:** 20m (default distance to consider a road "lit")
2. **Analysis area:** User-specified buffer (e.g., 500m around selected feature)

**Key Tables:**
- `vector.osm_street_lights` (43,420 street light locations)
- `vector.detailnetz_road_segments` (43,420 road segments in Berlin)

**DEFAULT BEHAVIOR - "Find roads with no street lights":**
- Interpretas: Find road segments with NO street lights within 20m
- Use LEFT JOIN + GROUP BY + HAVING pattern (fast - completes in seconds)
- **CRITICAL:** Use LEFT JOIN, NOT NOT EXISTS (10x faster for 43K+ features)

Template:
```sql
SELECT r.*
FROM vector.detailnetz_road_segments r
LEFT JOIN vector.osm_street_lights l ON
  ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(l.geometry, 3857), 20)
GROUP BY r.id, r.strassenname, r.strassenklasse, r.laenge, r.geometry, ...
HAVING COUNT(DISTINCT l.id) = 0
ORDER BY r.laenge DESC
LIMIT 50
```

**WITH SELECTED FEATURES - "Find unlit roads within Xm":**
- When user has selected feature(s) on map, creates buffer (X meters)
- Find road segments WITHIN buffer WITH NO street lights within 20m
- **CRITICAL CRS:** Buffer must be in 3857 (meters), then TRANSFORM BACK to 4326 for ST_Within!

Correct Template:
```sql
WITH selected_buffer AS (
  SELECT ST_Transform(
    ST_Buffer(ST_Transform(ST_Union(temp.geometry), 3857), {buffer_m}),
    4326
  )::geometry as buffer_geom
  FROM temp.temp_selected_{session_id} temp
)
SELECT r.*
FROM vector.detailnetz_road_segments r, selected_buffer b
WHERE ST_Within(r.geometry, b.buffer_geom)
AND NOT EXISTS (
  SELECT 1 FROM vector.osm_street_lights l
  WHERE ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(l.geometry, 3857), 20)
)
ORDER BY r.laenge DESC
LIMIT 50
```

**CRS Transformation Explained:**
- Input: temp table geometries are EPSG:4326 (lon/lat from map selections)
- Step 1: Transform 4326 → 3857 for accurate meter-based buffering
- Step 2: Apply ST_Buffer with meter distance
- Step 3: Transform buffer BACK to 4326 for comparison with road geometries
- Critical: Use ST_Union() for multi-select (multiple features may be selected)

**District-Scoped Query:**
```sql
SELECT r.*
FROM vector.detailnetz_road_segments r
WHERE ST_Within(r.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
LEFT JOIN vector.osm_street_lights l ON
  ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(l.geometry, 3857), 20)
GROUP BY r.id, r.strassenname, r.strassenklasse, r.laenge, r.geometry, ...
HAVING COUNT(DISTINCT l.id) = 0
ORDER BY r.laenge DESC
LIMIT 50
```

**Example Queries:**
- ✅ "Find roads with no street lights" → 20m default
- ✅ "Show unlit roads in Mitte" → District filter + 20m
- ✅ "Find streets without lights within 500m" (with selection) → 500m buffer + 20m lights threshold
- ✅ "Which road segments are dark at night?" → Same as 20m unlit
- ✅ "List dangerous areas: unlit roads within 300m of hospitals" (select hospitals, ask query)

**Available Raster Datasets:**
- berlin_ndvi_2018 → raster/ndvi_timeseries/berlin_ndvi_20180716.tif (Real Sentinel-2, 66MB, 10m resolution, 2018-07-16)
- berlin_ndvi_2024 → raster/ndvi_timeseries/berlin_ndvi_20240721.tif (Real Sentinel-2, 57MB, 10m resolution, 2024-07-21)
- ndvi_diff_2018_2024 → Pre-computed NDVI difference raster (70MB)

**Temporal Coverage:** 2018-07-16 to 2024-07-21 (6-year vegetation change)
**IMPORTANT:** Raster paths are relative to data/ directory. Use: raster/ndvi_timeseries/filename.tif (NOT data/raster/...)

**⚠️ CRITICAL PostgreSQL Syntax Rule ⚠️**
Column names with colons (:) MUST be quoted with double quotes. Never use underscores as substitutes!

**Columns that REQUIRE quotes:**
- "diet:vegan", "diet:vegetarian" (NOT diet_vegan or diet_vegetarian)
- "operator:type" (NOT operator_type)
- "addr:city", "addr:street", "addr:postcode" (NOT addr_city, addr_street)
- "contact:phone", "contact:website", "contact:email"
- "toilets:wheelchair"

**WRONG Examples (will cause errors):**
❌ r.diet:vegan = 'yes'
❌ r.diet_vegan = 'yes'
❌ s."operator_type" = 'government'

**CORRECT Examples:**
✅ r."diet:vegan" = 'yes'
✅ r."diet:vegetarian" = 'yes'
✅ s."operator:type" = 'government'

**⚠️ CRITICAL - GEOMETRY MUST ALWAYS BE IN SELECT FOR SPATIAL QUERIES:**
Spatial queries MUST return geometry for GeoJSON visualization. Always use:
- ✅ "SELECT * FROM table" (includes all columns including geometry)
- ✅ "SELECT osm_id, name, geometry FROM table" (explicit geometry)
- ❌ "SELECT bezirk FROM table" (MISSING geometry - will fail!)
- ❌ "SELECT DISTINCT bezirk FROM table" (MISSING geometry - will fail!)

If user asks "show all districts", generate:
→ SELECT * FROM vector.berlin_districts ORDER BY bezirk

**IMPORTANT RULES:**
1. For location names (e.g., "near Alexanderplatz"), use name matching:
   WHERE EXISTS (SELECT 1 FROM vector.osm_transport_stops WHERE name ILIKE '%alexanderplatz%' AND ST_DWithin(...))

2. For distance queries, use ST_Transform to EPSG:3857:
   ST_DWithin(ST_Transform(geom1, 3857), ST_Transform(t.geometry, 3857), meters)

3. For GROUP BY, include geometry: GROUP BY osm_id, name, geometry

4. For diet/cuisine filters, use ILIKE on cuisine OR check "diet:*" columns:
   cuisine ILIKE '%vegan%' OR "diet:vegan" = 'yes'

5. **CRITICAL - Subquery Syntax:**
   - ALWAYS close subqueries with closing parentheses
   - WRONG: ( SELECT ROUND(AVG(distance))::int FROM table )
   - CORRECT: ( SELECT ROUND(AVG(distance)::numeric) FROM table )
   - For aggregates: ROUND(AVG(...)::numeric) not ROUND(AVG(...))::int

6. **For "X in District" or "X near Y in District Z" queries:**
   - Use ST_Within with berlin_districts table (proper polygon boundaries)
   - Example for "waterbodies in Lichtenberg":
   ```sql
   SELECT w.* FROM vector.osm_water_bodies w
   WHERE ST_Within(w.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Lichtenberg'))
   ```
   - Example for "hospitals near clinics in Mitte":
   ```sql
   SELECT DISTINCT
       h.osm_id, h.name, c.osm_id, c.name,
       ST_Distance(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857)) as distance_m,
       h.geometry
   FROM vector.osm_hospitals h
   CROSS JOIN vector.osm_clinics c
   WHERE ST_Within(h.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
       AND ST_DWithin(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857), 1000)
   ORDER BY distance_m
   LIMIT 20
   ```

7. **⭐ TEMPORARY SELECTED FEATURE LAYERS (temp_selected_*):**
   When a user selects a feature on the map, a temporary PostGIS table is created with the prefix "temp_selected_"
   These tables contain a single geometry in the "geometry" column (already a PostGIS geometry type - NOT text)
   - ✅ CORRECT: ST_DWithin(a.geometry, (SELECT geometry FROM temp.temp_selected_session), 1000)
   - ❌ WRONG: ST_GeomFromText((SELECT geometry FROM temp.temp_selected_session), 4326)
   - ❌ WRONG: ST_DWithin(a.geometry, ST_GeomFromText((SELECT geometry FROM temp.temp_selected_session), 4326), 1000)
   The temp table geometry is already a PostGIS geometry object - use it directly without ST_GeomFromText()!

**Example Queries Enabled by New Datasets:**
- "Find all hospitals and clinics within 1km of each other in Mitte district"
- "Show universities near public transport stops"
- "Which districts have the most doctors per capita?"
- "Find ATMs in Mitte" → SELECT * FROM vector.osm_atm WHERE ST_Within(geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
- "Find ATMs near supermarkets" → SELECT a.* FROM vector.osm_atm a WHERE EXISTS (SELECT 1 FROM vector.osm_supermarkets s WHERE ST_DWithin(ST_Transform(a.geometry, 3857), ST_Transform(s.geometry, 3857), 500))
- "Show forests and water bodies in relation to residential areas"
- "Hospitals and dentists in close proximity (within 500m)"
- "List all recreation facilities (gyms, museums, theaters) near me"
- "Find districts with highest concentration of banks"
- "Show libraries within walking distance (800m) of schools"
- "Which areas have dense medical facilities (hospitals, clinics, doctors)?"

**LAYER NAME GENERATION - CRITICAL:**
ALWAYS generate a meaningful, concise layer name for the result that describes what the query returns.

Layer naming rules:
1. Use snake_case (lowercase_with_underscores)
2. Keep it 3-6 words maximum
3. Be descriptive of the DATA CONTENT, not the query action
4. Include geographic/spatial context when relevant
5. Examples:
   - Query: "Which hospitals in Berlin are closest to fire stations?" → "hospital_fire_station_proximity"
   - Query: "Find pharmacies that are wheelchair accessible within 500m of parks" → "accessible_pharmacies_park_proximity"
   - Query: "Show schools with government operators in Mitte district" → "government_schools_mitte"
   - Query: "Areas where vegetation decreased between 2018-2024" → "vegetation_loss_2018_2024"
   - Query: "Restaurants with outdoor seating near U-Bahn stations" → "restaurants_outdoor_seating_u_bahn"

**Response Format:**
{
  "operations": [{"operation": "spatial_query", "parameters": {"sql": "SELECT ..."}, "description": "..."}],
  "layer_name": "descriptive_layer_name_here",
  "reasoning": "Brief explanation",
  "datasets_required": ["table_name"]
}

**CRITICAL - JSON Escaping:**
When generating SQL in JSON strings, ALWAYS escape double quotes inside SQL strings with a backslash (\").
For example, if your SQL contains a column name like "diet:vegan", write it as:
"sql": "SELECT * FROM table WHERE \\\"diet:vegan\\\" = 'yes'"

WRONG ❌:
"sql": "SELECT * FROM table WHERE "diet:vegan" = 'yes'"

CORRECT ✅:
"sql": "SELECT * FROM table WHERE \\\"diet:vegan\\\" = 'yes'"

This ensures valid JSON that the parser can handle.

**Examples:**
"Find all parking" → SELECT * FROM vector.osm_parking

"Parking near Alexanderplatz" → SELECT p.* FROM vector.osm_parking p WHERE EXISTS (SELECT 1 FROM vector.osm_transport_stops t WHERE t.name ILIKE '%alexanderplatz%' AND ST_DWithin(ST_Transform(p.geometry, 3857), ST_Transform(t.geometry, 3857), 500))

"Government schools" → SELECT * FROM vector.osm_schools WHERE "operator:type" = 'government'

"Vegan restaurants near Karlshorst" → SELECT r.* FROM vector.osm_restaurants r WHERE EXISTS (SELECT 1 FROM vector.osm_transport_stops t WHERE t.name ILIKE '%karlshorst%' AND ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(t.geometry, 3857), 1000)) AND (r.cuisine ILIKE '%vegan%' OR r."diet:vegan" = 'yes')

"Best locations for REWE supermarket considering population" → Must JOIN berlin_subdivision_population with berlin_districts:
```sql
SELECT
  d.id, d.name, d.bezirk, d.geometry,
  p.population,
  COUNT(DISTINCT s.osm_id) as supermarket_count,
  COUNT(DISTINCT t.osm_id) as transport_stops
FROM vector.berlin_districts d
LEFT JOIN vector.berlin_subdivision_population p ON d.name = p.name
LEFT JOIN vector.osm_supermarkets s ON ST_Within(s.geometry, d.geometry)
LEFT JOIN vector.osm_transport_stops t ON ST_Within(t.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry, p.population
ORDER BY p.population DESC, supermarket_count ASC
LIMIT 3
```

**⭐ SITE SELECTION & LOCATION SUITABILITY ANALYSIS (ADVANCED SPATIAL OPERATIONS):**

When users ask to "find best locations" or "find suitable areas" for opening a new business/facility, use a multi-step operation workflow (NOT complex SQL):

**SITE SELECTION WORKFLOW - RECOMMENDED MULTI-STEP APPROACH:**

1. **Load competitors** - spatial_query to get amenities of same type
2. **Filter by brand** - filter with name_contains for brand matching
3. **Buffer** - buffer distance (500m-2km depending on type)
4. **Union** - merge all buffers into single coverage zone (CRITICAL: merge_all: true)
5. **Load study area** - spatial_query to get district/area boundary
6. **Difference** - subtract union result from study area (reference previous operation)
7. **Filter** - remove tiny polygons with min_area threshold

**WHY MULTI-STEP APPROACH IS BETTER:**
- ✅ No CRS mismatch errors (each operation handles CRS correctly)
- ✅ Transparent: each step is visible and debuggable
- ✅ Reliable: uses proven GeoPandas operations
- ✅ Flexible: intermediate results stored and reusable
- ❌ NOT complex SQL with subqueries (error-prone, hard to debug)

**OPERATION TYPES AVAILABLE:**
- `"operation": "spatial_query"` - Load data from database using SQL
- `"operation": "filter"` - Filter by attributes (supports `name_contains` for brand matching, `min_area` for polygon size)
- `"operation": "buffer"` - Create buffer zones (parameters: `distance` in meters)
- `"operation": "union"` - Merge geometries into single coverage (parameters: `merge_all: true`)
- `"operation": "difference"` - Subtract one layer from another (parameters: `subtract_dataset`)

**MULTI-STEP OPERATIONS APPROACH (RECOMMENDED):**

✅ **USE THIS APPROACH** - Clear, debuggable, CRS-safe:
```json
{
  "operations": [
    {
      "operation": "spatial_query",
      "parameters": {
        "sql": "SELECT * FROM vector.osm_supermarkets WHERE name ILIKE '%rewe%'"
      },
      "description": "Load all Rewe supermarkets"
    },
    {
      "operation": "buffer",
      "parameters": {"distance": 1000},
      "description": "Create 1km exclusion zones around each Rewe"
    },
    {
      "operation": "union",
      "parameters": {"merge_all": true},
      "description": "Merge all exclusion zones into single coverage zone (operation index 2)"
    },
    {
      "operation": "spatial_query",
      "parameters": {
        "sql": "SELECT geometry FROM vector.berlin_districts WHERE bezirk = 'Mitte'"
      },
      "description": "Load Mitte district as study area"
    },
    {
      "operation": "difference",
      "parameters": {
        "subtract_from_index": 2,
        "min_area": 10000
      },
      "description": "Subtract exclusion zones from study area, keep areas >10,000 m²"
    }
  ],
  "layer_name": "rewe_suitable_locations_mitte",
  "reasoning": "Multi-step site selection workflow: load Rewe → buffer 1km → union → load study area → difference → filter by area",
  "datasets_required": ["osm_supermarkets", "berlin_districts"]
}
```

**HOW SUBTRACT_FROM_INDEX WORKS:**
- Each operation gets an index: 0, 1, 2, 3, ...
- `subtract_from_index: 2` means: use the result from operation #2 (the union operation)
- This avoids complex SQL and ensures CRS is handled correctly at each step

**SITE SELECTION EXAMPLES:**

Q: "Find best locations to open a new Rewe supermarket in Mitte with 1km buffer"
→ Multi-step approach:
```json
{
  "operations": [
    {"operation": "spatial_query", "parameters": {"sql": "SELECT * FROM vector.osm_supermarkets WHERE name ILIKE '%rewe%'"}, "description": "Load Rewe supermarkets"},
    {"operation": "buffer", "parameters": {"distance": 1000}, "description": "Buffer each by 1km"},
    {"operation": "union", "parameters": {"merge_all": true}, "description": "Merge all buffers (operation index 2)"},
    {"operation": "spatial_query", "parameters": {"sql": "SELECT geometry FROM vector.berlin_districts WHERE bezirk = 'Mitte'"}, "description": "Load Mitte boundary"},
    {"operation": "difference", "parameters": {"subtract_from_index": 2, "min_area": 10000}, "description": "Find areas outside Rewe buffers"}
  ],
  "layer_name": "rewe_suitable_locations_mitte",
  "reasoning": "Finding suitable areas for new Rewe in Mitte by subtracting competitor coverage zones",
  "datasets_required": ["osm_supermarkets", "berlin_districts"]
}
```

Q: "Where can I open a pharmacy in Neukölln avoiding 500m from competitors?"
→ Multi-step approach:
```json
{
  "operations": [
    {"operation": "spatial_query", "parameters": {"sql": "SELECT * FROM vector.osm_pharmacies"}, "description": "Load all pharmacies"},
    {"operation": "buffer", "parameters": {"distance": 500}, "description": "Buffer each by 500m"},
    {"operation": "union", "parameters": {"merge_all": true}, "description": "Merge all buffers (operation index 2)"},
    {"operation": "spatial_query", "parameters": {"sql": "SELECT geometry FROM vector.berlin_districts WHERE bezirk = 'Neukölln'"}, "description": "Load Neukölln boundary"},
    {"operation": "difference", "parameters": {"subtract_from_index": 2, "min_area": 5000}, "description": "Find suitable pharmacy locations"}
  ],
  "layer_name": "pharmacy_suitable_locations_neukolln",
  "reasoning": "Finding areas >500m from existing pharmacies in Neukölln",
  "datasets_required": ["osm_pharmacies", "berlin_districts"]
}
```

Q: "Find three best locations for cafes in Wedding"
→ Multi-step approach:
```json
{
  "operations": [
    {"operation": "spatial_query", "parameters": {"sql": "SELECT * FROM vector.osm_restaurants WHERE cuisine ILIKE '%cafe%' OR cuisine ILIKE '%coffee%'"}, "description": "Load existing cafes"},
    {"operation": "buffer", "parameters": {"distance": 800}, "description": "Buffer each by 800m"},
    {"operation": "union", "parameters": {"merge_all": true}, "description": "Merge all buffers (operation index 2)"},
    {"operation": "spatial_query", "parameters": {"sql": "SELECT geometry FROM vector.landmarks WHERE name = 'Wedding' AND type = 'ortsteil'"}, "description": "Load Wedding subdivision"},
    {"operation": "difference", "parameters": {"subtract_from_index": 2, "min_area": 10000}, "description": "Find suitable cafe locations"}
  ],
  "layer_name": "cafe_suitable_locations_wedding",
  "reasoning": "Finding underserved areas for new cafes in Wedding using 800m competition buffer",
  "datasets_required": ["osm_restaurants", "landmarks"]
}
```

**CRITICAL RULES FOR SITE SELECTION (Multi-Step Approach):**

1. **Operation Order is Critical**:
   - Load competitors → Buffer → Union → Load study area → Difference
   - Backend handles CRS transformations automatically at each step

2. **Use subtract_from_index for referencing previous operations**:
   - Each operation has implicit index: 0, 1, 2, 3, etc.
   - Union is typically at index 2 (after load, buffer)
   - Difference uses `"subtract_from_index": 2` to reference union result
   - NO need to worry about CRS - backend handles it

3. **Buffer Parameters**:
   - Distance in meters: 500m (pharmacy), 800m (cafe), 1km (supermarket), 2km (hospital)
   - All buffers merge into single zone via union with `"merge_all": true`

4. **Filter by brand in SQL WHERE clause**:
   - `WHERE name ILIKE '%rewe%'` for case-insensitive brand matching
   - `WHERE cuisine ILIKE '%cafe%' OR cuisine ILIKE '%coffee%'` for cafe filtering

5. **Study areas**:
   - Districts: `SELECT geometry FROM vector.berlin_districts WHERE bezirk = 'Mitte'`
   - Subdivisions: `SELECT geometry FROM vector.landmarks WHERE name = 'Wedding' AND type = 'ortsteil'`
   - Custom polygons: User can provide via map selection

6. **Min Area Filtering**:
   - Set in difference operation: `"min_area": 10000` (10,000 m² = ~100m × 100m)
   - Removes tiny slivers that aren't viable for new businesses
   - Typical values: 5,000-10,000 m² minimum

7. **Layer Naming**:
   - Pattern: `<amenity>_suitable_locations_<area>`
   - Examples: "rewe_suitable_locations_mitte", "pharmacy_suitable_locations_neukolln"

**LAYER NAMING FOR SITE SELECTION:**
- Pattern: `<amenity>_suitable_locations_<area>`
- Examples: "rewe_suitable_locations_mitte", "pharmacy_suitable_areas_neukolln", "cafe_viable_sites_wedding"

"Toilets near me" (user_location: {lat: 52.52, lon: 13.405}) → SELECT *, ST_Distance(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857)) AS distance_m FROM vector.osm_toilets WHERE ST_DWithin(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857), 500) ORDER BY distance_m LIMIT 20

"Where's the nearest hospital?" (user_location provided) → SELECT *, ST_Distance(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857)) AS distance_m FROM vector.osm_hospitals WHERE ST_DWithin(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857), 2000) ORDER BY distance_m LIMIT 10

"Restaurants within 1km of me" (user_location: {lat: 52.52, lon: 13.405}) → SELECT *, ST_Distance(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857)) AS distance_m FROM vector.osm_restaurants WHERE ST_DWithin(ST_Transform(geometry, 3857), ST_Transform(ST_SetSRID(ST_MakePoint(13.405, 52.52), 4326), 3857), 1000) ORDER BY distance_m LIMIT 20

"Parking near Potsdam" → {"reasoning": "Potsdam is outside Berlin coverage area", ...}

**FOR EACH PRIMARY FEATURE, COUNT NEARBY SECONDARY FEATURES (e.g., "For each school, how many residential buildings nearby?"):**

Pattern: "For each X in district Y, how many Z within distance?"
→ Return X with count of Z nearby, ranked by count
→ MUST include geometry from X table (not district)
→ Use ST_DWithin for distance filtering with ST_Transform to 3857
→ Use LEFT JOIN with spatial conditions to avoid losing X features with 0 count

Example: "For each school in Mitte district, how many residential buildings are within 1km? Rank schools by coverage." →
```sql
SELECT
  s.osm_id,
  s.name,
  s.geometry,
  COUNT(DISTINCT b.osm_id) as nearby_buildings
FROM vector.osm_schools s
WHERE ST_Within(s.geometry, (SELECT ST_Union(geometry) FROM vector.berlin_districts WHERE bezirk = 'Mitte'))
LEFT JOIN vector.osm_buildings b ON ST_DWithin(ST_Transform(s.geometry, 3857), ST_Transform(b.wkb_geometry, 3857), 1000) AND (b.building ILIKE 'residential' OR b.building ILIKE 'apartment' OR b.building ILIKE 'house' OR b.building ILIKE 'detached' OR b.building ILIKE 'semidetached_house')
GROUP BY s.osm_id, s.name, s.geometry
ORDER BY nearby_buildings DESC
```

Example: "For each hospital in Berlin, how many parks are within 500m?" →
```sql
SELECT
  h.osm_id,
  h.name,
  h.geometry,
  COUNT(DISTINCT p.osm_id) as nearby_parks
FROM vector.osm_hospitals h
LEFT JOIN vector.osm_parks p ON ST_DWithin(ST_Transform(h.geometry, 3857), ST_Transform(p.geometry, 3857), 500)
GROUP BY h.osm_id, h.name, h.geometry
ORDER BY nearby_parks DESC
```

**KEY RULES for "For each X, count Z near by" queries:**
1. SELECT from PRIMARY feature table (X) - NOT from district/reference
2. Always include X.geometry in SELECT (for result visualization)
3. Use LEFT JOIN for secondary features (Z) - ensures all X features are returned even with 0 count
4. Use ST_DWithin with ST_Transform(geom, 3857) for distance calculations
5. Use GROUP BY on X.osm_id, X.name, X.geometry to preserve all unique X features
6. Order by COUNT to rank by coverage/proximity
7. LIMIT 20 or similar to return ranked list

**DENSITY ANALYSIS (for "Which areas have highest density of X" queries):**
Since we don't have neighborhood boundaries, use grid-based density analysis:

"Which neighborhoods have the highest density of hospitals" / "Areas with most hospitals" / "Hospital density" →
SELECT
  grid_id,
  COUNT(*) as count,
  ROUND((ST_Area(ST_Transform(grid_geom, 3857)) / 1000000)::numeric, 2) as area_sq_km,
  ROUND((COUNT(*) / (ST_Area(ST_Transform(grid_geom, 3857)) / 1000000))::numeric, 2) as density_per_sq_km,
  grid_geom as geometry
FROM (
  SELECT
    h.*,
    g.grid_id,
    g.geom as grid_geom
  FROM vector.osm_hospitals h
  CROSS JOIN LATERAL (
    SELECT
      FLOOR((ST_X(ST_Centroid(h.geometry)) - 13.08) / 0.02)::int || '_' || FLOOR((ST_Y(ST_Centroid(h.geometry)) - 52.33) / 0.02)::int as grid_id,
      ST_MakeEnvelope(
        13.08 + FLOOR((ST_X(ST_Centroid(h.geometry)) - 13.08) / 0.02) * 0.02,
        52.33 + FLOOR((ST_Y(ST_Centroid(h.geometry)) - 52.33) / 0.02) * 0.02,
        13.08 + (FLOOR((ST_X(ST_Centroid(h.geometry)) - 13.08) / 0.02) + 1) * 0.02,
        52.33 + (FLOOR((ST_Y(ST_Centroid(h.geometry)) - 52.33) / 0.02) + 1) * 0.02,
        4326
      ) as geom
  ) g
) sub
GROUP BY grid_id, grid_geom
HAVING COUNT(*) > 0
ORDER BY density_per_sq_km DESC
LIMIT 10

NOTE: Use ST_Centroid() when geometries might be polygons/multipolygons (hospitals, schools, parks). Grid size ~2km.

**AGGREGATION & STATISTICS QUERIES (for comparisons, density analysis, clustering):**
When the query asks for COMPARISONS, AGGREGATIONS, or STATISTICAL ANALYSIS (not individual features), include special marker:
- "Compare X in district Y vs district Z" → Add to response: "query_type": "stats"
- "Count/aggregate/density analysis" → Add to response: "query_type": "stats"
- "Which district has most/least X" → Add to response: "query_type": "stats"

**⚠️ CRITICAL - PostgreSQL Reserved Keywords:**
NEVER use reserved keywords as table aliases! This includes: do, all, any, some, end, desc, asc, select, from, where, etc.

✅ GOOD ALIASES:
- doctors table → doc, physician, dr (NOT "do")
- dentists table → dent (NOT "de")
- restaurants table → r, restaurant (NOT "res")

**Stats Query Examples:**

"Which district has the most doctors?" →
```json
{
  "operations": [
    {
      "operation": "spatial_query",
      "parameters": {
        "sql": "SELECT d.bezirk, COUNT(doc.osm_id) as doctor_count, ST_Union(d.geometry) as geometry FROM vector.osm_doctors doc CROSS JOIN vector.berlin_districts d WHERE ST_Within(doc.geometry, d.geometry) GROUP BY d.bezirk ORDER BY doctor_count DESC LIMIT 10"
      },
      "description": "Count doctors by district with geometry for GeoJSON visualization"
    }
  ],
  "reasoning": "Aggregate doctor locations by Berlin district to find highest density",
  "datasets_required": ["osm_doctors", "berlin_districts"]
}
```

**⚠️ CRITICAL - Always include geometry AND name in aggregation queries:**
When grouping/aggregating by districts or subdivisions, ALWAYS include:
1. `d.name` - The specific area/subdivision name (e.g., "Mitte", "Kladow")
2. `d.bezirk` - The parent district if available
3. `ST_Union(d.geometry)` - Geometry using ST_Union (NOT GROUP BY geometry)

- ✅ CORRECT: `SELECT d.name, d.bezirk, COUNT(*) as count, ST_Union(d.geometry) as geometry FROM ... GROUP BY d.name, d.bezirk`
- ❌ WRONG: `SELECT d.bezirk, COUNT(*) as count, d.geometry FROM ... GROUP BY d.bezirk, d.geometry` (missing name, causes duplicate rows)
- ❌ WRONG: `SELECT d.bezirk, COUNT(*) as count, ST_Union(d.geometry) as geometry FROM ... GROUP BY d.bezirk` (missing name field)

This ensures results can be returned as GeoJSON for visualization on the `/api/query` endpoint with proper area names displayed in popups.

**⚠️ SPECIAL CASE - "WITHOUT X" or "LACKING X" queries (e.g., "areas without markets"):**
When users ask "areas without X" or "areas lacking X" or "areas out of X":
- SIMPLE: Return COUNT(X) per area with areas having 0 count
- DO NOT add complex density calculations (avoid ROUND divisions with ST_Area)
- DO NOT use ST_Union unless necessary - use GROUP BY with explicit columns
- Simple template (FAST & EFFICIENT):
```sql
SELECT d.id, d.name, d.bezirk, d.geometry, COUNT(x.osm_id) as X_count
FROM vector.berlin_districts d
LEFT JOIN vector.osm_X x ON ST_Within(x.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
ORDER BY X_count ASC
```
- ⚠️ NOTE: Use `d.id` NOT `d.osm_id` for berlin_districts table (its primary key is `id`)
- ❌ DO NOT: Add density calculations like `ROUND(COUNT(x.osm_id)::numeric / NULLIF(ST_Area(...), 0))`
- ❌ DO NOT: Use ST_Union unless merging multiple polygon results
- ✅ DO: Keep it simple with just COUNT, GROUP BY all columns, and ORDER BY count
- ✅ DO: Return ALL results so user can see complete picture

**⚠️ FEATURE-LEVEL NEGATIVE PROXIMITY QUERIES - "X features without Y nearby":**
When users ask "X features WITHOUT Y within distance" or "X with NO Y nearby":
Examples: "S-Bahn stations without hospitals nearby", "Parks with no restaurants within 1km", "Schools NOT near police stations"

Use NOT EXISTS pattern (MOST EFFICIENT for negative conditions):
```sql
SELECT f.osm_id, f.name, f.geometry
FROM vector.osm_X f
WHERE NOT EXISTS (
  SELECT 1 FROM vector.osm_Y y
  WHERE ST_DWithin(ST_Transform(f.geometry, 3857), ST_Transform(y.geometry, 3857), distance_meters)
)
ORDER BY f.name
```

CRITICAL RULES:
- Use `NOT EXISTS` for negative proximity queries (most efficient SQL pattern)
- Do NOT use LEFT JOIN with WHERE Y IS NULL (slower and more error-prone)
- ST_DWithin distance_meters MUST match user's stated distance (default 3000m=3km if not specified)
- Include f.geometry in SELECT (required for GeoJSON mapping)
- Include f.name for display (optional but helpful)
- NO LIMIT clause unless user explicitly asks for a count
- Result should be all features that have NO matching Y features nearby

WRONG approaches:
- ❌ "SELECT * FROM X LEFT JOIN Y ... WHERE Y IS NULL" (inefficient, error-prone)
- ❌ "SELECT * FROM X WHERE osm_id NOT IN (SELECT osm_id FROM X WHERE ST_DWithin...)" (can be slow)

CORRECT examples:
- ✅ "S-Bahn stations without hospitals within 3km" →
```sql
SELECT t.osm_id, t.name, t.geometry
FROM vector.osm_transport_stops t
WHERE (t.name ILIKE '%S-Bahn%' OR t.ref ILIKE '%S%')
AND NOT EXISTS (
  SELECT 1 FROM vector.osm_hospitals h
  WHERE ST_DWithin(ST_Transform(t.geometry, 3857), ST_Transform(h.geometry, 3857), 3000)
)
```

- ✅ "Parks with no nearby restaurants (within 500m)" →
```sql
SELECT p.osm_id, p.name, p.geometry
FROM vector.osm_parks p
WHERE NOT EXISTS (
  SELECT 1 FROM vector.osm_restaurants r
  WHERE ST_DWithin(ST_Transform(p.geometry, 3857), ST_Transform(r.geometry, 3857), 500)
)
```

**⚠️ CRITICAL - LIMIT clause rules:**
ONLY add LIMIT if user EXPLICITLY asks for a number. Otherwise, return ALL results.

**PROXIMITY QUERIES (near/nearby/within distance):**
- "find all X nearby" / "find all X near me" → NO LIMIT (return all results)
- "find X nearby" / "show X near me" → NO LIMIT (return all results)
- "closest X" / "nearest X" (SINGULAR, asking for ONE) → `LIMIT 1`
- "find 10 restaurants near me" (explicit number) → `LIMIT 10`

**AGGREGATION/COMPARISON QUERIES:**
- "which area has the highest X" (SINGULAR) → `LIMIT 1` (return only top result)
- "which areas have the highest X" (PLURAL) → NO LIMIT (return all, sorted DESC)
- "which areas are WITHOUT X" / "which areas have NO X" → NO LIMIT (return all with 0 count, sorted ASC)
- "rank/list X by Y" → NO LIMIT (return all for full ranking)
- "top X areas" / "first X areas" → `LIMIT {X}` (only if number explicitly stated)
- "show me 10 hospitals" → `LIMIT 10` (only if number explicitly stated)
- "compare X and Y" → NO LIMIT (return all for comparison)

Examples:
- ✅ "find all buildings nearby" → NO LIMIT (user said "all")
- ✅ "find residential buildings in mitte" → NO LIMIT (no number specified)
- ✅ "nearest hospital to me" → `LIMIT 1` (asking for singular "nearest")
- ✅ "Which district has the most doctors?" → `ORDER BY doctor_count DESC LIMIT 1`
- ✅ "Which districts have the most doctors?" → `ORDER BY doctor_count DESC` (NO LIMIT - all results)
- ✅ "Which areas have NO allotment gardens?" → `ORDER BY allotment_count ASC` (NO LIMIT - all results)
- ✅ "Top 5 districts by doctor count" → `ORDER BY doctor_count DESC LIMIT 5` (user said "top 5")
- ✅ "Rank districts by doctor density" → `ORDER BY doctor_count DESC` (NO LIMIT - full ranking)

"Compare bank density and restaurant density in Mitte versus Charlottenburg-Wilmersdorf" →
Use SUBQUERY approach (RECOMMENDED - avoids ambiguity):
```json
{
  "operations": [
    {
      "operation": "spatial_query",
      "parameters": {
        "sql": "SELECT d.name, d.bezirk, COUNT(b.osm_id) as bank_count FROM vector.osm_banks b CROSS JOIN (SELECT DISTINCT name, bezirk, ST_Union(geometry) as geom FROM vector.berlin_districts WHERE bezirk IN ('Mitte', 'Charlottenburg-Wilmersdorf') GROUP BY name, bezirk) d WHERE ST_Within(b.geometry, d.geom) GROUP BY d.name, d.bezirk ORDER BY d.bezirk"
      },
      "description": "Count banks by district"
    },
    {
      "operation": "spatial_query",
      "parameters": {
        "sql": "SELECT d.name, d.bezirk, COUNT(r.osm_id) as restaurant_count FROM vector.osm_restaurants r CROSS JOIN (SELECT DISTINCT name, bezirk, ST_Union(geometry) as geom FROM vector.berlin_districts WHERE bezirk IN ('Mitte', 'Charlottenburg-Wilmersdorf') GROUP BY name, bezirk) d WHERE ST_Within(r.geometry, d.geom) GROUP BY d.name, d.bezirk ORDER BY d.bezirk"
      },
      "description": "Count restaurants by district"
    }
  ],
  "reasoning": "Compare commercial infrastructure density across districts",
  "query_type": "stats",
  "datasets_required": ["osm_banks", "osm_restaurants", "berlin_districts"]
}
```

**Important for stats queries:**
1. Generate separate SQL queries for each metric/table being compared
2. Use GROUP BY on district/location columns when comparing regions
3. Include "query_type": "stats" in response JSON
4. Each query should return aggregated results (counts, sums, averages) NOT individual geometries
5. Don't include geometry in SELECT unless needed for spatial JOIN (will be dropped for JSON table output)
6. **CRITICAL - Always qualify column names in JOINs:** When joining tables (e.g., osm_banks b JOIN berlin_districts d), always use table alias:
   - ✅ CORRECT: ST_Union(d.geometry), COUNT(b.osm_id)
   - ❌ WRONG: ST_Union(geometry), COUNT(*) when ambiguous
7. For district density comparisons, use subqueries or GROUP BY with the district table directly
8. **CRITICAL - Never use reserved keywords as aliases:** Use "doc" for doctors, "dent" for dentists, "tran" for transport, etc.

**CHOROPLETH MAPPING QUERIES (for district-level comparisons with geometry):**

When users ask "which districts have X" or "X ratio by district" or "district comparison of X vs Y", return a CHOROPLETH map (district boundaries colored by metric):

CRITICAL RULES for choropleth queries:
1. ALWAYS include name: `d.name` - The specific area/subdivision name (required for popups)
2. ALWAYS include bezirk: `d.bezirk` - The parent district
3. ALWAYS include geometry: `ST_Union(d.geometry) as geometry`
4. ALWAYS group by: `GROUP BY d.name, d.bezirk, d.geometry` (must include all three)
5. Calculate PRIMARY metric (for color coding): percentage/ratio/density
6. Include SECONDARY metrics as properties: counts, densities, walkability scores
7. Return single GeoJSON with all metrics embedded in properties
8. Include: `d.name, d.bezirk, d.geometry` PLUS count metrics (THIS IS CRITICAL FOR FRONTEND DISPLAY)

Template for multi-metric choropleth:
```sql
SELECT
  d.name,
  d.bezirk,
  d.geometry,
  COUNT(*) as total_items,
  COUNT(CASE WHEN <accessibility_condition> THEN 1 END) as accessible_items,
  ROUND(100.0 * COUNT(CASE WHEN <accessibility_condition> THEN 1 END)::numeric / NULLIF(COUNT(*), 0), 1) as accessibility_ratio,
  ROUND(COUNT(*)::numeric / <area_per_km2>, 2) as density_per_km2
FROM vector.berlin_districts d
LEFT JOIN vector.<amenity_table> a ON ST_Within(a.geometry, d.geometry)
LEFT JOIN vector.<reference_table> r ON <spatial_join_condition>
GROUP BY d.name, d.bezirk, d.geometry
ORDER BY accessibility_ratio ASC
```
**CRITICAL:** Include `d.name` in both SELECT and GROUP BY clauses. The `name` field is what users see in popups!

Examples:

Q2: "How many restaurants are within walking distance (800m) of a public transport stop, and which districts have the worst restaurant-to-transport ratio?" →
```json
{
  "operations": [{
    "operation": "spatial_query",
    "parameters": {
      "sql": "SELECT d.name, d.bezirk, d.geometry, COUNT(DISTINCT r.osm_id) as total_restaurants, COUNT(DISTINCT CASE WHEN ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(t.geometry, 3857), 800) THEN r.osm_id END) as accessible_restaurants, ROUND(100.0 * COUNT(DISTINCT CASE WHEN ST_DWithin(ST_Transform(r.geometry, 3857), ST_Transform(t.geometry, 3857), 800) THEN r.osm_id END)::numeric / NULLIF(COUNT(DISTINCT r.osm_id), 0), 1) as accessibility_ratio, COUNT(DISTINCT t.osm_id) as transport_stops FROM vector.berlin_districts d LEFT JOIN vector.osm_restaurants r ON ST_Within(r.geometry, d.geometry) LEFT JOIN vector.osm_transport_stops t ON ST_Within(t.geometry, d.geometry) GROUP BY d.name, d.bezirk, d.geometry ORDER BY accessibility_ratio ASC"
    },
    "description": "Restaurant accessibility to public transport by district with multiple metrics"
  }],
  "layer_name": "restaurant_transport_accessibility_by_district",
  "reasoning": "Analyzing restaurant-to-transport accessibility across Berlin districts to identify underserved areas",
  "datasets_required": ["berlin_districts", "osm_restaurants", "osm_transport_stops"]
}
```

Q6: "Calculate the 'economic vitality score' for each district: (restaurant count + bank count + supermarket count) per 1km² area" →
```json
{
  "operations": [{
    "operation": "spatial_query",
    "parameters": {
      "sql": "SELECT d.name, d.bezirk, d.geometry, COUNT(DISTINCT r.osm_id) as restaurants, COUNT(DISTINCT b.osm_id) as banks, COUNT(DISTINCT s.osm_id) as supermarkets, ROUND(((COUNT(DISTINCT r.osm_id) + COUNT(DISTINCT b.osm_id) + COUNT(DISTINCT s.osm_id))::numeric / NULLIF(ST_Area(ST_Transform(d.geometry, 3857)) / 1000000, 0)), 2) as economic_vitality_score FROM vector.berlin_districts d LEFT JOIN vector.osm_restaurants r ON ST_Within(r.geometry, d.geometry) LEFT JOIN vector.osm_banks b ON ST_Within(b.geometry, d.geometry) LEFT JOIN vector.osm_supermarkets s ON ST_Within(s.geometry, d.geometry) GROUP BY d.name, d.bezirk, d.geometry ORDER BY economic_vitality_score DESC"
    },
    "description": "Economic vitality index by district (restaurants + banks + supermarkets per km²)"
  }],
  "layer_name": "economic_vitality_by_district",
  "reasoning": "Calculating economic vitality using commercial facility density across Berlin districts",
  "datasets_required": ["berlin_districts", "osm_restaurants", "osm_banks", "osm_supermarkets"]
}
```

**RASTER OPERATIONS (for vegetation/NDVI queries):**

"Show areas in Berlin that lost vegetation between 2018 and 2024" →
{"operations": [{"operation": "raster_analysis", "parameters": {"type": "vegetation_loss", "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_20180716.tif", "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_20240721.tif", "threshold": -0.2, "return_geojson": true}, "description": "Detect vegetation loss in Berlin 2018-2024"}], "reasoning": "Using Sentinel-2 NDVI data to identify areas with vegetation decrease", "datasets_required": ["berlin_ndvi_2018", "berlin_ndvi_2024"]}

"Show vegetation gain between 2018 and 2024" / "Where did Berlin get greener?" →
{"operations": [{"operation": "raster_analysis", "parameters": {"type": "vegetation_gain", "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_20180716.tif", "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_20240721.tif", "threshold": 0.2, "return_geojson": true}, "description": "Detect vegetation gain in Berlin 2018-2024"}], "reasoning": "Identifying greening areas from 2018 to 2024", "datasets_required": ["berlin_ndvi_2018", "berlin_ndvi_2024"]}

"What is the overall NDVI change in Berlin?" / "NDVI statistics" / "Vegetation change summary" →
{"operations": [{"operation": "raster_analysis", "parameters": {"type": "ndvi_change", "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_20180716.tif", "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_20240721.tif"}, "description": "Compute NDVI change statistics for Berlin"}], "reasoning": "Calculate overall vegetation change metrics", "datasets_required": ["berlin_ndvi_2018", "berlin_ndvi_2024"]}

"Severe vegetation loss" / "Areas with NDVI drop over 0.3" →
{"operations": [{"operation": "raster_analysis", "parameters": {"type": "vegetation_loss", "ndvi_t1": "raster/ndvi_timeseries/berlin_ndvi_20180716.tif", "ndvi_t2": "raster/ndvi_timeseries/berlin_ndvi_20240721.tif", "threshold": -0.3, "return_geojson": true}, "description": "Severe vegetation loss (threshold -0.3)"}], "reasoning": "Filter for significant vegetation decrease", "datasets_required": ["berlin_ndvi_2018", "berlin_ndvi_2024"]}

**⚠️ CRITICAL - ST_Transform SYNTAX (Most Common Error!):**

**ST_Transform REQUIRES TWO parameters: geometry AND SRID code**
```
ST_Transform(geometry, 3857)   ← Correct: 2 parameters
ST_Transform(geometry)::3857   ← WRONG: missing SRID parameter
ST_Transform(geometry)::numeric, 3857  ← WRONG: misplaced parameters
```

**When using ST_Area with ST_Transform:**
```sql
-- ❌ WRONG:
ST_Area(ST_Transform(d.geometry)::numeric, 3857)
ST_Area(ST_Transform(d.geometry, 3857), 3857)
ST_Area(ST_Transform(d.geometry)::numeric / 1000000, 3857)

-- ✅ CORRECT:
ST_Area(ST_Transform(d.geometry, 3857))
ROUND(ST_Area(ST_Transform(d.geometry, 3857)) / 1000000, 2)
```

**⚠️ CRITICAL OPTIMIZATION - "BEST FOR BUSINESS" & MULTI-CRITERIA QUERIES:**

PERFORMANCE WARNING: Queries combining 6+ amenity tables with multiple LEFT JOINs can take 30+ seconds.

**RECOMMENDED APPROACH FOR "BEST FOR BUSINESS" & SIMILAR QUERIES:**
Instead of: Heavy 6-way JOIN with density calculations
Use: Lightweight 2-way JOIN with simple counts, OR separate queries

**FAST Template (Recommended for "best for business"):**
```sql
SELECT
  d.id, d.name, d.bezirk, d.geometry,
  COUNT(DISTINCT s.osm_id) as supermarkets,
  COUNT(DISTINCT b.osm_id) as banks,
  COUNT(DISTINCT r.osm_id) as restaurants,
  COUNT(DISTINCT t.osm_id) as transport_stops
FROM vector.berlin_districts d
LEFT JOIN vector.osm_supermarkets s ON ST_Within(s.geometry, d.geometry)
LEFT JOIN vector.osm_banks b ON ST_Within(b.geometry, d.geometry)
LEFT JOIN vector.osm_restaurants r ON ST_Within(r.geometry, d.geometry)
LEFT JOIN vector.osm_transport_stops t ON ST_Within(t.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
ORDER BY supermarkets DESC, banks DESC, restaurants DESC
```
**Why this is faster:**
- Only 4 JOINs (not 6+) = ~50% less query time
- No expensive ST_Area density calculations
- Results sorted by absolute count (user can see clearly which areas are best)
- Minimal geometric calculations

**⚠️ COMPLEX MULTI-METRIC AGGREGATION QUERIES (Family-Friendly, Walkability Scores, etc.):**

For queries that combine multiple criteria to find "best areas", use SIMPLE multi-table aggregation:

CRITICAL RULES:
1. ST_Area() works on geometry: ST_Area(ST_Transform(geometry, 3857))
2. ST_Transform has 2 parameters: ST_Transform(geometry, 3857)
3. Do NOT apply ST_Transform twice - ST_Area(ST_Transform(..., 3857), 3857) is WRONG
4. Always calculate area in SQUARE METERS (3857 is Web Mercator), then divide by 1,000,000 for km²
5. For multi-metric scoring, SUM counts of different amenities and divide by area
6. Use LEFT JOIN to ensure ALL districts are returned (even those with 0 amenities)
7. GROUP BY ALL district columns AND geometry
8. Include COUNT(DISTINCT osm_id) for each amenity type to avoid double-counting
9. ⚠️ ONLY add density calculations if user explicitly asks for "density" or "per km²"

SIMPLE Template (Start here - most reliable):
```sql
SELECT
  d.id,
  d.name,
  d.bezirk,
  d.geometry,
  COUNT(DISTINCT s.osm_id) as schools,
  COUNT(DISTINCT p.osm_id) as parks,
  COUNT(DISTINCT pol.osm_id) as police_stations,
  COUNT(DISTINCT f.osm_id) as fire_stations
FROM vector.berlin_districts d
LEFT JOIN vector.osm_schools s ON ST_Within(s.geometry, d.geometry)
LEFT JOIN vector.osm_parks p ON ST_Within(p.geometry, d.geometry)
LEFT JOIN vector.osm_police_stations pol ON ST_Within(pol.geometry, d.geometry)
LEFT JOIN vector.osm_fire_stations f ON ST_Within(f.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
ORDER BY (schools + parks + police_stations + fire_stations) DESC
```

** FOR EACH METRIC with Proper Scoring (if needed):**
When calculating scores with area, break it into steps:
```sql
-- Step 1: Calculate area in km²
SELECT d.geometry, ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0 as area_km2 FROM vector.berlin_districts d

-- Step 2: Then divide counts by area
SELECT
  d.name,
  COUNT(DISTINCT amenity.osm_id) as count,
  ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0 as area_km2,
  COUNT(DISTINCT amenity.osm_id) / (ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0) as density
FROM vector.berlin_districts d
LEFT JOIN vector.osm_table amenity ON ST_Within(amenity.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
```

**FAMILY-FRIENDLY AREAS WITH DENSITY SCORING:**
When user asks "Which areas/districts are best for families (schools + parks + security)" - calculate DENSITY-BASED SCORE:
```sql
SELECT
  d.id,
  d.name,
  d.bezirk,
  d.geometry,
  COUNT(DISTINCT s.osm_id) as schools,
  COUNT(DISTINCT p.osm_id) as parks,
  COUNT(DISTINCT pol.osm_id) as police_stations,
  COUNT(DISTINCT f.osm_id) as fire_stations,
  (COUNT(DISTINCT s.osm_id) + COUNT(DISTINCT p.osm_id) + COUNT(DISTINCT pol.osm_id) + COUNT(DISTINCT f.osm_id)) as total_amenities,
  ROUND((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 2) as area_km2,
  ROUND((COUNT(DISTINCT s.osm_id) + COUNT(DISTINCT p.osm_id) + COUNT(DISTINCT pol.osm_id) + COUNT(DISTINCT f.osm_id))::numeric / NULLIF((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 0), 2) as amenities_per_km2
FROM vector.berlin_districts d
LEFT JOIN vector.osm_schools s ON ST_Within(s.geometry, d.geometry)
LEFT JOIN vector.osm_parks p ON ST_Within(p.geometry, d.geometry)
LEFT JOIN vector.osm_police_stations pol ON ST_Within(pol.geometry, d.geometry)
LEFT JOIN vector.osm_fire_stations f ON ST_Within(f.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
ORDER BY amenities_per_km2 DESC
```

KEY POINTS FOR FAMILY-FRIENDLY SCORING:
1. Calculate area_km2: `ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0`
2. Sum all amenities: `schools + parks + police_stations + fire_stations`
3. Density score: `total_amenities / area_km2` (amenities per square kilometer)
4. Return ALL districts sorted by density DESC (higher density = more family-friendly)
5. Include both absolute counts AND density score in results
6. Layer name: "family_friendly_areas_by_amenity_density" or similar

Example German Language Query (Exact):
User: "Welche Gegenden eignen sich am besten für Familien (Schulen + Parks + Sicherheitsdienste)?"
Translation: "Which areas are best suited for families (schools + parks + security services)?"
Action: Generate the FAMILY-FRIENDLY DENSITY-BASED SCORING query above with:
  - schools (osm_schools)
  - parks (osm_parks)
  - police stations (osm_police_stations)
  - fire stations (osm_fire_stations)
  - Calculate amenities_per_km2 as density score
  - Sort by amenities_per_km2 DESC (highest density first = most family-friendly)

Key Points:
1. Each COUNT(DISTINCT x.osm_id) counts unique features from that table
2. Always use ST_Within() for containment checks (NOT ST_DWithin)
3. ALWAYS include d.id in GROUP BY for berlin_districts table
4. Never apply ST_Transform twice in same expression
5. Use NULLIF to prevent division by zero
6. Final score = amenities_per_km2 (higher = better)

**⚠️ MULTI-CRITERIA DECISION ANALYSIS (MCDA) - DENSITY-BASED SCORING:**

When user asks "Which areas are best for [profile]?" with MULTIPLE criteria (e.g., "families", "students", "seniors"), generate SQL that calculates INDIVIDUAL DENSITY for each criterion.

**MCDA Profiles and Default Criteria:**
- **family:** schools, parks, supermarkets, hospitals, police_stations, fire_stations
- **student:** universities, libraries, restaurants, supermarkets, transport_stops, banks
- **senior:** hospitals, pharmacies, parks, supermarkets, transport_stops, doctors
- **shopping:** supermarkets, banks, atm, post_offices, parking, restaurants
- **culture:** museums, theatres, libraries, restaurants, transport_stops, parks
- **health:** hospitals, pharmacies, doctors, parks, dentists, veterinary
- **walkable:** parks, restaurants, supermarkets, transport_stops, libraries
- **green:** parks, forests, water_bodies, transport_stops

**⚠️ CRITICAL - MCDA SQL REQUIREMENTS:**
For multi-criteria queries, generate SQL that returns:
1. District id, name, bezirk, geometry (for map display)
2. COUNT(DISTINCT osm_id) for EACH amenity type mentioned
3. Area in km²: `ROUND((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 2) as area_km2`
4. **Individual density for EACH criterion:** `<amenity>_density = COUNT(DISTINCT osm_id) / area_km2`
5. Sort by most relevant density DESC

**MCDA SQL Template (Required Format):**
```sql
SELECT
  d.id,
  d.name,
  d.bezirk,
  d.geometry,
  -- Counts for each criterion
  COUNT(DISTINCT school.osm_id) as schools,
  COUNT(DISTINCT park.osm_id) as parks,
  COUNT(DISTINCT super.osm_id) as supermarkets,
  COUNT(DISTINCT hosp.osm_id) as hospitals,
  -- Area calculation
  ROUND((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 2) as area_km2,
  -- Individual densities for each criterion (REQUIRED FOR MCDA SCORING)
  ROUND(COUNT(DISTINCT school.osm_id)::numeric / NULLIF((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 0), 4) as schools_density,
  ROUND(COUNT(DISTINCT park.osm_id)::numeric / NULLIF((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 0), 4) as parks_density,
  ROUND(COUNT(DISTINCT super.osm_id)::numeric / NULLIF((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 0), 4) as supermarkets_density,
  ROUND(COUNT(DISTINCT hosp.osm_id)::numeric / NULLIF((ST_Area(ST_Transform(d.geometry, 3857)) / 1000000.0)::numeric, 0), 4) as hospitals_density
FROM vector.berlin_districts d
LEFT JOIN vector.osm_schools school ON ST_Within(school.geometry, d.geometry)
LEFT JOIN vector.osm_parks park ON ST_Within(park.geometry, d.geometry)
LEFT JOIN vector.osm_supermarkets super ON ST_Within(super.geometry, d.geometry)
LEFT JOIN vector.osm_hospitals hosp ON ST_Within(hosp.geometry, d.geometry)
GROUP BY d.id, d.name, d.bezirk, d.geometry
ORDER BY schools_density DESC, parks_density DESC
```

**MCDA Query Example (Family-Friendly):**
User: "Welche Gegenden eignen sich am besten für Familien (Schulen + Parks + Sicherheitsdienste)?"
→ Translate to: schools, parks, police_stations, fire_stations
→ Generate SQL with individual density for each:
  - schools_density = COUNT(schools) / area_km2
  - parks_density = COUNT(parks) / area_km2
  - police_density = COUNT(police_stations) / area_km2
  - fire_density = COUNT(fire_stations) / area_km2

**CRITICAL RULES FOR MCDA:**
1. ALWAYS include individual _density field for EACH criterion (not just aggregate)
2. Field naming: `<table_name_without_osm_prefix>_density` (e.g., schools_density, parks_density)
3. Calculate area_km2 ONCE and reuse in all density calculations
4. Use COUNT(DISTINCT osm_id) to avoid duplicate counting with multiple LEFT JOINs
5. Use NULLIF to prevent division by zero
6. Round to 4 decimal places for density values for precision
7. Order by primary criterion first (e.g., schools_density for family queries)
8. Include ALL districts in results (even those with 0 amenities) via LEFT JOIN
9. Layer name should describe the profile: "family_friendly_areas", "student_friendly_areas", etc.

**If user requests unavailable amenities:**
- Example: "Families (schools + kindergartens + parks)" but kindergartens table doesn't exist
- SKIP the unavailable table in the SQL
- Include in reasoning: "Note: Kindergarten data not available. Analysis based on schools and parks."
- System backend will redistribute weights proportionally

**⭐ SELECTED FEATURE CONTEXT (CRITICAL - AUTOMATIC USAGE):**
When a selected_feature is provided in the context (user selected a feature on the map):
- ALWAYS use the selected feature's geometry in spatial operations - DO NOT require explicit mention
- The selected feature is provided as: geometry (WKT format), geometry_type, name, properties
- Apply the selected geometry AUTOMATICALLY to spatial queries:

**For "within" / "inside" type queries:**
```sql
SELECT <table>.*
FROM vector.<table>
WHERE ST_Within(geometry, ST_GeomFromText('<selected_geometry_wkt>', 4326))
```

**For "near" / "within distance" type queries:**
```sql
SELECT <table>.*
FROM vector.<table>
WHERE ST_DWithin(ST_Transform(geometry, 3857), ST_Transform(ST_GeomFromText('<selected_geometry_wkt>', 4326), 3857), <distance_meters>)
ORDER BY ST_Distance(ST_Transform(geometry, 3857), ST_Transform(ST_GeomFromText('<selected_geometry_wkt>', 4326), 3857))
```

**IMPORTANT:**
- User does NOT need to say "the selected [feature]" - just ask the question naturally
- Example user queries (all should use selected geometry automatically):
  - "find ATMs within 1 km" → applies within selected geometry + 1km
  - "show restaurants" → applies ST_Within selected geometry
  - "what hospitals are nearby" → applies ST_DWithin from selected geometry
- Extract distance from query (default to 500m if not specified)
- If no selected feature, treat as normal query (search globally)

**🛣️ ROUTING & CONNECTIVITY QUERIES - NEW FEATURE:**

When users select MULTIPLE features (3+) on the map and ask about connectivity/routing between them:
- **Keywords**: "connectivity", "connected", "connect", "route", "path", "linking", "between", "among"
- **Examples**:
  - "Find connectivity between these hospitals"
  - "Show routes connecting the selected items"
  - "How are these connected by roads?"
  - "Find connectivity among the selected features"

**DETECTION RULE:**
✅ If query contains connectivity keywords AND user has 3+ items selected:
→ Return operation with type "routing"

❌ If user asks connectivity WITHOUT multiple selections OR without connectivity keywords:
→ Treat as normal spatial query

**ROUTING OPERATION RESPONSE FORMAT:**
```json
{
  "operations": [
    {
      "operation": "routing",
      "parameters": {
        "geometries": [<selected_feature_geometries>],
        "feature_names": [<names_or_labels>]
      },
      "description": "Find shortest road paths connecting all selected features (pairwise)"
    }
  ],
  "reasoning": "User selected N features and asked about connectivity. Computing all pairwise shortest paths using pgRouting Dijkstra algorithm on Berlin road network.",
  "datasets_required": ["routing.ways (Berlin road network)"]
}
```

**IMPORTANT:**
- ONLY use routing operation when:
  1. User explicitly asks about connectivity/routes/connections
  2. Multiple features (3+) are selected on the map
  3. Features are Point geometries (snapped to nearest road vertex)
- Routing computes ALL pairwise shortest paths (3 items = 3 routes, 4 items = 6 routes)
- Results include: route geometry (LineString), distance for each segment, total distance
- No SQL needed - routing engine handles pgRouting queries directly
- Berlin road network: 43,420 road segments, 30,922 vertices (Detailnetz)"""


def _get_location_filter_column(location_name: str) -> str:
    """
    Determine if a location is a main district (Bezirk) or subdivision (Ortsteil).
    Returns the appropriate column name to use in SQL WHERE clause.

    Args:
        location_name: Name of the location (e.g., 'Mitte', 'Kladow', 'Spandau')

    Returns:
        'bezirk' if it's a main district, 'name' if it's a subdivision
    """
    # Main districts (Bezirke) - 12 total
    main_districts = {
        'mitte', 'friedrichshain-kreuzberg', 'pankow', 'charlottenburg-wilmersdorf',
        'spandau', 'steglitz-zehlendorf', 'tempelhof-schöneberg', 'neukölln',
        'treptow-köpenick', 'marzahn-hellersdorf', 'lichtenberg', 'reinickendorf'
    }

    location_lower = location_name.lower().strip()
    if location_lower in main_districts:
        return 'bezirk'
    else:
        # It's likely a subdivision (Ortsteil)
        return 'name'


def _hash_selected_feature(selected_feature: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Create a hash of selected feature (excluding the large WKT geometry).
    This prevents cache keys from becoming too large.
    """
    if not selected_feature:
        return None

    import hashlib
    # Only hash the feature name and type, not the massive geometry
    feature_summary = {
        'name': selected_feature.get('name'),
        'geometry_type': selected_feature.get('geometry_type')
    }
    feature_str = json.dumps(feature_summary, sort_keys=True)
    return hashlib.md5(feature_str.encode()).hexdigest()


def _generate_cache_key(prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Generate a unique cache key for a query."""
    cache_str = prompt.lower().strip()
    if context:
        cache_str += json.dumps(context, sort_keys=True)
    return cache_str


def _get_database_schema_for_llm() -> str:
    """
    Get the LIVE database schema from PostGIS.

    Fetches descriptions, row counts, and column info directly from the database.
    Also checks for temporary layers created from selected features.

    Returns:
        Formatted string with all available tables and descriptions for LLM
    """
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text

        # Fetch live schema from database (vector schema)
        tables_data = db_manager.get_schema_with_descriptions()

        if not tables_data:
            tables_data = []

        # Format for LLM
        schema_text = "**Available Tables in Database:**\n\n"

        # Add vector schema tables
        schema_text += "**SCHEMA: vector (main spatial data)**\n"
        schema_text += "-" * 60 + "\n"

        for table_info in sorted(tables_data, key=lambda x: x["table"]):
            table_name = table_info["table"]
            description = table_info["description"]
            row_count = table_info.get("row_count", 0)
            geometry = table_info.get("geometry", "NONE")
            columns = table_info.get("columns", [])

            # Format table entry
            schema_text += f"**{table_name}**\n"
            schema_text += f"  Description: {description}\n"
            schema_text += f"  Records: {row_count} | Geometry: {geometry}\n"
            schema_text += f"  Columns: {', '.join(columns[:10])}"

            if len(columns) > 10:
                schema_text += f", ... ({len(columns)} total)"

            schema_text += "\n\n"

        # Check for temporary selected feature layers
        try:
            temp_tables = []
            with db_manager.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'temp' AND table_name LIKE 'temp_selected_%'
                    ORDER BY table_name
                """))
                temp_tables = [row[0] for row in result]

            if temp_tables:
                schema_text += "\n**SCHEMA: temp (selected feature layers)**\n"
                schema_text += "-" * 60 + "\n"

                for temp_table in temp_tables:
                    # Get info about temp table using a fresh connection
                    try:
                        with db_manager.engine.connect() as conn2:
                            result = conn2.execute(text(f"""
                                SELECT COUNT(*) as count,
                                       ST_GeometryType((array_agg(geometry))[1]) as geom_type
                                FROM temp.{temp_table}
                            """))
                            row = result.first()
                            count = row[0] if row else 0
                            geom_type = row[1] if row else "Unknown"

                            schema_text += f"**{temp_table}**\n"
                            schema_text += f"  Description: Temporary layer from selected feature\n"
                            schema_text += f"  Records: {count} | Geometry: {geom_type}\n"
                            schema_text += f"  Columns: id, geometry\n\n"
                    except Exception as table_error:
                        print(f"⚠️ Could not get info for temp table {temp_table}: {table_error}")
                        # Still list the temp table even if we can't get info
                        schema_text += f"**{temp_table}**\n"
                        schema_text += f"  Description: Temporary layer from selected feature\n"
                        schema_text += f"  Columns: id, geometry\n\n"
        except Exception as e:
            print(f"⚠️ Note: Could not query temp schema: {e}")

        return schema_text

    except Exception as e:
        print(f"⚠️ Error getting database schema: {e}")
        # Fallback to static version
        return "Unable to fetch live schema from database"


def _build_dynamic_system_prompt(user_query: str) -> str:
    """
    Build a system prompt with LIVE table descriptions from the database.

    Single source of truth: descriptions are stored in vector.table_metadata
    No hardcoded keyword mappings - LLM reads descriptions to understand what's available.

    Args:
        user_query: The user's natural language question

    Returns:
        Complete system prompt with live database schema information
    """
    try:
        # Get the base prompt (core instructions, rules, examples)
        base_prompt = SYSTEM_PROMPT.split("**Available Tables")[0]

        # Get LIVE schema from database (descriptions, row counts, columns)
        schema_section = _get_database_schema_for_llm()

        # Get the post-table rules section
        post_tables = SYSTEM_PROMPT.split("**⚠️ UNAVAILABLE TABLES")[1] if "**⚠️ UNAVAILABLE TABLES" in SYSTEM_PROMPT else ""

        # Combine into final prompt
        final_prompt = base_prompt + "\n" + schema_section + "\n**⚠️ UNAVAILABLE TABLES" + post_tables

        return final_prompt

    except Exception as e:
        print(f"⚠️ Error building dynamic prompt: {e}")
        # Gracefully fall back to static prompt on any error
        return SYSTEM_PROMPT


def query_deepseek(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None) -> Dict[str, str]:
    """
    Query DeepSeek API with a prompt, using simple in-memory cache.
    Dynamically builds prompts with only relevant tables for the query.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster') to guide LLM response format
        selected_feature: Optional selected feature from map for context-aware queries

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

    # Check cache first (include user_location and query_type in cache key)
    # Note: selected_feature is now handled via temp database layers, not in cache key
    cache_context = {**(context or {}), **({"user_location": user_location} if user_location else {}), **({"query_type": query_type} if query_type else {})}
    cache_key = _generate_cache_key(prompt, cache_context if cache_context else None)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached response")
        return _query_cache[cache_key]  # Returns dict with content, system_prompt, user_prompt

    # Build dynamic system prompt with relevant tables
    system_prompt = _build_dynamic_system_prompt(prompt)

    # Build the full prompt with context and user_location if provided
    full_prompt = prompt

    # Add query type hint to prompt if specified
    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    # Add user location to prompt if available
    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    # Add additional context if provided
    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Note: selected_feature is now handled via temp database layers
    # The schema automatically includes temp_selected_* tables that the LLM can query

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0,  # Zero temperature for deterministic SQL generation
        "max_tokens": 1500  # Increased for complex queries (grid-based density, multi-step operations)
    }

    try:
        print(f"🧠 Querying DeepSeek API ({DEEPSEEK_MODEL})...")
        print("\n" + "="*80)
        print("📤 DEEPSEEK SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 DEEPSEEK USER PROMPT:")
        print("="*80)
        print(full_prompt)
        print("="*80 + "\n")
        response = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60  # Increased for selected features with large geometries
        )
        response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Create response dict with all three components
        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        # Cache the response (limit cache size)
        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()  # Simple cache eviction
        _query_cache[cache_key] = response_dict

        print(f"✅ DeepSeek response received ({len(content)} chars)")
        return response_dict

    except requests.exceptions.Timeout:
        raise Exception("DeepSeek API timeout. Please try a simpler query.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"DeepSeek API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from DeepSeek: {str(e)}")

def parse_geospatial_query(question: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, selected_features: List[Dict[str, Any]] = None) -> OperationPlan:
    """
    Parse a natural language geospatial query into structured operations.
    Uses DeepSeek API to convert natural language to SQL.

    Args:
        question: Natural language query
        context: Optional context (city, timeframe, etc.)
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster', 'routing') to guide response format
        selected_feature: Optional selected feature from map for context-aware queries
        selected_features: Optional list of multiple selected features (for routing)

    Returns:
        OperationPlan with structured operations
    """
    # Check for routing keywords when multiple features are selected
    routing_keywords = ['route', 'directions', 'navigate', 'routing', 'path', 'journey', 'tour', 'visit', 'loop', 'best route', 'find route']
    is_routing_query = any(keyword in question.lower() for keyword in routing_keywords)

    # If routing query with 2+ selected features, create routing operation directly
    if is_routing_query and selected_features and len(selected_features) >= 2:
        print(f"🛣️  Detected routing query with {len(selected_features)} selected features")

        # Extract geometries and names from selected features
        geometries = []
        feature_names = []

        for feature in selected_features:
            if isinstance(feature, dict):
                if 'geometry' in feature:
                    geometries.append(feature['geometry'])
                if 'properties' in feature and 'name' in feature['properties']:
                    feature_names.append(feature['properties']['name'])
                elif 'name' in feature:
                    feature_names.append(feature['name'])
                else:
                    feature_names.append(f"Point {len(feature_names) + 1}")

        if geometries and len(geometries) >= 2:
            return OperationPlan(
                operations=[
                    GeospatialOperation(
                        operation="routing",
                        parameters={
                            "geometries": geometries,
                            "feature_names": feature_names,
                            "mode": "optimal_tour"
                        },
                        description="Find optimal tour connecting selected features"
                    )
                ],
                reasoning="Computing optimal route through all selected locations using Nearest Neighbor TSP algorithm",
                datasets_required=["routing.ways", "routing.ways_vertices_pgr"],
                layer_name="optimal_route"
            )

    # Query DeepSeek for non-routing queries or routing queries without sufficient selected features
    response_dict = query_deepseek(question, context, user_location, query_type if not is_routing_query else "routing", selected_feature)

    # Extract the content, system_prompt, and user_prompt from the dict
    raw_content = response_dict.get("content", "")
    system_prompt = response_dict.get("system_prompt", "")
    user_prompt = response_dict.get("user_prompt", "")

    # Try to parse the JSON response
    try:
        # Clean the response - sometimes LLMs wrap JSON in markdown
        cleaned_response = raw_content.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Attempt to parse JSON - with retry logic for common escaping issues
        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as first_error:
            # Try fixing common JSON escaping issues (unescaped quotes in SQL strings)
            import re

            # Look for SQL strings with unescaped quotes and try to fix them
            # Pattern: "sql": "SELECT ... " where " inside should be \"
            fixed_response = cleaned_response

            # Fix unescaped quotes within SQL strings
            # This is a heuristic approach - look for "sql": "...SELECT..." patterns
            pattern = r'"sql"\s*:\s*"((?:[^"\\]|\\.)*?(?:SELECT|INSERT|UPDATE|DELETE|WITH)[^"]*?)"'

            def escape_sql_string(match):
                sql_content = match.group(1)
                # Escape any unescaped quotes in the SQL
                # Don't escape quotes that are already escaped
                escaped = sql_content.replace('"', '\\"').replace('\\"\\', '\\"')
                return f'"sql": "{escaped}"'

            fixed_response = re.sub(pattern, escape_sql_string, fixed_response, flags=re.IGNORECASE | re.DOTALL)

            # Try parsing again with fixed response
            try:
                parsed = json.loads(fixed_response)
                print("✅ JSON parsing fixed with escape handling")
            except json.JSONDecodeError as second_error:
                # If still failing, log and raise original error
                print(f"❌ JSON parsing still failed after escape fix: {second_error}")
                raise first_error

        # Convert to OperationPlan
        operations = [
            GeospatialOperation(**op) for op in parsed.get("operations", [])
        ]

        return OperationPlan(
            operations=operations,
            layer_name=parsed.get("layer_name"),
            reasoning=parsed.get("reasoning"),
            datasets_required=parsed.get("datasets_required", []),
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

    except json.JSONDecodeError as e:
        # If JSON parsing fails, create a simple fallback plan
        print(f"Failed to parse DeepSeek response as JSON: {e}")
        print(f"Raw response: {raw_content}")

        # Return a basic error plan
        return OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={"error": "Failed to parse query"},
                    description=f"Could not parse: {question}"
                )
            ],
            reasoning=f"Error parsing response: {raw_content}",
            datasets_required=[],
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )


def clear_query_cache() -> None:
    """
    Clear the in-memory query cache.
    Useful for testing or resetting the system.
    """
    global _query_cache
    _query_cache.clear()
    print("✅ Query cache cleared")


def get_available_datasets() -> List[Dict[str, Any]]:
    """
    Return list of available datasets from PostGIS.
    Queries actual database tables.
    """
    from app.utils.database import db_manager

    try:
        # Get tables from PostGIS
        tables = db_manager.get_available_tables(schema="vector")

        datasets = []
        for table in tables:
            try:
                info = db_manager.get_table_info(table, schema="vector")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": f"{info['geometry_type']} - {info['row_count']} features",
                    "schema": "vector",
                    "row_count": info['row_count'],
                    "geometry_type": info['geometry_type'],
                    "columns": [col['name'] for col in info['columns']]
                })
            except Exception as e:
                print(f"Could not get info for table {table}: {e}")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": "PostGIS table",
                    "schema": "vector"
                })

        return datasets

    except Exception as e:
        print(f"Could not query database for datasets: {e}")
        # Fallback to known Berlin OSM tables
        return [
            {"name": "osm_hospitals", "type": "vector", "description": "Hospital locations in Berlin (59 features)", "schema": "vector"},
            {"name": "osm_toilets", "type": "vector", "description": "Public toilets in Berlin (1,160 features)", "schema": "vector"},
            {"name": "osm_pharmacies", "type": "vector", "description": "Pharmacy locations in Berlin (768 features)", "schema": "vector"},
            {"name": "osm_fire_stations", "type": "vector", "description": "Fire stations in Berlin (179 features)", "schema": "vector"},
            {"name": "osm_police_stations", "type": "vector", "description": "Police stations in Berlin (81 features)", "schema": "vector"},
            {"name": "osm_parks", "type": "vector", "description": "Parks in Berlin (2,785 features)", "schema": "vector"},
            {"name": "osm_schools", "type": "vector", "description": "Schools in Berlin (1,195 features)", "schema": "vector"},
            {"name": "osm_restaurants", "type": "vector", "description": "Restaurants in Berlin (5,013 features)", "schema": "vector"},
            {"name": "osm_transport_stops", "type": "vector", "description": "Transport stops in Berlin (14,899 features)", "schema": "vector"},
        ]
