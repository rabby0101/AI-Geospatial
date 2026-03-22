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

The Cognitive Geospatial Assistant API lets you query and analyze geospatial datasets using natural language. It integrates **DeepSeek and Google Gemini LLMs** alongside a **Semantic Knowledge Graph** to translate plain-English questions into spatial operations, returning GeoJSON results on an interactive map.

## Features

- **Natural Language Queries** — Ask geospatial questions in plain English
- **LLM-Powered Reasoning** — DeepSeek and Gemini translate queries to spatial operations
- **Semantic Knowledge Graph** — RDF/OWL ontology matches query intent to the right tables
- **Valhalla Routing** — Accurate pedestrian/cycling/auto routing and walking distance calculations
- **Intelligent Site Selection** — Find optimal business locations with distance decay scoring
- **Interactive Map Viewer** — Leaflet-based frontend for result visualization
- **RESTful API + Docker** — FastAPI with Swagger docs; full stack deployable via docker-compose

## Tech Stack

| Component | Technology |
|-----------|------------|
| API | FastAPI |
| LLMs | DeepSeek, Google Gemini 2.5 Flash |
| Knowledge Graph | RDFLib, SHACL, SPARQL |
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
```

## API Usage

```bash
curl -X POST "http://localhost:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals within 2 km of flood zones in Berlin"}'
```

## Data Coverage

**24 OSM vector datasets** covering Berlin (~45,000+ features): hospitals, pharmacies, schools, universities, restaurants, parks, transport stops, supermarkets, parking, districts, and more.

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

### Development Tools
| Tool | Purpose |
|------|---------|
| [Claude Code](https://claude.ai/claude-code) by Anthropic | Partial code generation and development assistance used during implementation |
