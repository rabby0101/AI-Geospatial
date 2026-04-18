# Config

## Environment Variables

- `ALLOWED_ORIGINS` (has default) — .env.example
- `API_DEBUG` (has default) — .env.example
- `API_HOST` (has default) — .env.example
- `API_PORT` (has default) — .env.example
- `CACHE_TTL_SECONDS` **required** — app/utils/query_cache.py
- `CACHE_TYPE` **required** — app/utils/query_cache.py
- `DATA_DIR` (has default) — .env.example
- `DATABASE_URL` **required** — scripts/import_alkis_buildings.py
- `DB_HOST` **required** — scripts/import_alkis_buildings.py
- `DB_NAME` **required** — scripts/import_alkis_buildings.py
- `DB_PASSWORD` **required** — scripts/import_alkis_buildings.py
- `DB_PORT` **required** — scripts/import_alkis_buildings.py
- `DB_USER` **required** — scripts/import_alkis_buildings.py
- `DEEPSEEK_API_KEY` (has default) — .env.example
- `DEEPSEEK_MODEL` (has default) — .env.example
- `DEFAULT_LLM_PROVIDER` **required** — app/utils/llm_manager.py
- `ENABLE_LLM_FALLBACK` **required** — app/utils/llm_manager.py
- `GEMINI_API_KEY` (has default) — .env.example
- `GEMINI_MODEL` (has default) — .env.example
- `MAX_CACHE_SIZE_MB` **required** — app/utils/query_cache.py
- `MAX_LOG_FILES` **required** — app/utils/query_logger.py
- `METADATA_DIR` (has default) — .env.example
- `NOMINATIM_HOST` (has default) — .env.example
- `NOMINATIM_PORT` (has default) — .env.example
- `OLLAMA_API_URL` (has default) — .env.example
- `OLLAMA_MODEL` (has default) — .env.example
- `OLLAMA_MODEL_SMALL` (has default) — .env.example
- `OLLAMA_TIMEOUT` (has default) — .env.example
- `OPENTOPO_API_KEY` **required** — app/utils/data_loaders/dem_loader.py
- `POSTGRES_DB` (has default) — .env.example
- `POSTGRES_HOST` (has default) — .env.example
- `POSTGRES_PASSWORD` (has default) — .env.example
- `POSTGRES_PORT` (has default) — .env.example
- `POSTGRES_USER` (has default) — .env.example
- `QUERY_LOG_DIR` **required** — app/utils/query_logger.py
- `RASTER_DIR` (has default) — .env.example
- `REDIS_URL` **required** — app/utils/query_cache.py
- `SCHEMA_REFRESH_TOKEN` **required** — app/routes/database.py
- `VALHALLA_HOST` **required** — app/utils/valhalla_routing.py
- `VALHALLA_PORT` **required** — app/utils/valhalla_routing.py
- `VECTOR_DIR` (has default) — .env.example

## Config Files

- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
