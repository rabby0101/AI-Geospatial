-- ============================================================
-- Spatial Index Optimization Script for Berlin Geospatial Data
-- Uses EPSG:25833 (UTM zone 33N) for meter-based distance queries
-- ============================================================

-- 1. Add projected geometry columns (EPSG:25833) to key tables
-- This allows ST_DWithin to use meters directly without ::geography casting

-- Schools
ALTER TABLE vector.osm_schools ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_schools SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_schools_geom_25833 ON vector.osm_schools USING GIST (geom_25833);

-- Buildings
ALTER TABLE vector.osm_buildings ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_buildings SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_buildings_geom_25833 ON vector.osm_buildings USING GIST (geom_25833);

-- Street Lights
ALTER TABLE vector.osm_street_lights ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_street_lights SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_street_lights_geom_25833 ON vector.osm_street_lights USING GIST (geom_25833);

-- Road Segments (Custom)
ALTER TABLE vector.custom_roads ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.custom_roads SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_custom_roads_geom_25833 ON vector.custom_roads USING GIST (geom_25833);

-- Districts
ALTER TABLE vector.berlin_districts ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.berlin_districts SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_berlin_districts_geom_25833 ON vector.berlin_districts USING GIST (geom_25833);

-- Transport Stops
ALTER TABLE vector.osm_transport_stops ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_transport_stops SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_transport_stops_geom_25833 ON vector.osm_transport_stops USING GIST (geom_25833);

-- Hospitals
ALTER TABLE vector.osm_hospitals ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_hospitals SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_hospitals_geom_25833 ON vector.osm_hospitals USING GIST (geom_25833);

-- Parks
ALTER TABLE vector.osm_parks ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_parks SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_parks_geom_25833 ON vector.osm_parks USING GIST (geom_25833);

-- Traffic Accidents
ALTER TABLE vector.traffic_accidents ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.traffic_accidents SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_traffic_accidents_geom_25833 ON vector.traffic_accidents USING GIST (geom_25833);

-- Fire Stations
ALTER TABLE vector.osm_fire_stations ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_fire_stations SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_fire_stations_geom_25833 ON vector.osm_fire_stations USING GIST (geom_25833);

-- Supermarkets
ALTER TABLE vector.osm_supermarkets ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_supermarkets SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_supermarkets_geom_25833 ON vector.osm_supermarkets USING GIST (geom_25833);

-- Restaurants
ALTER TABLE vector.osm_restaurants ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_restaurants SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_restaurants_geom_25833 ON vector.osm_restaurants USING GIST (geom_25833);

-- Libraries
ALTER TABLE vector.osm_libraries ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_libraries SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_libraries_geom_25833 ON vector.osm_libraries USING GIST (geom_25833);

-- Universities
ALTER TABLE vector.osm_universities ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.osm_universities SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_osm_universities_geom_25833 ON vector.osm_universities USING GIST (geom_25833);

-- Landmarks
ALTER TABLE vector.landmarks ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.landmarks SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_landmarks_geom_25833 ON vector.landmarks USING GIST (geom_25833);

-- Micro-mobility stands
ALTER TABLE vector.abstell_mikromob ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833);
UPDATE vector.abstell_mikromob SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL;
CREATE INDEX IF NOT EXISTS idx_abstell_mikromob_geom_25833 ON vector.abstell_mikromob USING GIST (geom_25833);

-- 2. Analyze tables to update statistics for query planner
ANALYZE vector.osm_schools;
ANALYZE vector.osm_buildings;
ANALYZE vector.osm_street_lights;
ANALYZE vector.custom_roads;
ANALYZE vector.berlin_districts;
ANALYZE vector.osm_transport_stops;
ANALYZE vector.osm_hospitals;
ANALYZE vector.osm_parks;
ANALYZE vector.traffic_accidents;
ANALYZE vector.osm_fire_stations;
ANALYZE vector.osm_supermarkets;
ANALYZE vector.osm_restaurants;
ANALYZE vector.osm_libraries;
ANALYZE vector.osm_universities;
ANALYZE vector.landmarks;
ANALYZE vector.abstell_mikromob;

-- 3. Verification query (after running this script)
-- This should show all the new indexes:
-- SELECT indexname, tablename FROM pg_indexes 
-- WHERE schemaname = 'vector' AND indexname LIKE '%_25833%';
