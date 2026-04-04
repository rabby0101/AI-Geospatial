-- Fix stale geometry_type in metadata.table_descriptions
-- 41 tables had geometry_type = NULL despite having real geometry columns.
-- This caused the LLM schema context to show "NONE ⚠️ NO GEOMETRY COLUMNS"
-- for tables that actually have geometry, leading to broken SQL generation.
--
-- Run once: psql -d geoassist -f scripts/fix_geometry_types.sql

UPDATE metadata.table_descriptions td
SET geometry_type = gc.type
FROM geometry_columns gc
WHERE gc.f_table_schema = 'vector'
  AND gc.f_table_name = td.table_name
  AND gc.f_geometry_column = 'geometry'
  AND (td.geometry_type IS NULL OR td.geometry_type = 'NONE' OR td.geometry_type = 'Unknown');

-- Verify
SELECT table_name, geometry_type
FROM metadata.table_descriptions
WHERE table_name IN (
    'osm_cafes', 'osm_amenity_areas', 'osm_restaurants', 'wfs_alkis_bezirk',
    'osm_bars', 'osm_hospitals', 'osm_supermarkets', 'berlin_subdivision_population'
)
ORDER BY table_name;
