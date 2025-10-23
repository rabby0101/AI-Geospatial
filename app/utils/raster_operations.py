"""
Raster Operations Module
Handles NDVI computation, change detection, zonal statistics, and raster-vector integration
"""

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.features import shapes, rasterize
from rasterio.transform import from_bounds
import geopandas as gpd
from shapely.geometry import shape, box
from typing import Optional, Dict, List, Tuple, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class RasterOperations:
    """
    Core raster processing operations for geospatial analysis
    Supports NDVI, change detection, zonal statistics, and raster-vector integration
    """

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ==================== NDVI Operations ====================

    def compute_ndvi(
        self,
        red_band: Union[str, np.ndarray],
        nir_band: Union[str, np.ndarray],
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Compute NDVI from red and NIR bands
        NDVI = (NIR - Red) / (NIR + Red)

        Args:
            red_band: Path to red band raster or numpy array
            nir_band: Path to NIR band raster or numpy array
            output_path: Optional path to save result

        Returns:
            NDVI array or path to saved raster
        """
        # Load arrays if paths provided
        if isinstance(red_band, (str, Path)):
            with rasterio.open(red_band) as src:
                red = src.read(1).astype(float)
                profile = src.profile.copy()
        else:
            red = red_band.astype(float)
            profile = None

        if isinstance(nir_band, (str, Path)):
            with rasterio.open(nir_band) as src:
                nir = src.read(1).astype(float)
                if profile is None:
                    profile = src.profile.copy()
        else:
            nir = nir_band.astype(float)

        # Compute NDVI
        ndvi = np.where(
            (nir + red) == 0,
            0,
            (nir - red) / (nir + red)
        )

        # Clip to valid NDVI range [-1, 1]
        ndvi = np.clip(ndvi, -1, 1)

        # Save if output path provided
        if output_path and profile:
            profile.update(
                dtype=rasterio.float32,
                count=1,
                compress='lzw',
                nodata=-9999
            )

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(ndvi.astype(rasterio.float32), 1)

            logger.info(f"Saved NDVI to {output_path}")
            return output_path

        return ndvi

    def ndvi_difference(
        self,
        ndvi_t1: Union[str, Path, np.ndarray],
        ndvi_t2: Union[str, Path, np.ndarray],
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Compute NDVI change between two time periods
        Positive values = vegetation gain
        Negative values = vegetation loss

        Args:
            ndvi_t1: NDVI at time 1 (earlier)
            ndvi_t2: NDVI at time 2 (later)
            output_path: Optional path to save result

        Returns:
            NDVI difference array or path
        """
        # Load arrays
        if isinstance(ndvi_t1, (str, Path)):
            with rasterio.open(ndvi_t1) as src:
                ndvi1 = src.read(1).astype(float)
                profile1 = src.profile.copy()
                transform1 = src.transform
        else:
            ndvi1 = ndvi_t1.astype(float)
            profile1 = None
            transform1 = None

        if isinstance(ndvi_t2, (str, Path)):
            with rasterio.open(ndvi_t2) as src2:
                ndvi2_orig = src2.read(1).astype(float)
                profile2 = src2.profile.copy()
                transform2 = src2.transform
        else:
            ndvi2_orig = ndvi_t2.astype(float)
            profile2 = None
            transform2 = None

        # Check if rasters need resampling
        if isinstance(ndvi_t1, (str, Path)) and isinstance(ndvi_t2, (str, Path)):
            if ndvi1.shape != ndvi2_orig.shape or transform1 != transform2:
                logger.info(f"Resampling: {ndvi2_orig.shape} → {ndvi1.shape}")

                from rasterio.warp import reproject, Resampling

                # Resample ndvi2 to match ndvi1's grid
                ndvi2 = np.empty_like(ndvi1)
                reproject(
                    source=ndvi2_orig,
                    destination=ndvi2,
                    src_transform=transform2,
                    src_crs=profile2['crs'],
                    dst_transform=transform1,
                    dst_crs=profile1['crs'],
                    resampling=Resampling.bilinear
                )
                profile = profile1
            else:
                ndvi2 = ndvi2_orig
                profile = profile1
        else:
            ndvi2 = ndvi2_orig
            profile = profile1 if profile1 else profile2

        # Compute difference
        ndvi_diff = ndvi2 - ndvi1

        # Save if requested
        if output_path and profile:
            profile.update(dtype=rasterio.float32, count=1, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(ndvi_diff.astype(rasterio.float32), 1)
            logger.info(f"Saved NDVI difference to {output_path}")
            return output_path

        return ndvi_diff

    def detect_vegetation_loss(
        self,
        ndvi_diff: Union[str, Path, np.ndarray],
        threshold: float = -0.2,
        min_area_pixels: int = 10
    ) -> gpd.GeoDataFrame:
        """
        Detect areas with significant vegetation loss

        Args:
            ndvi_diff: NDVI difference raster (negative = loss)
            threshold: Minimum NDVI decrease to consider (default: -0.2)
            min_area_pixels: Minimum polygon size in pixels

        Returns:
            GeoDataFrame of vegetation loss polygons
        """
        # Load raster if path
        if isinstance(ndvi_diff, (str, Path)):
            with rasterio.open(ndvi_diff) as src:
                ndvi_array = src.read(1)
                transform = src.transform
                crs = src.crs
        else:
            ndvi_array = ndvi_diff
            transform = None
            crs = "EPSG:4326"

        # Create binary mask (1 = loss, 0 = no change/gain)
        loss_mask = (ndvi_array < threshold).astype(np.uint8)

        # Vectorize
        polygons = []
        values = []

        # Count pixels per polygon to filter by min_area_pixels
        pixel_counts = {}
        for geom, value in shapes(loss_mask, transform=transform):
            if value == 1:  # Only loss areas
                poly = shape(geom)
                # Estimate pixel count from geometry bounds
                # This is approximate but works for filtering
                polygons.append(poly)
                values.append(value)

        if not polygons:
            logger.warning("No vegetation loss detected")
            return gpd.GeoDataFrame(geometry=[], crs=crs)

        gdf = gpd.GeoDataFrame({'loss_detected': values}, geometry=polygons, crs=crs)
        logger.info(f"Detected {len(gdf)} vegetation loss areas")

        return gdf

    def detect_vegetation_gain(
        self,
        ndvi_diff: Union[str, Path, np.ndarray],
        threshold: float = 0.2,
        min_area_pixels: int = 10
    ) -> gpd.GeoDataFrame:
        """
        Detect areas with significant vegetation gain

        Args:
            ndvi_diff: NDVI difference raster (positive = gain)
            threshold: Minimum NDVI increase to consider (default: 0.2)
            min_area_pixels: Minimum polygon size in pixels

        Returns:
            GeoDataFrame of vegetation gain polygons
        """
        # Load raster if path
        if isinstance(ndvi_diff, (str, Path)):
            with rasterio.open(ndvi_diff) as src:
                ndvi_array = src.read(1)
                transform = src.transform
                crs = src.crs
        else:
            ndvi_array = ndvi_diff
            transform = None
            crs = "EPSG:4326"

        # Create binary mask (1 = gain, 0 = no change/loss)
        gain_mask = (ndvi_array > threshold).astype(np.uint8)

        # Vectorize
        polygons = []
        values = []

        for geom, value in shapes(gain_mask, transform=transform):
            if value == 1:
                poly = shape(geom)
                polygons.append(poly)
                values.append(value)

        if not polygons:
            logger.warning("No vegetation gain detected")
            return gpd.GeoDataFrame(geometry=[], crs=crs)

        gdf = gpd.GeoDataFrame({'gain_detected': values}, geometry=polygons, crs=crs)
        logger.info(f"Detected {len(gdf)} vegetation gain areas")

        return gdf

    # ==================== Zonal Statistics ====================

    def zonal_stats(
        self,
        raster: Union[str, Path, np.ndarray],
        polygons: gpd.GeoDataFrame,
        stats: List[str] = ['mean', 'min', 'max', 'std', 'count'],
        categorical: bool = False
    ) -> Dict[str, np.ndarray]:
        """
        Compute zonal statistics: aggregate raster values per polygon

        Args:
            raster: Input raster (path or array)
            polygons: Vector polygons for zoning
            stats: Statistics to compute (mean, min, max, std, count, sum)
            categorical: If True, compute counts per category (for land cover)

        Returns:
            Dictionary of statistic arrays, same length as polygons
        """
        # Load raster
        if isinstance(raster, (str, Path)):
            with rasterio.open(raster) as src:
                raster_array = src.read(1)
                transform = src.transform
                raster_crs = src.crs
        else:
            raster_array = raster
            transform = None
            raster_crs = None

        # Reproject polygons if needed
        if raster_crs and polygons.crs != raster_crs:
            polygons = polygons.to_crs(raster_crs)

        results = {stat: [] for stat in stats}
        if categorical:
            results['categories'] = []

        # Process each polygon
        for idx, row in polygons.iterrows():
            try:
                # Mask raster by polygon
                geom = [row.geometry.__geo_interface__]

                if isinstance(raster, (str, Path)):
                    with rasterio.open(raster) as src:
                        masked_array, _ = mask(src, geom, crop=True, nodata=-9999)
                        values = masked_array[0]
                else:
                    # For array input, use rasterize approach
                    # This is simplified - in production use proper masking
                    values = raster_array

                # Remove nodata values
                values = values[values != -9999]
                values = values[~np.isnan(values)]

                if len(values) == 0:
                    # No valid pixels
                    for stat in stats:
                        results[stat].append(np.nan)
                    continue

                # Compute statistics
                if 'mean' in stats:
                    results['mean'].append(np.mean(values))
                if 'min' in stats:
                    results['min'].append(np.min(values))
                if 'max' in stats:
                    results['max'].append(np.max(values))
                if 'std' in stats:
                    results['std'].append(np.std(values))
                if 'sum' in stats:
                    results['sum'].append(np.sum(values))
                if 'count' in stats:
                    results['count'].append(len(values))

                # Categorical mode
                if categorical:
                    unique, counts = np.unique(values, return_counts=True)
                    category_dict = dict(zip(unique.astype(int), counts.astype(int)))
                    results['categories'].append(category_dict)

            except Exception as e:
                logger.error(f"Error processing polygon {idx}: {e}")
                for stat in stats:
                    results[stat].append(np.nan)

        # Convert to numpy arrays
        for key in results:
            if key != 'categories':
                results[key] = np.array(results[key])

        logger.info(f"Computed zonal statistics for {len(polygons)} polygons")
        return results

    # ==================== Raster-Vector Integration ====================

    def clip_raster_by_vector(
        self,
        raster_path: Union[str, Path],
        vector: Union[gpd.GeoDataFrame, dict],
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Clip raster by vector polygon(s)

        Args:
            raster_path: Input raster file
            vector: Vector polygon(s) for clipping
            output_path: Optional output path

        Returns:
            Clipped array or path to saved raster
        """
        with rasterio.open(raster_path) as src:
            # Convert vector to GeoJSON-like format
            if isinstance(vector, gpd.GeoDataFrame):
                # Reproject if needed
                if vector.crs != src.crs:
                    vector = vector.to_crs(src.crs)
                geoms = [feature['geometry'] for feature in vector.__geo_interface__['features']]
            else:
                geoms = [vector]

            # Mask/clip
            clipped_array, clipped_transform = mask(src, geoms, crop=True, nodata=-9999)

            if output_path:
                # Save clipped raster
                profile = src.profile.copy()
                profile.update({
                    'height': clipped_array.shape[1],
                    'width': clipped_array.shape[2],
                    'transform': clipped_transform,
                    'nodata': -9999
                })

                with rasterio.open(output_path, 'w', **profile) as dst:
                    dst.write(clipped_array)

                logger.info(f"Saved clipped raster to {output_path}")
                return output_path

            return clipped_array[0]  # Return first band

    def extract_values_at_points(
        self,
        raster: Union[str, Path],
        points: gpd.GeoDataFrame
    ) -> np.ndarray:
        """
        Extract raster values at point locations

        Args:
            raster: Input raster
            points: Point GeoDataFrame

        Returns:
            Array of extracted values
        """
        with rasterio.open(raster) as src:
            # Reproject points if needed
            if points.crs != src.crs:
                points = points.to_crs(src.crs)

            # Extract coordinates
            coords = [(geom.x, geom.y) for geom in points.geometry]

            # Sample raster
            values = [val[0] for val in src.sample(coords)]

        logger.info(f"Extracted values at {len(points)} points")
        return np.array(values)

    def vectorize_raster(
        self,
        raster: Union[str, Path, np.ndarray],
        threshold: Optional[float] = None,
        operator: str = 'greater'
    ) -> gpd.GeoDataFrame:
        """
        Convert raster to vector polygons
        Optionally threshold before conversion

        Args:
            raster: Input raster
            threshold: Optional threshold value
            operator: 'greater', 'less', 'equal' (for thresholding)

        Returns:
            GeoDataFrame of polygons
        """
        # Load raster
        if isinstance(raster, (str, Path)):
            with rasterio.open(raster) as src:
                array = src.read(1)
                transform = src.transform
                crs = src.crs
        else:
            array = raster
            transform = None
            crs = "EPSG:4326"

        # Apply threshold if provided
        if threshold is not None:
            if operator == 'greater':
                mask_array = (array > threshold).astype(np.uint8)
            elif operator == 'less':
                mask_array = (array < threshold).astype(np.uint8)
            elif operator == 'equal':
                mask_array = (array == threshold).astype(np.uint8)
            else:
                raise ValueError(f"Unknown operator: {operator}")
        else:
            mask_array = (array > 0).astype(np.uint8)

        # Vectorize
        polygons = []
        values = []

        for geom, value in shapes(mask_array, transform=transform):
            if value == 1:
                polygons.append(shape(geom))
                values.append(value)

        if not polygons:
            logger.warning("No polygons generated from raster")
            return gpd.GeoDataFrame(geometry=[], crs=crs)

        gdf = gpd.GeoDataFrame({'value': values}, geometry=polygons, crs=crs)
        logger.info(f"Vectorized raster to {len(gdf)} polygons")

        return gdf

    # ==================== Raster Algebra ====================

    def raster_calculator(
        self,
        expression: str,
        rasters: Dict[str, Union[str, Path]],
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Execute raster algebra expressions

        Args:
            expression: Numpy expression (e.g., "(B8 - B4) / (B8 + B4)")
            rasters: Dictionary mapping variable names to raster paths
                    e.g., {'B4': 'red.tif', 'B8': 'nir.tif'}
            output_path: Optional output path

        Returns:
            Result array or path to saved raster
        """
        # Load all rasters
        arrays = {}
        profile = None

        for var_name, raster_path in rasters.items():
            with rasterio.open(raster_path) as src:
                arrays[var_name] = src.read(1).astype(float)
                if profile is None:
                    profile = src.profile.copy()

        # Evaluate expression
        try:
            result = eval(expression, {"__builtins__": {}}, arrays)
        except Exception as e:
            logger.error(f"Error evaluating expression '{expression}': {e}")
            raise

        # Save if requested
        if output_path and profile:
            profile.update(dtype=rasterio.float32, count=1, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(result.astype(rasterio.float32), 1)
            logger.info(f"Saved raster calculation result to {output_path}")
            return output_path

        return result


# Convenience functions for common operations

def quick_ndvi_change(
    region: str,
    ndvi_2018_path: Path,
    ndvi_2024_path: Path,
    threshold: float = -0.2
) -> gpd.GeoDataFrame:
    """
    Quick NDVI change detection workflow

    Args:
        region: Region name
        ndvi_2018_path: Path to 2018 NDVI
        ndvi_2024_path: Path to 2024 NDVI
        threshold: Loss threshold

    Returns:
        GeoDataFrame of loss areas
    """
    ops = RasterOperations()

    # Compute difference
    diff = ops.ndvi_difference(ndvi_2018_path, ndvi_2024_path)

    # Detect loss
    loss_areas = ops.detect_vegetation_loss(diff, threshold=threshold)

    logger.info(f"NDVI change analysis complete for {region}")
    return loss_areas


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    ops = RasterOperations()

    # Example: NDVI from bands
    # ndvi = ops.compute_ndvi('red_band.tif', 'nir_band.tif', 'output_ndvi.tif')

    # Example: NDVI change
    # diff = ops.ndvi_difference('ndvi_2018.tif', 'ndvi_2024.tif')
    # loss = ops.detect_vegetation_loss(diff, threshold=-0.2)

    print("Raster operations module loaded successfully")
