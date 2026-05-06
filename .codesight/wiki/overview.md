# AI-Geospatial — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**AI-Geospatial** is a python project built with fastapi, using sqlalchemy for data persistence.

## Scale

87 API routes · 3 database models · 1 middleware layers · 41 environment variables

## Subsystems

- **[Auth](./auth.md)** — 1 routes — touches: auth, db, cache, upload
- **[Agent](./agent.md)** — 1 routes — touches: cache
- **[Dashboard](./dashboard.md)** — 1 routes — touches: auth
- **[Database](./database.md)** — 22 routes — touches: auth, db, cache, upload
- **[Database-inspector](./database-inspector.md)** — 1 routes — touches: auth
- **[Dem_query](./dem_query.md)** — 8 routes
- **[Frontend](./frontend.md)** — 1 routes — touches: auth
- **[Gdi_berlin](./gdi_berlin.md)** — 2 routes
- **[Geocoding](./geocoding.md)** — 4 routes — touches: db
- **[Query](./query.md)** — 9 routes — touches: auth, db, cache
- **[Raster](./raster.md)** — 8 routes
- **[Routing](./routing.md)** — 3 routes — touches: auth

- **[Satellite](./satellite.md)** — 2 routes — touches: auth, db, upload
- **[Semantic](./semantic.md)** — 7 routes
- **[Skills](./skills.md)** — 1 routes
- **[Walking_distance](./walking_distance.md)** — 3 routes — touches: db
- **[Infra](./infra.md)** — 2 routes — touches: auth, db

**Database:** unknown, 3 models — see [database.md](./database.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `/query_model.py` — imported by **1** files
- `/query.py` — imported by **1** files
- `/deepseek.py` — imported by **1** files
- `/spatial_engine.py` — imported by **1** files
- `/osm_loader.py` — imported by **1** files
- `/sentinel_loader.py` — imported by **1** files

## Required Environment Variables

- `CACHE_TTL_SECONDS` — `app/utils/query_cache.py`
- `CACHE_TYPE` — `app/utils/query_cache.py`
- `DATABASE_URL` — `scripts/import_alkis_buildings.py`
- `DB_HOST` — `scripts/import_alkis_buildings.py`
- `DB_NAME` — `scripts/import_alkis_buildings.py`
- `DB_PASSWORD` — `scripts/import_alkis_buildings.py`
- `DB_PORT` — `scripts/import_alkis_buildings.py`
- `DB_USER` — `scripts/import_alkis_buildings.py`
- `DEFAULT_LLM_PROVIDER` — `app/utils/llm_manager.py`
- `ENABLE_LLM_FALLBACK` — `app/utils/llm_manager.py`
- `MAX_CACHE_SIZE_MB` — `app/utils/query_cache.py`
- `MAX_LOG_FILES` — `app/utils/query_logger.py`
- _...6 more_

---
_Back to [index.md](./index.md) · Generated 2026-04-08_