-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Create schema for geospatial data
CREATE SCHEMA IF NOT EXISTS geo;

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA geo TO geoassist;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO geoassist;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO geoassist;

-- Create sample tables for vector data
CREATE TABLE IF NOT EXISTS geo.hospitals (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    city VARCHAR(100),
    geom GEOMETRY(Point, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geo.flood_zones (
    id SERIAL PRIMARY KEY,
    zone_name VARCHAR(255),
    risk_level VARCHAR(50),
    city VARCHAR(100),
    geom GEOMETRY(Polygon, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geo.urban_areas (
    id SERIAL PRIMARY KEY,
    area_name VARCHAR(255),
    city VARCHAR(100),
    population INTEGER,
    geom GEOMETRY(Polygon, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create spatial indexes
CREATE INDEX IF NOT EXISTS idx_hospitals_geom ON geo.hospitals USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_flood_zones_geom ON geo.flood_zones USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_urban_areas_geom ON geo.urban_areas USING GIST(geom);

-- Insert sample data for Berlin (hospitals)
INSERT INTO geo.hospitals (name, city, geom) VALUES
    ('Charité Berlin', 'Berlin', ST_SetSRID(ST_MakePoint(13.3777, 52.5244), 4326)),
    ('Vivantes Klinikum', 'Berlin', ST_SetSRID(ST_MakePoint(13.4050, 52.5200), 4326)),
    ('DRK Kliniken', 'Berlin', ST_SetSRID(ST_MakePoint(13.2846, 52.4668), 4326));

-- Insert sample flood zones for Berlin
INSERT INTO geo.flood_zones (zone_name, risk_level, city, geom) VALUES
    ('Spree River Zone 1', 'High', 'Berlin',
     ST_SetSRID(ST_MakePolygon(ST_GeomFromText('LINESTRING(13.37 52.52, 13.38 52.52, 13.38 52.51, 13.37 52.51, 13.37 52.52)')), 4326)),
    ('Spree River Zone 2', 'Medium', 'Berlin',
     ST_SetSRID(ST_MakePolygon(ST_GeomFromText('LINESTRING(13.40 52.52, 13.41 52.52, 13.41 52.51, 13.40 52.51, 13.40 52.52)')), 4326));

-- Insert sample urban areas
INSERT INTO geo.urban_areas (area_name, city, population, geom) VALUES
    ('Mitte District', 'Berlin', 100000,
     ST_SetSRID(ST_MakePolygon(ST_GeomFromText('LINESTRING(13.37 52.53, 13.42 52.53, 13.42 52.50, 13.37 52.50, 13.37 52.53)')), 4326));
