-- Script to add geom_25833 (EPSG:25833 - UTM zone 33N) column to all tables
-- This ensures consistent schema across all spatial tables for fast distance queries
-- 1 unit in EPSG:25833 = 1 meter, making ST_DWithin and ST_Distance much faster

-- ============================================================================
-- Tables that need geom_25833 column added
-- ============================================================================

-- osm_parking
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_parking' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_parking ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_parking SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_parking_geom_25833 ON vector.osm_parking USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_parking';
    ELSE
        RAISE NOTICE 'osm_parking already has geom_25833';
    END IF;
END $$;

-- osm_atm
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_atm' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_atm ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_atm SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_atm_geom_25833 ON vector.osm_atm USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_atm';
    ELSE
        RAISE NOTICE 'osm_atm already has geom_25833';
    END IF;
END $$;

-- osm_banks
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_banks' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_banks ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_banks SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_banks_geom_25833 ON vector.osm_banks USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_banks';
    ELSE
        RAISE NOTICE 'osm_banks already has geom_25833';
    END IF;
END $$;

-- osm_post_offices
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_post_offices' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_post_offices ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_post_offices SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_post_offices_geom_25833 ON vector.osm_post_offices USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_post_offices';
    ELSE
        RAISE NOTICE 'osm_post_offices already has geom_25833';
    END IF;
END $$;

-- osm_forests
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_forests' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_forests ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_forests SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_forests_geom_25833 ON vector.osm_forests USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_forests';
    ELSE
        RAISE NOTICE 'osm_forests already has geom_25833';
    END IF;
END $$;

-- osm_water_bodies
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'vector' AND table_name = 'osm_water_bodies' AND column_name = 'geom_25833'
    ) THEN
        ALTER TABLE vector.osm_water_bodies ADD COLUMN geom_25833 geometry(Geometry, 25833);
        UPDATE vector.osm_water_bodies SET geom_25833 = ST_Transform(geometry, 25833);
        CREATE INDEX IF NOT EXISTS idx_osm_water_bodies_geom_25833 ON vector.osm_water_bodies USING GIST (geom_25833);
        RAISE NOTICE 'Added geom_25833 to osm_water_bodies';
    ELSE
        RAISE NOTICE 'osm_water_bodies already has geom_25833';
    END IF;
END $$;

-- ============================================================================
-- Dynamic script to add geom_25833 to ALL tables in vector schema that have 
-- a geometry column but are missing geom_25833
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    geom_col TEXT;
BEGIN
    FOR r IN 
        SELECT f_table_name as table_name, f_geometry_column as geom_column
        FROM geometry_columns
        WHERE f_table_schema = 'vector'
        AND f_geometry_column = 'geometry'
        AND f_table_name NOT IN (
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = 'vector' AND column_name = 'geom_25833'
        )
    LOOP
        RAISE NOTICE 'Processing table: %', r.table_name;
        
        -- Add the column
        EXECUTE format('ALTER TABLE vector.%I ADD COLUMN IF NOT EXISTS geom_25833 geometry(Geometry, 25833)', r.table_name);
        
        -- Populate it
        EXECUTE format('UPDATE vector.%I SET geom_25833 = ST_Transform(geometry, 25833) WHERE geom_25833 IS NULL', r.table_name);
        
        -- Create spatial index
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_geom_25833 ON vector.%I USING GIST (geom_25833)', r.table_name, r.table_name);
        
        RAISE NOTICE 'Completed: %', r.table_name;
    END LOOP;
END $$;

-- ============================================================================
-- Verify all tables now have geom_25833
-- ============================================================================

SELECT 
    f_table_name as table_name,
    f_geometry_column as geometry_column,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'vector' 
            AND table_name = gc.f_table_name 
            AND column_name = 'geom_25833'
        ) THEN '✓ Has geom_25833'
        ELSE '✗ Missing geom_25833'
    END as status
FROM geometry_columns gc
WHERE f_table_schema = 'vector'
AND f_geometry_column = 'geometry'
ORDER BY status DESC, table_name;
