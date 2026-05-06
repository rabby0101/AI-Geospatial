# Spatial Generator — Design Spec
**Date:** 2026-04-18  
**Status:** Approved

## Context

The app currently only queries and filters existing PostGIS data. The goal is to make it generative — capable of creating new geospatial features, surfaces, and scenarios from existing data. This serves two primary user groups: urban planners / government officials who need evidence for infrastructure decisions, and NGOs / community advocates who need to expose spatial inequalities.

## Architecture

A new `spatial_generator.py` module handles all Shapely/GeoPandas computation. It is a pure computation layer — no DB access, no side effects. It receives GeoJSON dicts as input and returns GeoJSON dicts as output.

`agent_tools.py` remains the DB-facing layer: it fetches input data from PostGIS, calls functions in `spatial_generator.py`, and saves results back to the `temp_layers` schema using `GeoDataFrame.to_postgis()`. This keeps the computation testable without a live DB connection.

Generated layers are saved to `temp_layers` with semantic names (e.g., `layer_voronoi_hospitals_{hash}`) so the agent can reference them in follow-up queries within the same session.

```
User query
  → Agent Orchestrator (ReAct loop)
    → agent_tools.py: fetch from PostGIS → spatial_generator.py → save to temp_layers
      → GeoJSON returned to frontend map
        → Agent can reference saved layer in next query
```

## Files

| File | Change |
|------|--------|
| `app/utils/spatial_generator.py` | **CREATE** — pure Shapely/GeoPandas functions (~400 lines) |
| `app/utils/agent_tools.py` | **MODIFY** — add 12 new tool functions + register in TOOL_REGISTRY |
| `app/utils/agent_orchestrator.py` | **MODIFY** — add new tools to system prompt |

## New Tools (12)

### A — New Geometries from Existing Data
| Tool | Description | Example query |
|------|-------------|---------------|
| `generate_voronoi(table, id_col)` | Voronoi polygons around input points — one polygon per point representing the nearest-zone | "Generate hospital coverage zones for Berlin" |
| `generate_hexgrid(bbox, cell_size_m)` | Hexagonal grid covering a bounding box — base layer for density and scoring | "Create a 500m hex grid over Mitte" |
| `generate_convex_hull(table)` | Minimum bounding polygon around a set of features | "What area do all schools cover?" |
| `generate_corridor(route_geom, width_m)` | Buffered corridor along a road or route | "Generate a 200m corridor along Unter den Linden" |

### B — Suitability & Site Selection
| Tool | Description | Example query |
|------|-------------|---------------|
| `site_suitability(criteria)` | Multi-criteria scoring on a hex grid. Each criterion: `{table, weight, direction: near/far}` | "Find best 5 locations for a new clinic, near transport, far from existing clinics" |
| `coverage_gaps(service_table, radius_m)` | Returns polygons of areas NOT within radius of any service feature | "Show areas more than 1km from any pharmacy" |

### C — Derived Analytical Surfaces
| Tool | Description | Example query |
|------|-------------|---------------|
| `kernel_density(table, bandwidth_m, grid_size_m)` | Point density surface as a scored hex/point grid | "Show density of restaurants across Berlin" |
| `equity_gap_analysis(service_table, district_table)` | Compares service counts per district, flags statistically underserved ones | "Which districts have the worst school-to-population ratio?" |
| `accessibility_surface(target_table, mode, max_minutes)` | Grid of travel times to nearest target feature using Valhalla isochrones | "Show walking time to nearest hospital across Berlin" |

### D — Scenario Planning & What-If
| Tool | Description | Example query |
|------|-------------|---------------|
| `add_hypothetical(layer_name, geometry, properties)` | Adds a hypothetical point/polygon to a named scenario layer in PostGIS | "Add a hypothetical hospital at Tempelhof" |
| `compare_scenarios(baseline_layer, scenario_layer)` | Runs coverage analysis on both layers and returns a diff — what improved, what didn't | "How does adding that hospital change coverage gaps?" |

### Persistence
| Tool | Description |
|------|-------------|
| `save_generated_layer(geojson, layer_name, description)` | Saves any FeatureCollection to `temp_layers` schema with a semantic name for follow-up reference |

## Data Flow Example

Query: *"Generate Voronoi zones for all hospitals"*

1. Agent picks `generate_voronoi(table="public.osm_hospitals", id_col="osm_id")`
2. `agent_tools.py` runs: `SELECT osm_id, ST_AsGeoJSON(geom) FROM public.osm_hospitals`
3. Passes GeoJSON to `spatial_generator.voronoi_from_points(points_geojson, clip_boundary=berlin_bbox)`
4. Shapely computes Voronoi polygons, returns FeatureCollection
5. Tool saves to `temp_layers.layer_voronoi_hospitals_{hash}` via `GeoDataFrame.to_postgis()`
6. Agent returns GeoJSON + layer name → frontend renders polygons
7. Follow-up: *"Show coverage gaps in those zones"* → agent queries the saved layer directly

## New Dependencies

| Package | Purpose | Status |
|---------|---------|--------|
| `geopandas` | GeoDataFrame + `to_postgis()` | **New** |
| `scipy` | Voronoi diagram + KDE computation | **New** |
| `shapely` | Geometry operations | Already installed |
| `sqlalchemy` | DB connection | Already installed |

## Verification

1. Ask: *"Generate Voronoi zones for all hospitals"* → new table appears in `temp_layers`, polygons render on map
2. Ask: *"Show coverage gaps in those zones"* → agent references saved layer, no re-computation
3. Ask: *"Find the best location for a new clinic near transport stops"* → `site_suitability` returns scored candidates on map
4. Ask: *"Add a hypothetical hospital at Tempelhof and show how coverage changes"* → `add_hypothetical` + `compare_scenarios` produce a before/after diff layer
