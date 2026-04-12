import json
from pathlib import Path
from typing import Any, Dict, Optional, List, Union
import geopandas as gpd
import pandas as pd
import numpy as np
from app.models.query_model import OperationPlan
from app.utils.sql_generator import sql_generator
import logging

logger = logging.getLogger(__name__)


class SpatialEngine:
    """
    Executes geospatial operations by running SQL queries in PostGIS.
    Extended to support raster operations (NDVI, DEM, land cover).
    DeepSeek generates SQL → PostGIS executes → Return GeoJSON
    """

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        # Only need result storage
        self.current_result: Optional[gpd.GeoDataFrame] = None

        # Initialize raster operations (lazy load)
        self._raster_ops = None

    def execute_plan(self, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute operation plan using PostGIS SQL or specialized routing.

        Args:
            plan: OperationPlan with SQL operations from DeepSeek

        Returns:
            Dictionary with GeoJSON results
        """
        try:
            # Check for routing operations first
            routing_op = next((op for op in plan.operations if op.operation == "routing"), None)
            if routing_op:
                return self._execute_routing_operation(routing_op, plan)



            # Check for nearest by road operations
            nearest_road_op = next((op for op in plan.operations if op.operation == "nearest_by_road"), None)
            if nearest_road_op:
                return self._execute_nearest_by_road_operation(nearest_road_op, plan)

            # Check for walking time operations (find POIs within walking time)
            walking_time_op = next((op for op in plan.operations if op.operation == "walking_time"), None)
            if walking_time_op:
                return self._execute_walking_time_operation(walking_time_op, plan)

            # Execute SQL operations via sql_generator
            result_gdf = sql_generator.execute_plan(plan)

            logger.info(f"Result GDF type: {type(result_gdf)}")
            if result_gdf is not None:
                logger.info(f"Result GDF length: {len(result_gdf)}")

            if result_gdf is not None and len(result_gdf) > 0:
                # Apply MCDA scoring if applicable
                query = plan.reasoning if plan.reasoning else ""  # Use reasoning as fallback for query context
                result_gdf = self.apply_mcda_scoring(result_gdf, query, plan)

                return self._format_result(result_gdf, plan)
            else:
                return {
                    "error": "No results found",
                    "success": False,
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }

        except Exception as e:
            logger.error(f"Error in execute_plan: {e}")
            return {
                "error": str(e),
                "success": False,
                "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
            }

    def apply_mcda_scoring(
        self,
        result_gdf: gpd.GeoDataFrame,
        query: str,
        plan: OperationPlan
    ) -> gpd.GeoDataFrame:
        """
        Apply multi-criteria decision analysis (MCDA) scoring to results.

        This method:
        1. Extracts criteria from the user query
        2. Assigns dynamic weights based on context
        3. Calculates normalized density scores
        4. Computes composite suitability scores

        OPTIMIZATION: Skip MCDA if query already has density columns calculated in SQL
        (e.g., when SQL query includes density calculations like '*_density', '*_per_km2')

        Args:
            result_gdf: GeoDataFrame with density data
            query: Original user query
            plan: OperationPlan with reasoning and context

        Returns:
            GeoDataFrame with added scoring columns
        """
        try:
            from app.utils.criteria_extractor import CriteriaExtractor
            from app.utils.weight_calculator import WeightCalculator
            from app.utils.density_scorer import DensityScorer

            # OPTIMIZATION: Check if density is already calculated in SQL
            # If the result already has density columns, skip expensive MCDA scoring
            density_columns = [col for col in result_gdf.columns if '_density' in col or '_per_km2' in col]
            if len(density_columns) >= 2:
                logger.info(f"MCDA: Density already calculated in SQL ({len(density_columns)} columns), skipping MCDA scoring")
                return result_gdf

            # Step 1: Extract criteria from query
            criteria_data = CriteriaExtractor.extract_criteria(query)

            logger.info(f"MCDA: Extracted {criteria_data['available_count']} criteria "
                       f"({criteria_data['missing_count']} unavailable)")

            # Only apply MCDA if we have multi-criteria scoring query AND small result set (< 100 rows)
            # For large aggregation queries (districts), density is calculated in SQL to avoid Python overhead
            if not criteria_data['has_scoring'] or criteria_data['available_count'] < 2 or len(result_gdf) > 100:
                logger.info(f"MCDA: Skipping MCDA - scoring={criteria_data.get('has_scoring', False)}, "
                           f"criteria={criteria_data.get('available_count', 0)}, rows={len(result_gdf)}")
                return result_gdf

            # Step 2: Calculate dynamic weights
            weights_result = WeightCalculator.calculate_weights(
                criteria_data,
                context=criteria_data['query_context']
            )

            if 'error' in weights_result:
                logger.warning(f"MCDA: Weight calculation failed: {weights_result['error']}")
                return result_gdf

            weights = weights_result['weights']
            criteria_tables = criteria_data['available_tables']

            logger.info(f"MCDA: Applied weights - {weights}")

            # Step 3: Convert GeoDataFrame to list of features for scoring
            features = []
            for idx, row in result_gdf.iterrows():
                feature = {
                    'properties': row.to_dict(),
                    'geometry': row.geometry.__geo_interface__ if hasattr(row.geometry, '__geo_interface__') else None
                }
                features.append(feature)

            # Step 4: Calculate composite scores
            scored_features, stats = DensityScorer.calculate_composite_scores(
                features,
                weights,
                criteria_tables
            )

            logger.info(f"MCDA: Calculated composite scores - "
                       f"min={stats['composite_score_range']['min']}, "
                       f"max={stats['composite_score_range']['max']}, "
                       f"mean={stats['composite_score_range']['mean']}")

            # Step 5: Update result_gdf with scores
            result_gdf['composite_score'] = [f['properties'].get('composite_score', 0) for f in scored_features]
            result_gdf['score_breakdown'] = [f['properties'].get('score_breakdown', {}) for f in scored_features]
            result_gdf['criterion_scores'] = [f['properties'].get('criterion_scores', {}) for f in scored_features]
            result_gdf['weights_used'] = [f['properties'].get('weights_used', {}) for f in scored_features]
            result_gdf['included_criteria'] = [criteria_data['available_tables']] * len(result_gdf)
            result_gdf['excluded_criteria'] = [
                [{'name': c['name'], 'reason': c.get('reason', 'Unknown')}
                 for c in criteria_data['criteria'] if not c['available']]
            ] * len(result_gdf)

            # Store metadata for response
            result_gdf.attrs['mcda_metadata'] = {
                'scoring_applied': True,
                'context': criteria_data['query_context'],
                'available_criteria': criteria_data['available_tables'],
                'excluded_criteria': criteria_data['missing_tables'],
                'weights': weights,
                'weight_metadata': weights_result.get('weight_metadata', {}),
                'statistics': stats,
                'redistribution_applied': weights_result.get('redistribution_applied', False),
                'weight_method': weights_result.get('weight_method', 'unknown')
            }

            # Sort by composite score
            result_gdf = result_gdf.sort_values('composite_score', ascending=False)

            return result_gdf

        except Exception as e:
            logger.error(f"MCDA scoring failed: {e}")
            logger.exception(e)
            # Return original GDF without scoring if MCDA fails
            return result_gdf

    def execute_stats_plan(self, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute operation plan for statistical/aggregation queries (non-spatial).

        Args:
            plan: OperationPlan with SQL operations from DeepSeek

        Returns:
            Dictionary with tabular/statistical results (not GeoJSON)
        """
        try:
            from app.utils.database import db_manager

            # For stats queries, execute all operations and combine results
            all_results = []

            for operation in plan.operations:
                if operation.operation == "spatial_query":
                    # Execute non-spatial query and get DataFrame
                    sql = operation.parameters.get("sql", "")
                    if sql:
                        logger.info(f"Executing stats query: {sql[:100]}...")
                        result_df = db_manager.execute_query(sql)
                        all_results.append(result_df)
                        logger.info(f"Query returned {len(result_df)} rows")

            if all_results:
                # Combine all results if multiple queries
                if len(all_results) == 1:
                    combined_df = all_results[0]
                else:
                    # For multiple queries, combine by merging on common columns
                    import pandas as pd
                    combined_df = all_results[0]
                    for df in all_results[1:]:
                        # Merge on district column if present
                        if 'bezirk' in combined_df.columns and 'bezirk' in df.columns:
                            combined_df = pd.merge(combined_df, df, on='bezirk', how='outer')
                        else:
                            # Otherwise just concatenate side by side
                            combined_df = pd.concat([combined_df, df], axis=1)

                return self._format_stats_result(combined_df)
            else:
                return {
                    "error": "No results found",
                    "success": False,
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }

        except Exception as e:
            logger.error(f"Error in execute_stats_plan: {e}")
            return {
                "error": str(e),
                "success": False,
                "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
            }

    def _execute_routing_operation(self, routing_op, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute a routing operation to find shortest paths or optimal tours.

        Supports two modes:
        1. "pairwise": Find all pairwise shortest paths between selected features
        2. "optimal_tour": Find single optimal tour connecting all features (closed loop)

        Args:
            routing_op: GeospatialOperation with type "routing"
            plan: OperationPlan for context and metadata

        Returns:
            Dictionary with route geometries as GeoJSON
        """
        try:
            from app.utils.database import db_manager

            params = routing_op.parameters
            geometries = params.get("geometries", [])
            feature_names = params.get("feature_names", [])
            mode = params.get("mode", "pairwise")  # Default to pairwise for backward compatibility

            if not geometries or len(geometries) < 2:
                return {
                    "success": False,
                    "error": "Need at least 2 geometries for routing",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }

            logger.info(f"🛣️  Computing {mode} routes for {len(geometries)} features")

            # Route computation based on mode
            if mode == "optimal_tour":
                # Try Valhalla first for more accurate pedestrian routing
                try:
                    from app.utils.valhalla_routing import valhalla_service
                    
                    health = valhalla_service.check_health()
                    if health.get("status") == "healthy":
                        logger.info("🛣️  Using Valhalla for optimal tour routing")
                        
                        # Extract coordinates from geometries
                        points = []
                        for geom in geometries:
                            if geom.get("type") == "Point":
                                coords = geom.get("coordinates", [])
                                if len(coords) >= 2:
                                    points.append((coords[1], coords[0]))  # (lat, lon)
                        
                        if len(points) >= 2:
                            route_result = valhalla_service.get_multi_point_route(points)
                            
                            if route_result.success:
                                feature = {
                                    "type": "Feature",
                                    "geometry": route_result.geometry,
                                    "properties": {
                                        "route_type": "optimal_tour",
                                        "total_distance_m": route_result.distance_m,
                                        "total_distance_km": round(route_result.distance_m / 1000, 2),
                                        "total_time_minutes": round(route_result.duration_minutes, 1),
                                        "waypoint_count": len(points),
                                        "algorithm": "Valhalla Pedestrian",
                                        "road_network": "OpenStreetMap Berlin"
                                    }
                                }
                                
                                geojson = {
                                    "type": "FeatureCollection",
                                    "features": [feature]
                                }
                                
                                # Build layer name from feature names
                                if feature_names:
                                    layer_name = "Route: " + " → ".join(feature_names[:5])
                                    if len(feature_names) > 5:
                                        layer_name += " ..."
                                else:
                                    layer_name = f"optimal_tour_{len(points)}_stops"
                                
                                metadata = {
                                    "algorithm": "Valhalla Pedestrian",
                                    "road_network": "OpenStreetMap Berlin",
                                    "routing_engine": "valhalla",
                                    "total_distance_m": round(route_result.distance_m, 2),
                                    "total_distance_km": round(route_result.distance_m / 1000, 2),
                                    "total_time_minutes": round(route_result.duration_minutes, 1),
                                    "directions": route_result.maneuvers,
                                    "feature_count": len(points),
                                    "waypoint_count": len(points)
                                }
                                
                                return {
                                    "success": True,
                                    "result_type": "routing",
                                    "data": geojson,
                                    "layer_name": layer_name,
                                    "metadata": metadata,
                                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                                }
                            else:
                                logger.warning(f"Valhalla routing failed: {route_result.error}")
                    else:
                        logger.warning("Valhalla not available for optimal tour routing")
                        
                except ImportError:
                    logger.error("Valhalla module not available")
                except Exception as e:
                    logger.error(f"Valhalla error: {e}")
                
                return {
                    "success": False,
                    "error": "Valhalla routing service is required but not available",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }

            else:  # pairwise mode (default) - for 2+ point routing
                # Try Valhalla first for simple routes (especially 2-point)
                try:
                    from app.utils.valhalla_routing import valhalla_service
                    
                    health = valhalla_service.check_health()
                    if health.get("status") == "healthy":
                        # Extract coordinates from geometries
                        points = []
                        for geom in geometries:
                            if geom.get("type") == "Point":
                                coords = geom.get("coordinates", [])
                                if len(coords) >= 2:
                                    points.append((coords[1], coords[0]))  # (lat, lon)
                            elif geom.get("type") in ["Polygon", "MultiPolygon"]:
                                # For polygons, use centroid
                                from shapely.geometry import shape
                                shapely_geom = shape(geom)
                                centroid = shapely_geom.centroid
                                points.append((centroid.y, centroid.x))  # (lat, lon)
                        
                        if len(points) >= 2:
                            logger.info(f"🚶 Using Valhalla for pedestrian route between {len(points)} points")
                            
                            # For 2 points, use simple route
                            if len(points) == 2:
                                route_result = valhalla_service.get_pedestrian_route(
                                    origin_lat=points[0][0],
                                    origin_lon=points[0][1],
                                    dest_lat=points[1][0],
                                    dest_lon=points[1][1]
                                )
                            else:
                                # For 3+ points, use multi-point route
                                route_result = valhalla_service.get_multi_point_route(points)
                            
                            if route_result.success:
                                feature = {
                                    "type": "Feature",
                                    "geometry": route_result.geometry,
                                    "properties": {
                                        "route_type": "pedestrian",
                                        "from_index": 0,
                                        "to_index": len(points) - 1,
                                        "distance_m": round(route_result.distance_m, 2),
                                        "distance_km": round(route_result.distance_m / 1000, 2),
                                        "duration_minutes": round(route_result.duration_minutes, 1),
                                        "walking_time_min": round(route_result.duration_minutes, 1),
                                        "algorithm": "Valhalla Pedestrian",
                                        "road_network": "OpenStreetMap Berlin"
                                    }
                                }
                                
                                # Add feature names if available
                                if feature_names:
                                    if len(feature_names) > 0:
                                        feature["properties"]["from_name"] = feature_names[0]
                                    if len(feature_names) > 1:
                                        feature["properties"]["to_name"] = feature_names[-1]
                                
                                geojson = {
                                    "type": "FeatureCollection",
                                    "features": [feature]
                                }
                                
                                # Build descriptive layer name
                                if feature_names and len(feature_names) >= 2:
                                    layer_name = f"Route: {feature_names[0]} → {feature_names[-1]}"
                                else:
                                    layer_name = f"Walking Route ({route_result.duration_minutes:.1f} min)"
                                
                                metadata = {
                                    "algorithm": "Valhalla Pedestrian",
                                    "routing_engine": "valhalla",
                                    "road_network": "OpenStreetMap Berlin",
                                    "total_distance_m": round(route_result.distance_m, 2),
                                    "total_distance_km": round(route_result.distance_m / 1000, 2),
                                    "total_time_minutes": round(route_result.duration_minutes, 1),
                                    "walking_speed_kmh": 5.1,
                                    "directions": route_result.maneuvers,
                                    "feature_count": len(points)
                                }
                                
                                logger.info(f"✅ Valhalla route: {route_result.distance_m:.0f}m, {route_result.duration_minutes:.1f} min")
                                
                                return {
                                    "success": True,
                                    "result_type": "routing",
                                    "data": geojson,
                                    "layer_name": layer_name,
                                    "metadata": metadata,
                                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                                }
                            else:
                                logger.warning(f"Valhalla routing failed: {route_result.error}")
                    else:
                        logger.warning("Valhalla not available for pairwise routing")
                        
                except ImportError:
                    logger.error("Valhalla module not available")
                except Exception as e:
                    logger.error(f"Valhalla error: {e}")
                
                return {
                    "success": False,
                    "error": "Valhalla routing service is required but not available",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }

        except Exception as e:
            logger.error(f"Error in _execute_routing_operation: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
            }



    def _execute_nearest_by_road_operation(self, nearest_op, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute nearest by road operation - find nearest POI using road network distance.
        
        Parameters expected:
            - origin_lon, origin_lat: Origin point coordinates (OR session_id to extract from selected)
            - target_table: Table to search (e.g., 'vector.osm_supermarkets')
            - max_candidates: Optional max candidates to check (default 15)
            - max_radius_m: Optional pre-filter radius in meters (default 5000)
            - session_id: Optional session ID to extract coordinates from selected feature
        """
        try:
            from app.utils.database import db_manager
            from shapely.geometry import shape, mapping
            from sqlalchemy import text
            
            params = nearest_op.parameters
            origin_lon = params.get("origin_lon")
            origin_lat = params.get("origin_lat")
            target_table = params.get("target_table")
            max_candidates = params.get("max_candidates", 15)
            max_radius_m = params.get("max_radius_m", 5000)
            session_id = params.get("session_id")
            location_name = params.get("location_name")  # e.g., "Wedding", "Mitte"
            where_clause = params.get("where_clause")  # e.g., "brand ILIKE '%Netto%'"
            
            # If no coordinates provided, try to extract from selected feature
            if (not origin_lon or not origin_lat) and session_id:
                logger.info(f"Extracting coordinates from selected feature (session: {session_id})")
                try:
                    # First check if the temp table exists
                    temp_table = f"temp.temp_selected_{session_id}"
                    check_query = f"""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = 'temp' 
                            AND table_name = 'temp_selected_{session_id}'
                        ) as table_exists
                    """
                    db_manager.initialize()
                    with db_manager.engine.connect() as conn:
                        check_result = conn.execute(text(check_query))
                        exists = check_result.fetchone()[0]
                        
                        if exists:
                            coord_query = f"""
                                SELECT 
                                    ST_X(ST_Centroid(ST_Union(geometry))) as lon,
                                    ST_Y(ST_Centroid(ST_Union(geometry))) as lat
                                FROM {temp_table}
                            """
                            result = conn.execute(text(coord_query))
                            row = result.fetchone()
                            if row and row[0] and row[1]:
                                origin_lon = float(row[0])
                                origin_lat = float(row[1])
                                logger.info(f"Extracted coordinates: ({origin_lon}, {origin_lat})")
                        else:
                            logger.warning(f"Temp table {temp_table} does not exist, will try location_name lookup")
                except Exception as e:
                    logger.warning(f"Could not extract coordinates from selected feature: {e}")
            
            # Fallback: Resolve location name via Nominatim
            if (not origin_lon or not origin_lat) and location_name:
                logger.info(f"Resolving location via Nominatim: {location_name}")
                try:
                    from app.utils.location_resolver import resolve_location
                    loc = resolve_location(location_name)
                    if loc:
                        bbox = loc.get("bbox")
                        if bbox:
                            origin_lon = (bbox[0] + bbox[2]) / 2
                            origin_lat = (bbox[1] + bbox[3]) / 2
                            logger.info(f"Resolved '{location_name}' to ({origin_lon}, {origin_lat})")
                except Exception as e:
                    logger.warning(f"Could not resolve location '{location_name}': {e}")

            # Validate required parameters
            if not origin_lon or not origin_lat:
                return {
                    "success": False,
                    "error": "Missing origin coordinates. Please select a feature or provide location.",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }
            
            if not target_table:
                return {
                    "success": False,
                    "error": "Missing target table. Please specify what to find (e.g., supermarkets).",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }
            
            # Ensure table has schema prefix (LLM sometimes omits it)
            if '.' not in target_table:
                target_table = f"vector.{target_table}"
            
            logger.info(f"Finding nearest from ({origin_lon}, {origin_lat}) in {target_table}")
            if where_clause:
                logger.info(f"📋 With filter: {where_clause}")
            
            # Call the database function
            result = db_manager.find_nearest_by_road_distance(
                origin_lon=origin_lon,
                origin_lat=origin_lat,
                target_table=target_table,
                max_candidates=max_candidates,
                max_radius_m=max_radius_m,
                where_clause=where_clause
            )
            
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Failed to find nearest by road"),
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }
            
            # Build GeoJSON response with only the POI (route LineString suppressed for nearest queries)
            features = []

            poi_feature = result["feature"]
            if poi_feature.get("geometry"):
                poi_properties = {k: v for k, v in poi_feature.items() if k != "geometry"}
                poi_properties["road_distance_m"] = result["road_distance_m"]
                poi_properties["straight_line_m"] = result["straight_line_m"]
                poi_properties["duration_minutes"] = result.get("duration_minutes")
                poi_geojson = {
                    "type": "Feature",
                    "geometry": poi_feature["geometry"],
                    "properties": poi_properties
                }
                features.append(poi_geojson)
            
            geojson = {
                "type": "FeatureCollection",
                "features": features
            }
            
            metadata = {
                "query_type": "nearest_by_road",
                "road_distance_m": round(result["road_distance_m"], 1),
                "straight_line_m": round(result["straight_line_m"], 1),
                "total_distance_m": round(result["total_distance_m"], 1),
                "candidates_checked": result["candidates_checked"],
                "routable_candidates": result["routable_candidates"],
                "target_table": target_table
            }
            
            # Get name for layer
            poi_name = result["feature"].get("name", "Unnamed")
            layer_name = f"Nearest: {poi_name} ({round(result['road_distance_m'])}m by road)"
            
            return {
                "success": True,
                "result_type": "nearest_by_road",
                "data": geojson,
                "layer_name": layer_name,
                "metadata": metadata,
                "reasoning": f"Found {poi_name} at {round(result['road_distance_m'])}m by road (vs {round(result['straight_line_m'])}m straight-line)"
            }
            
        except Exception as e:
            logger.error(f"Error in _execute_nearest_by_road_operation: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
            }

    def _execute_walking_time_operation(self, walking_op, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute walking time operation - find POIs within walking time using road network.
        
        Parameters expected:
            - location: {lat, lon} or session_id to extract from selected feature
            - time_minutes: Walking time in minutes (default 10)
            - target_table: Table to search (e.g., 'osm_supermarkets', 'alkis_buildings')
            - buffer_m: Buffer distance from roads (default 30m)
            - limit: Max results (default 5000)
            - session_id: Optional session ID to extract coordinates from selected feature
        """
        try:
            from app.utils.walking_distance import walking_distance_service
            from app.utils.database import db_manager
            from sqlalchemy import text
            
            params = walking_op.parameters
            location = params.get("location") or {}
            lat = location.get("lat")
            lon = location.get("lon")
            time_minutes = params.get("time_minutes", 10)
            target_table = params.get("target_table", "alkis_buildings")
            building_filter = params.get("building_filter")  # e.g., "building IN ('commercial', 'retail')"
            buffer_m = params.get("buffer_m", 30)
            limit = params.get("limit", 5000)
            session_id = params.get("session_id")
            include_coverage = False  # Always disabled - coverage polygon not shown
            
            # If no coordinates provided, try to extract from selected feature
            location_name = params.get("location_name")  # e.g., "Wedding", "Mitte"
            
            if (not lat or not lon) and session_id:
                logger.info(f"Extracting coordinates from selected feature (session: {session_id})")
                try:
                    temp_table = f"temp.temp_selected_{session_id}"
                    # First check if the temp table exists
                    check_query = f"""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = 'temp' 
                            AND table_name = 'temp_selected_{session_id}'
                        ) as table_exists
                    """
                    db_manager.initialize()
                    with db_manager.engine.connect() as conn:
                        check_result = conn.execute(text(check_query))
                        exists = check_result.fetchone()[0]
                        
                        if exists:
                            coord_query = f"""
                                SELECT 
                                    ST_X(ST_Centroid(ST_Union(geometry))) as lon,
                                    ST_Y(ST_Centroid(ST_Union(geometry))) as lat
                                FROM {temp_table}
                            """
                            result = conn.execute(text(coord_query))
                            row = result.fetchone()
                            if row and row[0] and row[1]:
                                lon = float(row[0])
                                lat = float(row[1])
                                logger.info(f"Extracted coordinates: ({lon}, {lat})")
                        else:
                            logger.warning(f"Temp table {temp_table} does not exist, will try location_name lookup")
                except Exception as e:
                    logger.warning(f"Could not extract coordinates from selected feature: {e}")
            
            # Fallback: Resolve location name via Nominatim
            if (not lat or not lon) and location_name:
                logger.info(f"Resolving location via Nominatim: {location_name}")
                try:
                    from app.utils.location_resolver import resolve_location
                    loc = resolve_location(location_name)
                    if loc:
                        bbox = loc.get("bbox")
                        if bbox:
                            lon = (bbox[0] + bbox[2]) / 2
                            lat = (bbox[1] + bbox[3]) / 2
                            logger.info(f"Resolved '{location_name}' to ({lon}, {lat})")
                except Exception as e:
                    logger.warning(f"Could not resolve location '{location_name}': {e}")
            
            # Validate required parameters
            if not lat or not lon:
                return {
                    "success": False,
                    "error": "Missing location. Please select a feature or provide coordinates.",
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }
            
            logger.info(f"🚶 Finding {target_table} within {time_minutes} min walk of ({lon}, {lat})")
            if building_filter:
                logger.info(f"📋 With filter: {building_filter}")
            
            # Call walking distance service - uses Valhalla if available, falls back to pgRouting
            result = walking_distance_service.find_buildings_within_walking_time(
                lat=lat,
                lon=lon,
                time_minutes=time_minutes,
                building_table=target_table,
                building_filter=building_filter,
                limit=limit
            )
            
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Walking time query failed"),
                    "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
                }
            
            # Get the GeoJSON data
            geojson = result.get("data", {"type": "FeatureCollection", "features": []})
            metadata = result.get("metadata", {})
            
            # Optionally add coverage polygon
            if include_coverage:
                coverage_result = walking_distance_service.get_walking_coverage(
                    lat=lat,
                    lon=lon,
                    time_minutes=time_minutes,
                    buffer_m=buffer_m
                )
                if coverage_result.get("success"):
                    coverage_features = coverage_result.get("data", {}).get("features", [])
                    # Add coverage as first feature with distinct styling
                    for cf in coverage_features:
                        cf["properties"]["feature_type"] = "walking_coverage"
                        cf["properties"]["style"] = {
                            "fillColor": "#3388ff",
                            "fillOpacity": 0.15,
                            "color": "#3388ff",
                            "weight": 2
                        }
                    # Prepend coverage features
                    geojson["features"] = coverage_features + geojson.get("features", [])
            
            # Add feature type to POI features
            for feature in geojson.get("features", []):
                if feature.get("properties", {}).get("feature_type") != "walking_coverage":
                    feature["properties"]["feature_type"] = "walking_time_poi"
            
            # Build layer name
            table_display = target_table.replace("osm_", "").replace("_", " ").title()
            layer_name = f"{table_display} within {time_minutes} min walk"
            
            return {
                "success": True,
                "result_type": "walking_time",
                "data": geojson,
                "layer_name": layer_name,
                "metadata": {
                    "query_type": "walking_time",
                    "time_minutes": time_minutes,
                    "walking_speed_kmh": metadata.get("walking_speed_kmh", 6.0),
                    "distance_limit_m": metadata.get("distance_limit_m"),
                    "buffer_m": buffer_m,
                    "target_table": target_table,
                    "building_count": metadata.get("building_count", 0),
                    "start_point": {"lat": lat, "lon": lon}
                },
                "reasoning": f"Found {metadata.get('building_count', 0)} {table_display} within {time_minutes} min walk"
            }
            
        except Exception as e:
            logger.error(f"Error in _execute_walking_time_operation: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "reasoning": plan.reasoning if hasattr(plan, 'reasoning') else ""
            }

    def _format_result(self, gdf: gpd.GeoDataFrame, plan: OperationPlan = None) -> Dict[str, Any]:
        """
        Format GeoDataFrame as GeoJSON response.

        Args:
            gdf: GeoDataFrame with results
            plan: Optional OperationPlan for including reasoning and other metadata

        Returns:
            Dictionary with GeoJSON and metadata
        """
        # Convert to WGS84 for GeoJSON
        if gdf.crs and gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")

        # Check geometry before filtering
        total_before = len(gdf)
        null_geoms = gdf.geometry.isna().sum()
        if null_geoms > 0:
            logger.warning(f"Found {null_geoms} features with NULL geometries before validation")

        # Filter out invalid geometries (None, empty, or with NaN bounds)
        gdf_valid = gdf[gdf.geometry.is_valid].copy()
        invalid_count = total_before - len(gdf_valid)

        if invalid_count > 0:
            logger.warning(f"Filtered out {invalid_count}/{total_before} features with invalid geometries")
            # Log sample of invalid geometries for debugging
            invalid_gdf = gdf[~gdf.geometry.is_valid]
            for _, (i, row) in enumerate(invalid_gdf.head(3).iterrows()):
                geom_type = type(row.geometry).__name__ if row.geometry is not None else "None"
                logger.warning(f"  Invalid geometry {i}: type={geom_type}, {row.geometry}")

        gdf = gdf_valid

        if len(gdf) == 0:
            error_msg = f"No valid geometries found (filtered {invalid_count} invalid, {null_geoms} NULL)"
            logger.error(error_msg)
            return {
                "success": True,
                "result_type": "geojson",
                "data": {"type": "FeatureCollection", "features": []},
                "metadata": {
                    "count": 0,
                    "crs": "EPSG:4326",
                    "bounds": [],
                    "message": error_msg,
                    "total_features_before_filter": total_before,
                    "invalid_geometries_filtered": invalid_count,
                    "null_geometries": null_geoms
                }
            }

        # Get metadata
        bounds = gdf.total_bounds.tolist() if len(gdf) > 0 else []

        # Check for NaN in bounds
        if bounds and any(np.isnan(b) if isinstance(b, (int, float)) else False for b in bounds):
            bounds = []

        metadata = {
            "count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else "EPSG:4326",
            "bounds": bounds
        }

        # Add MCDA metadata if available
        if hasattr(gdf, 'attrs') and 'mcda_metadata' in gdf.attrs:
            metadata['mcda'] = gdf.attrs['mcda_metadata']

        # Add any custom metadata
        if hasattr(gdf, 'metadata'):
            metadata.update(gdf.metadata)

        # Drop datetime columns that can't be serialized and convert Decimal to float
        gdf_copy = gdf.copy()
        for col in gdf_copy.columns:
            # Skip geometry column - it has a special dtype that numpy doesn't understand
            if col == 'geometry':
                continue

            if gdf_copy[col].dtype == 'datetime64[ns]' or str(gdf_copy[col].dtype) == 'datetime64[ns, UTC]':
                gdf_copy[col] = gdf_copy[col].astype(str)
            # Handle object types (could be Decimal, dict, list, or string)
            elif gdf_copy[col].dtype == 'object':
                # Check if first non-null value to determine type
                first_val = gdf_copy[col].dropna().iloc[0] if len(gdf_copy[col].dropna()) > 0 else None
                if first_val is not None:
                    first_type = type(first_val).__name__
                    if first_type == 'Decimal':
                        # Convert Decimal to float
                        gdf_copy[col] = gdf_copy[col].astype(float)
                    # Otherwise keep dicts, lists, and strings as-is (they're JSON serializable)
            # Replace NaN values in numeric columns with None (which becomes null in JSON)
            else:
                try:
                    if np.issubdtype(gdf_copy[col].dtype, np.floating):
                        gdf_copy[col] = gdf_copy[col].where(~gdf_copy[col].isna(), None)
                    elif np.issubdtype(gdf_copy[col].dtype, np.integer):
                        # For integers, convert NaN to None
                        gdf_copy[col] = gdf_copy[col].where(gdf_copy[col].notna(), None)
                except (TypeError, AttributeError):
                    # Skip columns with non-standard dtypes
                    pass

        # Convert to GeoJSON with custom JSON handler for NaN values
        try:
            # Use __geo_interface__ for more robust conversion
            geojson = gdf_copy.__geo_interface__
        except Exception as e:
            logger.error(f"Error with __geo_interface__: {e}")
            # Fallback to to_json() method
            try:
                geojson_str = gdf_copy.to_json()
                # Replace any remaining NaN values in the JSON string
                geojson_str = geojson_str.replace('NaN', 'null')
                geojson = json.loads(geojson_str)
            except Exception as json_error:
                logger.error(f"Error converting to GeoJSON: {json_error}")
                return {
                    "success": True,
                    "result_type": "geojson",
                    "data": {"type": "FeatureCollection", "features": []},
                    "metadata": {
                        **metadata,
                        "error": f"Error serializing geometries: {str(json_error)}"
                    }
                }

        return {
            "success": True,
            "result_type": "geojson",
            "data": geojson,
            "metadata": metadata
        }

    def _format_stats_result(self, data) -> Dict[str, Any]:
        """
        Format non-spatial results (aggregations, statistics) as JSON table.

        Args:
            data: GeoDataFrame or DataFrame with statistical results

        Returns:
            Dictionary with tabular results
        """
        try:
            # Convert to DataFrame if needed (remove geometry column if present)
            if isinstance(data, gpd.GeoDataFrame):
                df = data.drop(columns=['geometry'], errors='ignore')
            else:
                df = data

            # Convert to list of dictionaries for JSON serialization
            records = []
            for _, row in df.iterrows():
                record = {}
                for col in df.columns:
                    val = row[col]
                    # Handle different data types for JSON serialization
                    if pd.isna(val):
                        record[col] = None
                    elif isinstance(val, (np.integer, np.floating)):
                        record[col] = float(val)
                    elif isinstance(val, (int, float)):
                        record[col] = val
                    else:
                        record[col] = str(val)
                records.append(record)

            metadata = {
                "count": len(df),
                "columns": list(df.columns),
                "message": f"Statistical query returned {len(df)} rows"
            }

            return {
                "success": True,
                "result_type": "table",
                "data": records,
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"Error formatting stats result: {e}")
            return {
                "success": False,
                "error": f"Error formatting results: {str(e)}",
                "result_type": "table",
                "data": []
            }

    # ==================== Raster Operations Support ====================

    @property
    def raster_ops(self):
        """Lazy load raster operations module"""
        if self._raster_ops is None:
            from app.utils.raster_operations import RasterOperations
            self._raster_ops = RasterOperations()
        return self._raster_ops

    def execute_raster_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute raster-specific operations (NDVI, change detection, zonal stats)

        Args:
            operation: Dictionary describing raster operation
                {
                    'type': 'ndvi_change' | 'zonal_stats' | 'clip_raster' | 'vectorize',
                    'params': {...}
                }

        Returns:
            Result dictionary (GeoJSON or statistics)
        """
        op_type = operation.get('type')
        params = operation.get('params', {})

        try:
            if op_type == 'ndvi_change':
                return self._execute_ndvi_change(params)

            elif op_type == 'zonal_stats':
                return self._execute_zonal_stats(params)

            elif op_type == 'clip_raster':
                return self._execute_clip_raster(params)

            elif op_type == 'vectorize_raster':
                return self._execute_vectorize_raster(params)

            elif op_type == 'vegetation_loss':
                return self._execute_vegetation_loss(params)

            else:
                return {
                    "error": f"Unknown raster operation type: {op_type}",
                    "success": False
                }

        except Exception as e:
            logger.error(f"Error executing raster operation '{op_type}': {e}")
            return {
                "error": str(e),
                "success": False,
                "operation": op_type
            }

    def _execute_ndvi_change(self, params: Dict) -> Dict[str, Any]:
        """Execute NDVI change detection"""
        ndvi_t1 = self.data_dir / params['ndvi_t1']
        ndvi_t2 = self.data_dir / params['ndvi_t2']
        threshold = params.get('threshold', -0.2)

        # Check if raster files exist
        if not ndvi_t1.exists():
            return {
                "success": False,
                "error": f"NDVI raster file not found: {ndvi_t1}. Please download Sentinel-2 NDVI data to data/raster/ndvi_timeseries/",
                "result_type": "error"
            }
        if not ndvi_t2.exists():
            return {
                "success": False,
                "error": f"NDVI raster file not found: {ndvi_t2}. Please download Sentinel-2 NDVI data to data/raster/ndvi_timeseries/",
                "result_type": "error"
            }

        # Compute difference
        diff = self.raster_ops.ndvi_difference(ndvi_t1, ndvi_t2)

        # Detect loss
        loss_areas = self.raster_ops.detect_vegetation_loss(
            diff,
            threshold=threshold
        )

        # Format result
        if len(loss_areas) > 0:
            return self._format_result(loss_areas)
        else:
            return {
                "success": True,
                "result_type": "geojson",
                "data": {"type": "FeatureCollection", "features": []},
                "metadata": {"count": 0, "message": "No vegetation loss detected"}
            }

    def _execute_vegetation_loss(self, params: Dict) -> Dict[str, Any]:
        """
        Detect vegetation loss in specific land use areas

        Params:
            - ndvi_t1: Path to earlier NDVI raster
            - ndvi_t2: Path to later NDVI raster
            - mask_vector: Optional vector layer to mask results
            - threshold: Loss threshold (default: -0.2)
        """
        ndvi_t1 = self.data_dir / params['ndvi_t1']
        ndvi_t2 = self.data_dir / params['ndvi_t2']
        threshold = params.get('threshold', -0.2)

        # Check if raster files exist
        if not ndvi_t1.exists():
            return {
                "success": False,
                "error": f"NDVI raster file not found: {ndvi_t1}. Please download Sentinel-2 NDVI data to data/raster/ndvi_timeseries/",
                "result_type": "error"
            }
        if not ndvi_t2.exists():
            return {
                "success": False,
                "error": f"NDVI raster file not found: {ndvi_t2}. Please download Sentinel-2 NDVI data to data/raster/ndvi_timeseries/",
                "result_type": "error"
            }

        # Compute difference and save to temp file
        diff_path = self.data_dir / "temp" / "ndvi_diff_temp.tif"
        diff_path.parent.mkdir(parents=True, exist_ok=True)

        diff = self.raster_ops.ndvi_difference(
            ndvi_t1,
            ndvi_t2,
            output_path=diff_path
        )

        # Detect loss (using the saved file path)
        loss_areas = self.raster_ops.detect_vegetation_loss(diff_path, threshold=threshold)

        # Optional: filter by mask vector (e.g., residential areas)
        if 'mask_vector' in params and len(loss_areas) > 0:
            mask_path = self.data_dir / params['mask_vector']
            mask_gdf = gpd.read_file(mask_path)

            # Ensure same CRS
            if mask_gdf.crs != loss_areas.crs:
                mask_gdf = mask_gdf.to_crs(loss_areas.crs)

            # Spatial intersection
            loss_areas = gpd.overlay(loss_areas, mask_gdf, how='intersection')

        return self._format_result(loss_areas)

    def _execute_zonal_stats(self, params: Dict) -> Dict[str, Any]:
        """Execute zonal statistics"""
        raster_path = self.data_dir / params['raster']
        vector_path = self.data_dir / params['vector']
        stats = params.get('stats', ['mean', 'min', 'max'])

        # Load vector
        polygons = gpd.read_file(vector_path)

        # Compute stats
        results = self.raster_ops.zonal_stats(
            raster=raster_path,
            polygons=polygons,
            stats=stats
        )

        # Add stats to GeoDataFrame
        for stat, values in results.items():
            if stat != 'categories':
                polygons[f'zonal_{stat}'] = values

        return self._format_result(polygons)

    def _execute_clip_raster(self, params: Dict) -> Dict[str, Any]:
        """Clip raster by vector polygon"""
        raster_path = self.data_dir / params['raster']
        vector_path = self.data_dir / params['vector']
        output_path = self.data_dir / params.get('output', 'temp/clipped.tif')

        # Load vector
        vector = gpd.read_file(vector_path)

        # Clip
        result_path = self.raster_ops.clip_raster_by_vector(
            raster_path,
            vector,
            output_path
        )

        return {
            "success": True,
            "result_type": "raster",
            "output_path": str(result_path),
            "metadata": {"operation": "clip_raster"}
        }

    def _execute_vectorize_raster(self, params: Dict) -> Dict[str, Any]:
        """Convert raster to vector polygons"""
        raster_path = self.data_dir / params['raster']
        threshold = params.get('threshold')
        operator = params.get('operator', 'greater')

        # Vectorize
        polygons = self.raster_ops.vectorize_raster(
            raster_path,
            threshold=threshold,
            operator=operator
        )

        return self._format_result(polygons)

    def execute_hybrid_operation(
        self,
        raster_ops: List[Dict],
        vector_ops: List[Dict],
        integration_type: str = 'overlay'
    ) -> Dict[str, Any]:
        """
        Execute operations that combine raster and vector data

        Args:
            raster_ops: List of raster operations to execute
            vector_ops: List of vector operations to execute
            integration_type: How to combine results ('overlay', 'zonal_stats', 'clip')

        Returns:
            Integrated result dictionary
        """
        # Execute raster operations
        raster_results = []
        for op in raster_ops:
            result = self.execute_raster_operation(op)
            if result.get('success'):
                raster_results.append(result)

        # Execute vector operations (via existing SQL generator)
        vector_results = []
        for op in vector_ops:
            # This would call existing vector operation methods
            pass

        # Integration logic would go here
        # For now, return raster results
        if raster_results:
            return raster_results[0]
        else:
            return {
                "error": "No successful operations",
                "success": False
            }
