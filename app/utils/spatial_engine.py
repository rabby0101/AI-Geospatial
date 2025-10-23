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
    Simple and clean: DeepSeek generates SQL → PostGIS executes → Return GeoJSON
    """

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        # Only need result storage
        self.current_result: Optional[gpd.GeoDataFrame] = None

        # Initialize raster operations (lazy load)
        self._raster_ops = None

    def execute_plan(self, plan: OperationPlan) -> Dict[str, Any]:
        """
        Execute operation plan using PostGIS SQL.

        Args:
            plan: OperationPlan with SQL operations from DeepSeek

        Returns:
            Dictionary with GeoJSON results
        """
        try:
            # Execute SQL operations via sql_generator
            result_gdf = sql_generator.execute_plan(plan)

            logger.info(f"Result GDF type: {type(result_gdf)}")
            if result_gdf is not None:
                logger.info(f"Result GDF length: {len(result_gdf)}")

            if result_gdf is not None and len(result_gdf) > 0:
                return self._format_result(result_gdf)
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


    def _format_result(self, gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
        """Format GeoDataFrame as GeoJSON response"""
        # Convert to WGS84 for GeoJSON
        if gdf.crs and gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")

        # Filter out invalid geometries (None, empty, or with NaN bounds)
        gdf = gdf[gdf.geometry.is_valid].copy()

        if len(gdf) == 0:
            return {
                "success": True,
                "result_type": "geojson",
                "data": {"type": "FeatureCollection", "features": []},
                "metadata": {
                    "count": 0,
                    "crs": "EPSG:4326",
                    "bounds": [],
                    "message": "No valid geometries found"
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
            # Convert Decimal/object types that might contain Decimal
            elif gdf_copy[col].dtype == 'object':
                # Check if first non-null value is Decimal
                first_val = gdf_copy[col].dropna().iloc[0] if len(gdf_copy[col].dropna()) > 0 else None
                if first_val is not None and str(type(first_val).__name__) == 'Decimal':
                    gdf_copy[col] = gdf_copy[col].astype(float)
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
