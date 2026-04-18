# Project Context

This is a python project using fastapi with sqlalchemy.

The API has 87 routes. See .codesight/routes.md for the full route map with methods, paths, and tags.
The database has 3 models. See .codesight/schema.md for the full schema with fields, types, and relations.
Middleware includes: custom.

High-impact files (most imported, changes here affect many other files):
- /query_model.py (imported by 1 files)
- /query.py (imported by 1 files)
- /deepseek.py (imported by 1 files)
- /spatial_engine.py (imported by 1 files)
- /osm_loader.py (imported by 1 files)
- /sentinel_loader.py (imported by 1 files)
- /dem_loader.py (imported by 1 files)
- /gadm_loader.py (imported by 1 files)

Required environment variables (no defaults):
- CACHE_TTL_SECONDS (app/utils/query_cache.py)
- CACHE_TYPE (app/utils/query_cache.py)
- DATABASE_URL (scripts/import_alkis_buildings.py)
- DB_HOST (scripts/import_alkis_buildings.py)
- DB_NAME (scripts/import_alkis_buildings.py)
- DB_PASSWORD (scripts/import_alkis_buildings.py)
- DB_PORT (scripts/import_alkis_buildings.py)
- DB_USER (scripts/import_alkis_buildings.py)
- DEFAULT_LLM_PROVIDER (app/utils/llm_manager.py)
- ENABLE_LLM_FALLBACK (app/utils/llm_manager.py)
- MAX_CACHE_SIZE_MB (app/utils/query_cache.py)
- MAX_LOG_FILES (app/utils/query_logger.py)
- OPENTOPO_API_KEY (app/utils/data_loaders/dem_loader.py)
- QUERY_LOG_DIR (app/utils/query_logger.py)
- REDIS_URL (app/utils/query_cache.py)

Read .codesight/wiki/index.md for orientation (WHERE things live). Then read actual source files before implementing. Wiki articles are navigation aids, not implementation guides.
Read .codesight/CODESIGHT.md for the complete AI context map including all routes, schema, components, libraries, config, middleware, and dependency graph.
