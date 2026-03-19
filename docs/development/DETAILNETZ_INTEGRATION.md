# Detailnetz (Berlin Detailed Road Network) Integration

> [!CAUTION]
> **DEPRECATED / REPLACED**: As of 2026-02-03, the `vector.detailnetz_road_segments` table has been replaced by `vector.custom_roads` for all routing and analysis queries. This document remains for historical context on the original Detailnetz import.


## Overview

This document describes the integration of Berlin's comprehensive street and road network from the GDI Berlin WFS service. The Detailnetz represents a detailed digital node-edge model of Berlin's traffic-related road infrastructure.

**Source**: https://gdi.berlin.de/services/wfs/detailnetz

**Integration Date**: 2025-10-29

## Datasets Integrated

### 1. Road Segments (Straßenabschnitte)

**Table**: `vector.detailnetz_road_segments`

| Property | Value |
|----------|-------|
| Features | 43,420 road segments |
| Geometry | LineString |
| CRS | EPSG:4326 (WGS84) |
| Size | 30.6 MB |
| Data File | `data/vector/detailnetz/berlin_detailnetz_road_segments.geojson` |

**Key Fields**:
- `strassenschluessel`: Street key identifier
- `strassenname`: Street name
- `element_nr`: Element/segment number
- `dnez__sdatenid`: Data set ID
- Traffic-related attributes

**Coverage**:
- Longitude: 13.0902° to 13.7569°E
- Latitude: 52.3404° to 52.6599°N

**Sample Queries**:
```
"Show all roads in Berlin"
"Which main streets pass near hospitals?"
"Display the street network"
"Find roads connecting to Mitte"
```

---

### 2. Connection Points/Nodes (Verbindungspunkte)

**Table**: `vector.detailnetz_connection_points`

| Property | Value |
|----------|-------|
| Features | 31,079 network nodes |
| Geometry | Point |
| CRS | EPSG:4326 (WGS84) |
| Size | 7.3 MB |
| Data File | `data/vector/detailnetz/berlin_detailnetz_connection_points.geojson` |

**Key Fields**:
- Network node information
- Traffic level indicators
- Location metadata
- Data source/collection information

**Coverage**:
- Longitude: 13.0902° to 13.7569°E
- Latitude: 52.3420° to 52.6599°N

**Sample Queries**:
```
"Show network intersection points"
"Which nodes have high traffic?"
"Find junction points near schools"
```

---

### 3. Engineering Structures (Bauwerke)

**Table**: `vector.detailnetz_structures`

| Property | Value |
|----------|-------|
| Features | 1,005 structures |
| Geometry | MultiLineString |
| CRS | EPSG:4326 (WGS84) |
| Size | 0.4 MB |
| Data File | `data/vector/detailnetz/berlin_detailnetz_structures.geojson` |

**Key Fields**:
- Bridge and tunnel information
- Structure type and attributes
- Connection to road segments

**Coverage**:
- Longitude: 13.0886° to 13.7221°E
- Latitude: 52.3747° to 52.6438°N

**Sample Queries**:
```
"Show all bridges in Berlin"
"Find tunnels near transport"
"Which engineering structures are in Wedding?"
```

---

## Implementation

### Download Script

**File**: `scripts/download_detailnetz.py` (7.2 KB)

**Features**:
- Queries WFS capabilities for available layers
- Downloads all three feature types
- Handles WFS version differences (2.0.0, 1.1.0, 1.0.0)
- Converts to GeoJSON and WGS84
- Saves to `data/vector/detailnetz/`

**Key Features**:
- No BBOX filtering (service returns better results without spatial filtering)
- Supports multiple WFS versions
- Automatic error handling and fallbacks
- Progress reporting

**Usage**:
```bash
python scripts/download_detailnetz.py
```

### PostGIS Loader

**File**: `scripts/load_detailnetz.py` (7.9 KB)

**Features**:
- Creates spatial tables with GiST indexes
- Targets: `vector.detailnetz_*`
- SQLAlchemy 2.0 compatible
- Validates data integrity
- Reports geographic bounds

**Tables Created**:
1. `vector.detailnetz_road_segments` (43,420 features)
2. `vector.detailnetz_connection_points` (31,079 features)
3. `vector.detailnetz_structures` (1,005 features)

**Usage**:
```bash
python scripts/load_detailnetz.py
```

---

## Complete Workflow

### 1. Download

```bash
python scripts/download_detailnetz.py
```

**Output**:
- `data/vector/detailnetz/berlin_detailnetz_road_segments.geojson` (30.6 MB)
- `data/vector/detailnetz/berlin_detailnetz_connection_points.geojson` (7.3 MB)
- `data/vector/detailnetz/berlin_detailnetz_structures.geojson` (0.4 MB)

### 2. Load

```bash
python scripts/load_detailnetz.py
```

**Creates**:
- `vector.detailnetz_road_segments` with `idx_detailnetz_road_segments_geom`
- `vector.detailnetz_connection_points` with `idx_detailnetz_connection_points_geom`
- `vector.detailnetz_structures` with `idx_detailnetz_structures_geom`

### 3. Verify

```bash
# Check tables exist
psql -h localhost -p 5433 -U geoassist -d geoassist -c "\dt vector.detailnetz*"

# Count records
psql -h localhost -p 5433 -U geoassist -d geoassist -c "
  SELECT 'road_segments' as table_name, COUNT(*) FROM vector.detailnetz_road_segments
  UNION ALL
  SELECT 'connection_points', COUNT(*) FROM vector.detailnetz_connection_points
  UNION ALL
  SELECT 'structures', COUNT(*) FROM vector.detailnetz_structures;"
```

### 4. Restart Application

The application's auto-discovery system will automatically detect and make available the new tables.

```bash
python app/main.py
```

---

## Database Statistics

### Total Data

| Table | Records | Geometry | Size | Index |
|-------|---------|----------|------|-------|
| `detailnetz_road_segments` | 43,420 | LineString | 30.6 MB | ✅ GiST |
| `detailnetz_connection_points` | 31,079 | Point | 7.3 MB | ✅ GiST |
| `detailnetz_structures` | 1,005 | MultiLineString | 0.4 MB | ✅ GiST |
| **TOTAL** | **75,504** | **✓** | **38.3 MB** | **✓** |

### Geographic Coverage

All three layers cover the complete Berlin metropolitan area:
- **Longitude Range**: 13.0886° to 13.7569°E
- **Latitude Range**: 52.3404° to 52.6599°N

---

## Query Examples

### Road Network Queries

```sql
-- Find longest roads
SELECT strassenname, ST_Length(geometry::geography) as length_meters
FROM vector.detailnetz_road_segments
ORDER BY length_meters DESC
LIMIT 10;

-- Roads near a location
SELECT strassenname, ST_Distance(geometry::geography,
  ST_GeogFromText('POINT(13.405 52.52)')) as distance_meters
FROM vector.detailnetz_road_segments
ORDER BY distance_meters
LIMIT 5;

-- Road density by area
SELECT COUNT(*) as road_count,
  ST_Transform(ST_Buffer(geometry::geography, 1000)::geometry, 4326) as buffer
FROM vector.detailnetz_road_segments
GROUP BY buffer;
```

### Network Connectivity Queries

```sql
-- Find junction points
SELECT COUNT(*) as connected_roads
FROM vector.detailnetz_road_segments roads
WHERE ST_Contains(ST_Buffer(cp.geometry, 50), roads.geometry)
GROUP BY cp.id;

-- Connection points near POIs
SELECT cp.id, COUNT(h.id) as nearby_hospitals
FROM vector.detailnetz_connection_points cp
LEFT JOIN vector.osm_hospitals h
  ON ST_DWithin(cp.geometry, h.geometry, 1000)
GROUP BY cp.id
HAVING COUNT(h.id) > 0;
```

### Bridge and Tunnel Queries

```sql
-- All structures
SELECT COUNT(*) FROM vector.detailnetz_structures;

-- Structures by type
SELECT geometry, COUNT(*)
FROM vector.detailnetz_structures
GROUP BY geometry;

-- Nearby structures
SELECT *
FROM vector.detailnetz_structures
WHERE ST_DWithin(geometry, ST_GeomFromText('POINT(13.405 52.52)', 4326), 5000);
```

### Natural Language Queries (Frontend)

```
"Show main streets in Berlin"
"Find bridges near Spandau"
"Which roads connect to Mitte?"
"Display the entire street network"
"Show all tunnels"
"Find road intersections near parks"
"Which streets are near the hospital?"
"Display bridges and tunnels"
```

---

## Performance Characteristics

### Query Performance

| Query Type | Complexity | Est. Time |
|------------|-----------|-----------|
| Simple geometry | Low | < 50ms |
| Proximity (5km) | Medium | 100-200ms |
| Spatial join | High | 200-500ms |
| Network analysis | Complex | 500ms-5s |

### Index Performance

All three tables have spatial GiST indexes:
- `idx_detailnetz_road_segments_geom`
- `idx_detailnetz_connection_points_geom`
- `idx_detailnetz_structures_geom`

### Memory Usage

- Total dataset size: 38.3 MB
- In-memory PostGIS operations: ~200 MB
- Typical query memory: 10-50 MB

---

## Use Cases

### 1. Route Planning & Navigation
- Find optimal paths through Berlin
- Identify alternative routes
- Traffic-aware navigation

### 2. Urban Analysis
- Analyze road network density
- Identify bottlenecks
- Study connectivity patterns

### 3. Infrastructure Planning
- Locate bridges and tunnels
- Plan infrastructure improvements
- Assess structural coverage

### 4. Proximity Analysis
- Find roads near specific locations
- Identify intersections near amenities
- Analyze accessibility

### 5. Traffic Analysis
- Study network node traffic levels
- Analyze road classifications
- Model traffic flow

---

## Technical Details

### WFS Service Specifics

**Service URL**: https://gdi.berlin.de/services/wfs/detailnetz

**Available WFS Versions**: 2.0.0, 1.1.0, 1.0.0

**Implementation Notes**:
- WFS 2.0.0 requires `typeNames` parameter (not `TYPENAME`)
- No BBOX filtering needed (service works better without it)
- WFS 1.1.0 provides reliable downloads
- GeoJSON output format recommended

### Database Configuration

**Schema**: `vector`

**CRS**: EPSG:4326 (WGS84)

**Connection**:
- Host: localhost
- Port: 5433
- Database: geoassist
- User: geoassist

### SQLAlchemy Configuration

Scripts use SQLAlchemy 2.0+ features:
- `text()` wrapper for raw SQL
- `engine.begin()` for transactions
- Proper error handling
- Efficient batch inserts (chunksize=1000)

---

## Troubleshooting

### Download Returns Empty Results

**Problem**: `detailnetz:c_strassenabschnitte` returns 0 features

**Solution**:
- Don't use BBOX filter (service works better without it)
- Use WFS 1.1.0 for reliability
- Check service is online: https://gdi.berlin.de/

### Large Download Time

**Problem**: Download takes > 10 minutes

**Solution**:
- Normal for 43,420 road segments (30 MB)
- Network speed dependent
- Can cache results locally

### PostGIS Load Fails

**Problem**: "No valid geometries in the data"

**Solution**:
- Check GeoJSON file is valid
- Verify CRS is set correctly
- Ensure geometry column exists

### Spatial Index Creation Error

**Problem**: "Index already exists"

**Solution**:
- This is normal if re-loading
- Index will be skipped
- No action needed

---

## Future Enhancements

### Phase 2: Network Analysis
- Implement routing algorithms
- Calculate shortest paths
- Analyze network connectivity metrics

### Phase 3: Traffic Integration
- Integrate real-time traffic data
- Add dynamic weight calculations
- Implement congestion analysis

### Phase 4: Visualization
- Add interactive route visualization
- Create network density heatmaps
- Implement 3D network visualization

### Phase 5: Advanced Analytics
- Road usage patterns
- Accident hotspot analysis
- Infrastructure deterioration tracking

---

## Related Resources

### Documentation
- `WFS_INTEGRATION_GUIDE.md` - Wasserschutzgebiete integration
- `WFS_LANDUSE_INTEGRATION.md` - Landuse & Building Plans
- `DETAILNETZ_INTEGRATION.md` - This document

### Scripts
- `scripts/download_detailnetz.py` - WFS download
- `scripts/load_detailnetz.py` - PostGIS loader

### Data Files
- `data/vector/detailnetz/berlin_detailnetz_road_segments.geojson`
- `data/vector/detailnetz/berlin_detailnetz_connection_points.geojson`
- `data/vector/detailnetz/berlin_detailnetz_structures.geojson`

### Configuration
- `data/metadata/table_descriptions.json` - Updated with 3 new tables

---

## Summary

**Total Features Integrated**: 75,504
- Road Segments: 43,420
- Connection Points: 31,079
- Structures: 1,005

**Total Data Size**: 38.3 MB

**Status**: ✅ Complete - Ready for queries

**Next**: Restart application for auto-discovery

---

**Last Updated**: 2025-10-29
**Status**: Production Ready
**Integration**: Complete
