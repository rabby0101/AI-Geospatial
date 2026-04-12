# AI-Geospatial — AI Context Map

> **Stack:** fastapi | sqlalchemy | unknown | python

> 87 routes | 3 models | 0 components | 65 lib files | 41 env vars | 1 middleware | 7% test coverage
> **Token savings:** this file is ~5,400 tokens. Without it, AI exploration would cost ~75,900 tokens. **Saves ~70,500 tokens per conversation.**

---

# Routes

## CRUD Resources

- **`/tables`** GET | POST | GET/:id | DELETE/:id → Table

## Other Routes

- `GET` `/` params() [auth] ✓
- `GET` `/dashboard` params() [auth]
- `GET` `/database-inspector` params() [auth]
- `GET` `/frontend` params() [auth]
- `POST` `/query` params() → in: AgentRequest [cache]
- `POST` `/columns` params() [auth, db, cache, upload]
- `GET` `/schema-for-prompt` params() [auth, db, cache, upload]
- `POST` `/table-description` params() [auth, db, cache, upload]
- `GET` `/tables-with-metadata` params() [auth, db, cache, upload]
- `GET` `/changelog` params() [auth, db, cache, upload]
- `POST` `/upload` params() [auth, db, cache, upload]
- `POST` `/upload/check` params() [auth, db, cache, upload]
- `PUT` `/tables/{table_name}/rename` params(table_name) [auth, db, cache, upload]
- `GET` `/tables/{table_name}/preview` params(table_name) [auth, db, cache, upload]
- `GET` `/tables/{table_name}/stats` params(table_name) [auth, db, cache, upload]
- `POST` `/schema/refresh` params() [auth, db, cache, upload]
- `GET` `/schema/status` params() [auth, db, cache, upload]
- `POST` `/wfs-capabilities` params() [auth, db, cache, upload]
- `POST` `/wfs-import/check` params() [auth, db, cache, upload]
- `POST` `/wfs-import` params() [auth, db, cache, upload]
- `POST` `/overpass/generate-query` params() [auth, db, cache, upload]
- `POST` `/overpass/query` params() [auth, db, cache, upload]
- `POST` `/overpass/import/check` params() [auth, db, cache, upload]
- `POST` `/overpass/import` params() [auth, db, cache, upload]
- `GET` `/terrain-stats` params() ✓
- `GET` `/slope` params() ✓
- `GET` `/development-suitability` params() ✓
- `GET` `/development-by-subdivisions` params()
- `GET` `/flood-risk` params()
- `GET` `/classification` params() ✓
- `GET` `/available-files` params()
- `GET` `/info` params()
- `GET` `/layers` params()
- `GET` `/wfs/{layer_id}` params(layer_id)
- `GET` `/search` params() → in: st, out: GeocodeSearchResponse [db]
- `GET` `/autocomplete` params() → in: st, out: GeocodeSearchResponse [db]
- `GET` `/reverse` params() → in: st, out: GeocodeSearchResponse [db]
- `GET` `/feature` params() → in: st, out: GeocodeSearchResponse [db]
- `GET` `/health` params() → in: st, out: GeocodeSearchResponse [db]
- `POST` `/query-stats` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `GET` `/datasets` params() → out: QueryResponse [auth, db, cache]
- `POST` `/execute-sql` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `GET` `/load-table/{table_name}` params(table_name) → out: QueryResponse [auth, db, cache]
- `GET` `/districts-geojson` params() → out: QueryResponse [auth, db, cache]
- `POST` `/cache/clear` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `POST` `/create-temp-layer` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `POST` `/drop-temp-layer` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `POST` `/street-lights/coverage` params() → in: NLQuery, out: QueryResponse [auth, db, cache]
- `POST` `/ndvi/change-detection` params() → in: NDVIChangeRequest
- `POST` `/ndvi/zonal-stats` params() → in: NDVIChangeRequest
- `GET` `/ndvi/timeseries/{region}` params(region)
- `POST` `/clip` params() → in: NDVIChangeRequest
- `POST` `/vectorize` params() → in: NDVIChangeRequest
- `GET` `/catalog` params()
- `GET` `/info/{dataset_id}` params(dataset_id)
- `POST` `/analyze/urban-vegetation-loss` params() → in: NDVIChangeRequest
- `POST` `/connect-features` params() → in: Dict [auth]
- `POST` `/nearest-vertex` params() → in: Dict [auth]
- `POST` `/optimal-tour` params() → in: Dict [auth]
- `GET` `/mitte/summary` params() [db, cache]
- `GET` `/mitte/geojson` params() [db, cache]
- `GET` `/mitte/lighting` params() [db, cache]
- `GET` `/mitte/activity-nodes` params() [db, cache]
- `GET` `/mitte/emergency-services` params() [db, cache]
- `GET` `/mitte/buildings` params() [db, cache]
- `POST` `/analysis/export` params() [db, cache]
- `GET` `/mitte/crime-summary` params() [db, cache]
- `GET` `/mitte/accidents` params() [db, cache]
- `GET` `/mitte/hotspots` params() [db, cache]
- `GET` `/mitte/risk-heatmap` params() [db, cache]
- `POST` `/analyze` params() → in: List, out: SatelliteUploadResponse [auth, db, upload]
- `DELETE` `/session/{session_id}` params(session_id) → out: SatelliteUploadResponse [auth, db, upload]
- `GET` `/datasets/{dataset_id}` params(dataset_id)
- `GET` `/datasets/by-purpose/{purpose}` params(purpose)
- `GET` `/ontology` params()
- `POST` `/sparql` params() → in: SPARQLQueryRequest
- `POST` `/validate` params() → in: SPARQLQueryRequest
- `GET` `/statistics` params()
- `POST` `/load-catalog` params() → in: SPARQLQueryRequest
- `GET` `/api/skills` params() → out: List
- `POST` `/reachable-roads` params() → in: Dict [db]
- `POST` `/find-buildings` params() → in: Dict [db]
- `POST` `/coverage` params() → in: Dict [db]

---

# Schema

### hospitals
- id: integer(auto) (pk)
- name: varchar
- city: varchar
- geom: geometry(point

### flood_zones
- id: integer(auto) (pk)
- zone_name: varchar
- risk_level: varchar
- city: varchar
- geom: geometry(polygon

### urban_areas
- id: integer(auto) (pk)
- area_name: varchar
- city: varchar
- population: integer
- geom: geometry(polygon

---

# Libraries

- `examples/01_download_osm_data.py` — function main: ()
- `examples/02_download_admin_boundaries.py` — function main: ()
- `examples/03_download_land_cover.py` — function main: ()
- `examples/04_ndvi_change_detection.py` — function main: (), function quick_analysis_example: ()
- `examples/05_dem_analysis_examples.py`
  - function example_1_basic_terrain_analysis: ()
  - function example_2_single_analysis: ()
  - function example_3_hydrological_analysis: ()
  - function example_4_urban_planning: ()
  - function example_5_flood_risk: ()
  - function example_6_custom_parameters: ()
  - _...1 more_
- `examples/test_simple_download.py` — function main: ()
- `scripts/add_geom_25833_column.py` — function add_geom_25833_to_all_tables: ()
- `scripts/analyze_berlin_dem.py` — function analyze_berlin_dem: ()
- `scripts/convert_geojsonseq_to_buildings.py` — function convert_geojsonseq_to_buildings: (), function main: ()
- `scripts/create_berlin_grid.py`
  - function create_4x4_grid: ()
  - function save_grid_config: (grid_cells, output_file)
  - function print_grid_info: (grid_cells)
- `scripts/create_sample_ndvi.py` — function create_sample_ndvi: (output_path, base_ndvi, noise_level, seed), function main: ()
- `scripts/demo_berlin_dem_simple.py` — function demo_berlin_dem: ()
- `scripts/demo_live.py`
  - function print_header: (text)
  - function print_success: (text)
  - function print_info: (text)
  - function test_query: (question, show_details)
  - function main: ()
- `scripts/download_abstell_mikromob.py`
  - function build_wfs_request: (feature_type)
  - function download_wfs_data: (feature_type)
  - function convert_wfs_to_geodataframe: (wfs_data)
  - function save_to_postgis: (gdf, table_name)
  - function main: ()
- `scripts/download_allotment_gardens.py` — function download_allotment_gardens: (), function create_sample_data: ()
- `scripts/download_berlin_dem.py` — function download_berlin_dem: ()
- `scripts/download_berlin_ndvi.py` — function main: ()
- `scripts/download_berlin_osm.py` — function download_berlin_features: ()
- `scripts/download_berlin_osm_expanded.py` — function main: ()
- `scripts/download_bplan_landuse.py`
  - function get_wfs_capabilities: ()
  - function download_wfs_layer: (layer_name, bbox)
  - function main: ()
- `scripts/download_buildings_by_subdivision.py`
  - function get_subdivisions: () -> List[Dict[str, Any]]
  - function build_overpass_query: (bbox_string) -> str
  - function parse_osm_xml: (xml_text) -> List[Dict]
  - function download_subdivision: (subdiv, Any], attempt) -> Dict[str, Any]
  - function convert_osm_to_geojson: (osm_elements) -> List[Dict]
  - function main: ()
- `scripts/download_buildings_overpass_grid.py`
  - function load_grid_config: (config_file) -> List[Dict[str, Any]]
  - function build_overpass_query: (bbox_string) -> str
  - function parse_osm_xml: (xml_text) -> List[Dict]
  - function download_grid_cell: (cell, Any], attempt, max_attempts) -> Dict[str, Any]
  - function convert_osm_to_geojson: (osm_elements) -> List[Dict]
  - function aggregate_grid_downloads: (results, Any]]) -> List[Dict]
  - _...3 more_
- `scripts/download_detailnetz.py`
  - function get_wfs_capabilities: ()
  - function download_wfs_layer: (layer_name, bbox)
  - function main: ()
- `scripts/download_gewerbedaten.py`
  - function build_wfs_request: (feature_type, output_format, max_features)
  - function download_wfs_data: (feature_type, output_format, max_features)
  - function convert_wfs_to_geodataframe: (wfs_data)
  - function save_to_postgis: (gdf, table_name, schema, if_exists)
  - function main: ()
- `scripts/download_landuse.py` — function main: ()
- `scripts/download_landuse_wfs.py`
  - function get_wfs_capabilities: ()
  - function download_wfs_layer: (layer_name)
  - function main: ()
- `scripts/download_missing_osm_datasets.py` — function main: ()
- `scripts/download_osm_buildings.py`
  - function download_using_simple_overpass: ()
  - function convert_osm_to_geojson_simple: (elements)
  - function download_from_geofabrik: ()
  - function download_from_osm2geojson: ()
  - function create_dummy_dataset: ()
  - function save_geojson: (features)
  - _...1 more_
- `scripts/download_parkplaetze.py`
  - function build_wfs_request: (feature_type)
  - function download_wfs_data: (feature_type)
  - function convert_wfs_to_geodataframe: (wfs_data)
  - function save_to_postgis: (gdf, table_name)
  - function main: ()
- `scripts/download_real_sentinel2.py` — function main: (), class RealSentinel2Loader
- `scripts/download_wasserschutzgebiete.py`
  - function get_wfs_capabilities: ()
  - function download_wfs_layer: (layer_name)
  - function main: ()
- `scripts/extract_buildings_from_pbf.py`
  - function check_pbf_file: ()
  - function extract_buildings_with_ogr2ogr: ()
  - function load_and_import_buildings: ()
  - function verify_import: ()
  - function main: ()
- `scripts/extract_gml_landuse.py`
  - function parse_gml_landuse_attributes: (gml_file)
  - function update_postgis_with_landuse: (landuse_data)
  - function verify_updates: ()
  - function main: ()
- `scripts/import_alkis_buildings.py`
  - function gfk_to_building: (gfk) -> str
  - function get_engine: ()
  - function fetch_page: (start_index) -> dict
  - function parse_feature: (feat) -> Optional[dict]
  - function run_import: ()
- `scripts/import_buildings.py` — function import_buildings_data: ()
- `scripts/import_buildings_chunked.py` — function import_chunked: (), function main: ()
- `scripts/import_buildings_to_postgis.py`
  - function verify_input_file: ()
  - function truncate_current_table: ()
  - function load_and_prepare_data: ()
  - function import_to_postgis: (gdf)
  - function create_spatial_index: ()
  - function verify_import: ()
  - _...1 more_
- `scripts/import_custom_roads.py` — function import_custom_roads: (geojson_path, table_name, schema)
- `scripts/import_elu_gml.py`
  - function get_db_engine: ()
  - function load_gml_file: (gml_path)
  - function validate_geometries: (gdf)
  - function transform_to_wgs84: (gdf)
  - function prepare_data_for_postgis: (gdf)
  - function drop_existing_table: (engine)
  - _...5 more_
- `scripts/import_osm_buildings.py` — function import_osm_buildings: (), function main: ()
- `scripts/ingest_crime_data.py` — function clean_column_name: (col), function ingest_data: ()
- `scripts/ingest_data.py` — function main: (), class DataIngestion
- `scripts/ingest_street_lights.py` — function convert_multipoint_to_point: (geom), function ingest_street_lights: ()
- `scripts/load_allotment_gardens.py` — function load_gardens_to_postgis: ()
- `scripts/load_bplan_landuse.py`
  - function create_schema: (engine)
  - function load_geojson: (filepath)
  - function upload_to_postgis: (gdf, engine, table_name)
  - function create_spatial_index: (engine, table_name)
  - function get_table_statistics: (engine, table_name)
  - function main: ()
- `scripts/load_bplan_metadata.py`
  - function create_schema: (engine)
  - function extract_document_info: (row)
  - function load_geojson_as_dataframe: (filepath)
  - function upload_to_postgres: (df, engine)
  - function get_table_statistics: (engine)
  - function main: ()
- `scripts/load_detailnetz.py`
  - function create_schema: (engine)
  - function load_geojson: (filepath)
  - function upload_to_postgis: (gdf, engine, table_name)
  - function create_spatial_index: (engine, table_name)
  - function get_table_statistics: (engine, table_name)
  - function main: ()
- `scripts/load_landuse.py` — function load_landuse_to_postgis: ()
- `scripts/load_wasserschutzgebiete.py`
  - function create_schema: (engine)
  - function load_geojson: (filepath)
  - function upload_to_postgis: (gdf, engine)
  - function create_spatial_index: (engine)
  - function verify_data: (engine)
  - function get_table_statistics: (engine)
  - _...1 more_
- `scripts/repair_roads_topology.py` — function repair_topology: (tolerance)
- `scripts/run_supermarket_query.py`
  - function div: (char)
  - function header: (title)
  - function sub: (label, value)
  - function section: (n, name, subtitle)
  - function banner: (title)
  - function run_preflight: (provider) -> bool
  - _...9 more_
- `scripts/setup_business_intelligence.py`
  - function section: (title)
  - function ok: (msg)
  - function info: (msg)
  - function warn: (msg)
  - function run: ()
- `scripts/setup_database.py` — class PostGISSetup
- `scripts/setup_inspector_tables.py` — function setup_inspector_tables: ()
- `scripts/setup_metadata_tables.py` — function setup_metadata_tables: ()
- `scripts/test_api.py`
  - function test_health: ()
  - function test_datasets: ()
  - function test_query: (question)
  - function test_sql_query: ()
- `scripts/test_dem_api.py`
  - function print_response: (title, response, Any])
  - function test_dem_endpoints: ()
  - function example_queries: ()
- `scripts/test_llm_integration.py` — function test_provider: (provider, query)
- `scripts/test_ndvi_implementation.py`
  - function test_imports: ()
  - function test_raster_operations: ()
  - function test_spatial_engine_raster: ()
  - function test_api_routes: ()
  - function test_dependencies: ()
  - function test_file_structure: ()
  - _...2 more_
- `scripts/test_phase1_complete.py`
  - function print_section: (title)
  - function test_1_ndvi_difference: ()
  - function test_2_vegetation_loss_detection: ()
  - function test_3_vegetation_gain_detection: ()
  - function test_4_zonal_statistics: ()
  - function test_5_spatial_engine_integration: ()
  - _...2 more_
- `scripts/test_real_postgis.py` — function test_query: (question)
- `scripts/verify_geom_fix.py` — function test_missing_geom_query: ()
- `scripts/verify_import.py` — function verify_import: ()
- `scripts/verify_osm_expansion.py`
  - function print_header: (text)
  - function verify_tables: ()
  - function test_sample_queries: ()
- `scripts/visualize_dem_analysis.py`
  - function plot_raster: (raster_path, title, output_path, cmap, vmin, vmax)
  - function plot_vector: (vector_path, title, output_path)
  - function create_visualizations: ()

---

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

---

# Middleware

## custom
- migrate_table_descriptions — `scripts/migrate_table_descriptions.sql`

---

# Dependency Graph

## Most Imported Files (change these carefully)

- `/query_model.py` — imported by **1** files
- `/query.py` — imported by **1** files
- `/deepseek.py` — imported by **1** files
- `/spatial_engine.py` — imported by **1** files
- `/osm_loader.py` — imported by **1** files
- `/sentinel_loader.py` — imported by **1** files
- `/dem_loader.py` — imported by **1** files
- `/gadm_loader.py` — imported by **1** files
- `/copernicus_loader.py` — imported by **1** files

## Import Map (who imports what)

- `/query_model.py` ← `app/models/__init__.py`
- `/query.py` ← `app/routes/__init__.py`
- `/deepseek.py` ← `app/utils/__init__.py`
- `/spatial_engine.py` ← `app/utils/__init__.py`
- `/osm_loader.py` ← `app/utils/data_loaders/__init__.py`
- `/sentinel_loader.py` ← `app/utils/data_loaders/__init__.py`
- `/dem_loader.py` ← `app/utils/data_loaders/__init__.py`
- `/gadm_loader.py` ← `app/utils/data_loaders/__init__.py`
- `/copernicus_loader.py` ← `app/utils/data_loaders/__init__.py`

---

# Test Coverage

> **7%** of routes and models are covered by tests
> 23 test files found

## Covered Routes

- GET:/
- GET:/terrain-stats
- GET:/slope
- GET:/development-suitability
- GET:/classification

## Covered Models

- hospitals

---

_Generated by [codesight](https://github.com/Houseofmvps/codesight) — see your codebase clearly_