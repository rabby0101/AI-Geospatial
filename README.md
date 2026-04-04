# Cognitive Geospatial Assistant API

An LLM-Integrated RESTful API for Interactive Geospatial Reasoning and Querying

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)
![PostGIS](https://img.shields.io/badge/PostGIS-3.3-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Demo

[![Watch the demo](https://img.youtube.com/vi/NA19nn7qcLs/hqdefault.jpg)](https://www.youtube.com/watch?v=NA19nn7qcLs)

> Ask in plain English. Get walking routes, distances, restaurants, hospitals & more — instantly.
> No dropdowns. No filters. Just answers. Export results as GeoJSON for deeper GIS analysis.

## Overview

The Cognitive Geospatial Assistant API lets you query and analyze geospatial datasets using natural language. It integrates **DeepSeek, Google Gemini, and Ollama LLMs** alongside a **6-phase AI pipeline** and a **Semantic Knowledge Graph** to translate plain-English questions into spatial operations, returning GeoJSON results on an interactive map.

## Features

- **Natural Language Queries** — Ask geospatial questions in plain English
- **LLM-Powered Reasoning** — DeepSeek, Gemini, and Ollama translate queries to spatial operations
- **6-Phase AI Pipeline** — Structured query processing from intent detection to result evaluation
- **Business Intelligence Layer** — Auto-loads structured site-selection profiles (legal zones, building type filters, competitor exclusion, scoring weights) for any business type before SQL generation
- **Knowledge Graph (BauNVO)** — 46 triples encoding German planning law stored in `metadata.knowledge_graph`; legal zone rules are injected into every site-selection prompt automatically
- **Schema Auto-Discovery** — New PostGIS tables are catalogued by AI with zero code changes; the system picks them up immediately
- **Semantic Knowledge Graph** — RDF/OWL ontology matches query intent to the right tables
- **Valhalla Routing** — Accurate pedestrian/cycling/auto routing and walking distance calculations
- **Intelligent Site Selection** — Find optimal business locations with legal-zone filtering, competitor exclusion, and distance-decay MCDA scoring
- **Local LLM Support** — Ollama backend (qwen3.5:9b) as a fully offline alternative to cloud APIs
- **Interactive Map Viewer** — Leaflet-based frontend for result visualization
- **RESTful API + Docker** — FastAPI with Swagger docs; full stack deployable via docker-compose

## System Architecture

The system has two tiers: **specialized direct endpoints** for specific operations (routing, NDVI, DEM, semantic) that bypass the AI pipeline, and the **main AI pipeline** (`/api/query`) that handles all natural-language queries through a multi-phase reasoning process.

```mermaid
flowchart TD
    USER(["User / Frontend\nLeaflet Map"]) -->|natural language| MAIN["POST /api/query"]
    USER -->|"direct call"| SPEC

    subgraph SPEC["Specialized Endpoints (no AI pipeline)"]
        direction LR
        EP1["POST /api/routing/connect-features\nValhalla multi-point routing"]
        EP2["POST /api/walking-distance/find-buildings\nValhalla isochrones"]
        EP3["POST /api/raster/ndvi/change-detection\nSentinel-2 NDVI diff"]
        EP4["POST /api/dem/slope|aspect\nDEM terrain analysis"]
        EP5["POST /api/semantic/sparql\nRDF/OWL SPARQL query"]
    end

    MAIN --> PRE

    subgraph PRE["Pre-processing"]
        direction TB
        PRE1["Create temp PostGIS layer\nif drawn_geometry or selected_feature present\n→ temp.temp_selected_{session_id}"]
    end

    PRE --> RT_CHECK{"Routing keywords\ndetected AND\n2+ map features\nselected?"}

    RT_CHECK -->|"Yes — skip AI"| VALHALLA_RT["Valhalla Routing\noptimal_tour TSP\n→ Route GeoJSON + maneuvers"]
    RT_CHECK -->|"No"| P0

    subgraph P0["Phase 0 — Business Intelligence (optional, no LLM call)"]
        direction TB
        P0A{"Business type\nkeyword detected?"}
        P0A -->|"Yes"| P0B["Lookup vector.business_profiles\n(legal zones · bezgfk filters · competitor table · weights)"]
        P0B --> P0C["Query metadata.knowledge_graph\n(BauNVO: permitted / prohibited / conditional zones)"]
        P0C --> P0D["Format profile → injected into system prompt"]
        P0A -->|"No"| P0E["Skip — no profile injected"]
    end

    P0 --> P12

    subgraph P12["Phase 1+2 — Table Selection + Schema Discovery"]
        direction TB
        P12A["LLM selects relevant tables\nfrom metadata.table_descriptions\n(auto-discovered catalog)"] --> P12B["Fetch full schema\nfor selected tables only\n(column names · types · real sample values)"]
    end

    P12 --> P3_CHECK{"2+ tables OR\ncomplex data?"}
    P3_CHECK -->|"Yes"| P3

    subgraph P3["Phase 3 — Query Planning"]
        direction TB
        P3A["LLM validates filter values\nagainst real DB column values\n(prevents hallucination)"] --> P3B["Returns confirmed_tables\n+ filter_plan JSON"]
    end

    P3_CHECK -->|"No — simple query"| P4
    P3 --> P4

    subgraph P4["Phase 4 — SQL / Operation Generation"]
        direction TB
        P4A["LLM Provider\nDeepSeek · Gemini · Ollama"] --> P4B["System prompt =\nbase instructions\n+ schema (Phase 1+2)\n+ ontology context\n+ query plan (Phase 3)\n+ business profile (Phase 0)"]
        P4B --> P4C["Returns OperationPlan JSON\n(list of typed operations)"]
    end

    P4 --> SE

    subgraph SE["Spatial Engine — execute_plan()"]
        direction TB
        SE_CHECK{"Operation type?"}

        SE_CHECK -->|"routing"| SE_RT["Valhalla\npairwise or optimal_tour\n→ Route GeoJSON"]
        SE_CHECK -->|"nearest_by_road"| SE_NR["Valhalla road-distance\nfind nearest POI\n→ Feature + distance_m"]
        SE_CHECK -->|"walking_time"| SE_WT["Valhalla isochrone\nintersect with target table\n→ Reachable buildings/POIs"]
        SE_CHECK -->|"spatial_query"| SE_SQL["PostGIS SQL execution\nST_DWithin · ST_Intersects\nST_Buffer · CTE scoring"]
        SE_CHECK -->|"load"| SE_LOAD["SELECT * FROM table\nor custom SQL"]
        SE_CHECK -->|"buffer / intersection\nunion / difference\nfilter / aggregate / sort"| SE_CHAIN["Chained spatial ops\non previous result\n(multi-step queries)"]
        SE_CHECK -->|"raster_analysis"| SE_RAST["Raster engine\nNDVI · DEM · land cover\nzonal stats · change detection"]
    end

    SE_SQL --> MCDA{"Multi-criteria\nscoring needed?"}
    SE_LOAD --> MCDA
    SE_CHAIN --> MCDA

    MCDA -->|"Yes\n(2+ criteria, <100 rows)"| MCDA_CALC["MCDA Scoring\nExtract criteria from query\nCalculate dynamic weights\nCompute composite_score per feature"]
    MCDA -->|"No"| FMT
    MCDA_CALC --> FMT

    SE_RT --> FMT
    SE_NR --> FMT
    SE_WT --> FMT
    SE_RAST --> FMT

    subgraph FMT["Result Formatting"]
        direction TB
        FMT1["Reproject to WGS84\nFilter invalid geometries\nSerialize to GeoJSON FeatureCollection"]
    end

    FMT --> P5

    subgraph P5["Phase 5 — Result Evaluation (site-selection queries only, no LLM call)"]
        direction TB
        P5A["Rule-based quality check"] --> P5B{"Issues found?"}
        P5B -->|"geographic clustering\nbezgfk mismatch\nempty results"| P5C["Surface warnings + issues\nwith suggested fixes"]
        P5B -->|"Pass"| P5D["Return results as-is"]
    end

    P5 --> RESP["QueryResponse\n{success · geojson · layer_name\nreasoning · metadata · datasets_used}"]
    RESP --> USER
    VALHALLA_RT --> RESP
    EP1 & EP2 & EP3 & EP4 & EP5 --> RESP
```

**Phase summary:**

| Phase | Name | Trigger | LLM call? |
|-------|------|---------|-----------|
| Pre | Temp layer creation | `drawn_geometry` or `selected_feature` present | No |
| 0 | Business Intelligence | Business keyword in question | No (DB lookup) |
| 1+2 | Table Selection + Schema | Every AI query | Yes |
| 3 | Query Planning | 2+ tables selected OR complex column values | Yes |
| 4 | SQL/Operation Generation | Every AI query | Yes |
| EX | Execution | Every query | No |
| MCDA | Multi-criteria scoring | Multi-factor evaluation queries | No |
| 5 | Result Evaluation | Site-selection queries only | No |

## Tech Stack

| Component | Technology |
|-----------|------------|
| API | FastAPI |
| LLMs | DeepSeek, Google Gemini 2.5 Flash |
| Local LLM | Ollama (qwen3.5:9b) |
| Knowledge Graph | RDFLib, SHACL, SPARQL + BauNVO triples |
| Business Intelligence | `vector.business_profiles`, `metadata.knowledge_graph` |
| Schema Auto-Discovery | AI-powered table cataloguing (DeepSeek) |
| Routing | Valhalla |
| Spatial DB | PostGIS, pgRouting |
| Vector Processing | GeoPandas, Shapely |
| Frontend | Leaflet, HTML/JS |

## Quick Start

**Prerequisites:** Python 3.11+, Docker & Docker Compose, DeepSeek API key

```bash
# 1. Clone and set up environment
conda create -n geoassist python=3.11 && conda activate geoassist
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Add DEEPSEEK_API_KEY (and optionally GEMINI_API_KEY) to .env

# 3. Start PostGIS + Valhalla (first run downloads Berlin OSM data, ~3-5 min)
docker-compose up -d postgis valhalla

# 4. Run the API
python -m uvicorn app.main:app --reload

# 5. (Optional) Set up Business Intelligence tables
python scripts/setup_business_intelligence.py
```

- Frontend: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Example Queries

```
"Find hospitals within 2km of flood zones in Berlin"
"Show universities near public transport stops"
"Where should I open a pharmacy near hospitals in Mitte?"
"Find restaurants within walking distance of Alexanderplatz"
"Which district has the highest concentration of schools?"
"Find top 5 locations for a veterinary clinic in Marzahn-Hellersdorf"
"Where should I open a pharmacy in Mitte — legally viable locations only?"
```

## API Usage

```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals within 2 km of flood zones in Berlin"}'
```

## Data Coverage

**24 OSM vector datasets** covering Berlin (~45,000+ features): hospitals, pharmacies, schools, universities, restaurants, parks, transport stops, supermarkets, parking, districts, and more.

**Business Intelligence**: `vector.business_profiles` (8 business types pre-seeded), `metadata.knowledge_graph` (46 BauNVO triples encoding German zoning law).

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for the full dataset list and external data sources.

## Documentation

- [Quick Start Guide](docs/guides/QUICKSTART.md)
- [Setup Guide](docs/guides/SETUP_GUIDE.md)
- [Troubleshooting](docs/guides/TROUBLESHOOTING.md)
- [Implementation Plan](docs/implementation/IMPLEMENTATION_PLAN.md)

## Contributing

Contributions welcome — fork, branch, add tests, submit a PR.

## License

MIT License — see LICENSE file for details.

## Author

**Sk Fazla Rabby**
MSc in Geodesy and Geoinformation Science — AI-driven geospatial data integration and analysis

## Open Source Acknowledgments

This project is built on the shoulders of these excellent open source projects:

### Routing & Geocoding
| Project | Purpose |
|---------|---------|
| [Valhalla](https://github.com/valhalla/valhalla) | Multi-mode routing engine (pedestrian, cycling, auto) with isochrone support |
| [Nominatim](https://github.com/osm-search/Nominatim) | Self-hosted OpenStreetMap geocoding — forward, reverse, and autocomplete |

### Data Sources & Tooling
| Project | Purpose |
|---------|---------|
| [OpenStreetMap](https://www.openstreetmap.org) | Primary geospatial dataset for all Berlin features |
| [Geofabrik](https://download.geofabrik.de) | OSM PBF download mirror used for Berlin data |
| [ODIS WFS Explorer](https://github.com/technologiestiftung/odis-wfsexplorer) by Technologiestiftung Berlin | Reference implementation for fetching official Berlin open data via WFS endpoints |

### Spatial Database
| Project | Purpose |
|---------|---------|
| [PostGIS](https://postgis.net) | PostgreSQL extension for storing and querying vector geometry |
| [pgRouting](https://pgrouting.org) | Graph routing extension (Dijkstra fallback when Valhalla is unavailable) |

### Semantic Web & Knowledge Graph
| Project | Purpose |
|---------|---------|
| [RDFLib](https://rdflib.readthedocs.io) | RDF/OWL ontology management and SPARQL queries |
| [pySHACL](https://github.com/RDFLib/pySHACL) | SHACL shape validation for geospatial ontologies |
| [owlready2](https://owlready2.readthedocs.io) | OWL 2 ontology API for class and property management |

### Geospatial Processing
| Project | Purpose |
|---------|---------|
| [GeoPandas](https://geopandas.org) | Vector geospatial data frames and analysis |
| [Shapely](https://shapely.readthedocs.io) | Geometric operations (buffers, intersections, unions) |

### Frontend & Visualization
| Project | Purpose |
|---------|---------|
| [Leaflet](https://leafletjs.com) | Interactive web mapping and layer management |
| [Turf.js](https://turfjs.org) | Browser-side spatial analysis (distance, bbox, buffer) |

### Backend & LLMs
| Project | Purpose |
|---------|---------|
| [FastAPI](https://fastapi.tiangolo.com) | REST API framework with automatic Swagger docs |
| [DeepSeek](https://deepseek.com) | Primary LLM for natural language → SQL translation |
| [Google Gemini](https://ai.google.dev) | Secondary LLM option (Gemini 2.5 Flash) |
| [Ollama](https://ollama.com) | Local LLM runtime for fully offline operation |

### Development Tools
| Tool | Purpose |
|------|---------|
| [Claude Code](https://claude.ai/claude-code) by Anthropic | Partial code generation and development assistance used during implementation |
