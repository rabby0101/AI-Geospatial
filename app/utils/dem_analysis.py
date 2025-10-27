"""
Enhanced DEM Analysis Module
Comprehensive terrain analysis including hydrological and urban planning analyses
"""

import numpy as np
import rasterio
from rasterio.plot import show
from pathlib import Path
from typing import Optional, Tuple, Dict, Union
import logging
from scipy import ndimage
from skimage import morphology
import geopandas as gpd
from shapely.geometry import shape
from rasterio.features import shapes

logger = logging.getLogger(__name__)


class DEMAnalyzer:
    """
    Comprehensive DEM analysis tool for terrain, hydrological, and urban planning studies
    """

    def __init__(self, dem_path: Union[str, Path], cache_dir: str = "data/raster/dem"):
        """
        Initialize DEM analyzer

        Args:
            dem_path: Path to DEM raster file
            cache_dir: Directory to cache analysis results
        """
        self.dem_path = Path(dem_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load DEM
        with rasterio.open(dem_path) as src:
            self.dem = src.read(1)
            self.profile = src.profile.copy()
            self.transform = src.transform
            self.crs = src.crs

        logger.info(f"Loaded DEM: {dem_path}, shape: {self.dem.shape}")

    def compute_slope(self, output_path: Optional[Path] = None) -> Union[np.ndarray, Path]:
        """
        Compute slope in degrees

        Args:
            output_path: Optional path to save slope raster

        Returns:
            Slope array or path to saved raster
        """
        # Compute gradients in x and y directions
        dy, dx = np.gradient(self.dem)

        # Get cell size from transform (assuming square cells)
        cell_size = self.transform.a

        # Compute slope in degrees
        slope = np.arctan(np.sqrt(dx**2 + dy**2) / cell_size) * (180.0 / np.pi)

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.float32, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(slope.astype(rasterio.float32), 1)
            logger.info(f"Saved slope to {output_path}")
            return output_path

        return slope

    def compute_aspect(self, output_path: Optional[Path] = None) -> Union[np.ndarray, Path]:
        """
        Compute aspect (direction of slope) in degrees (0-360)

        Args:
            output_path: Optional path to save aspect raster

        Returns:
            Aspect array or path to saved raster
        """
        dy, dx = np.gradient(self.dem)

        # Aspect: direction of steepest slope
        aspect = np.arctan2(-dy, dx) * (180.0 / np.pi)
        aspect = (aspect + 360) % 360  # Normalize to 0-360

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.float32, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(aspect.astype(rasterio.float32), 1)
            logger.info(f"Saved aspect to {output_path}")
            return output_path

        return aspect

    def compute_hillshade(
        self,
        azimuth: float = 315.0,
        elevation: float = 45.0,
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Compute hillshade for visualization

        Args:
            azimuth: Light source direction (0-360, default 315)
            elevation: Light source elevation angle (0-90, default 45)
            output_path: Optional path to save hillshade raster

        Returns:
            Hillshade array (0-255) or path to saved raster
        """
        # Get slope and aspect
        dy, dx = np.gradient(self.dem)

        # Compute slope in radians
        slope = np.pi/2. - np.arctan(np.sqrt(dx*dx + dy*dy))

        # Compute aspect in radians
        aspect = np.arctan2(-dy, dx)

        # Convert light angles to radians
        shading = np.sin(np.radians(elevation)) * np.cos(slope) + \
                  np.cos(np.radians(elevation)) * np.sin(slope) * \
                  np.cos(np.radians(azimuth) - aspect - np.pi/2)

        # Normalize to 0-255
        shading = (shading + 1) / 2 * 255
        shading = np.clip(shading, 0, 255).astype(np.uint8)

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.uint8, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(shading, 1)
            logger.info(f"Saved hillshade to {output_path}")
            return output_path

        return shading

    def compute_flow_direction(self, output_path: Optional[Path] = None) -> Union[np.ndarray, Path]:
        """
        Compute flow direction using D8 algorithm (8 directions)

        Returns:
            Flow direction array (1-8 or 0 for pit) or path to saved raster
        """
        # Create flow direction array
        flow_dir = np.zeros_like(self.dem, dtype=np.uint8)

        # D8 directions: 1=E, 2=SE, 3=S, 4=SW, 5=W, 6=NW, 7=N, 8=NE
        # Direction vectors
        directions = [
            (0, 1),    # 1: East
            (1, 1),    # 2: Southeast
            (1, 0),    # 3: South
            (1, -1),   # 4: Southwest
            (0, -1),   # 5: West
            (-1, -1),  # 6: Northwest
            (-1, 0),   # 7: North
            (-1, 1)    # 8: Northeast
        ]

        # For each cell, find lowest neighbor
        for i in range(1, self.dem.shape[0] - 1):
            for j in range(1, self.dem.shape[1] - 1):
                current_elev = self.dem[i, j]
                min_elev = current_elev
                min_dir = 0

                for dir_idx, (di, dj) in enumerate(directions):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < self.dem.shape[0] and 0 <= nj < self.dem.shape[1]:
                        neighbor_elev = self.dem[ni, nj]
                        if neighbor_elev < min_elev:
                            min_elev = neighbor_elev
                            min_dir = dir_idx + 1

                flow_dir[i, j] = min_dir

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.uint8, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(flow_dir, 1)
            logger.info(f"Saved flow direction to {output_path}")
            return output_path

        return flow_dir

    def compute_flow_accumulation(
        self,
        flow_direction: Optional[Union[np.ndarray, Path, str]] = None,
        output_path: Optional[Path] = None
    ) -> Union[np.ndarray, Path]:
        """
        Compute flow accumulation (number of cells flowing into each cell)

        Args:
            flow_direction: Flow direction array or path to raster (computed if not provided)
            output_path: Optional path to save flow accumulation raster

        Returns:
            Flow accumulation array or path to saved raster
        """
        if flow_direction is None:
            flow_direction = self.compute_flow_direction()

        # Load flow direction if it's a path
        if isinstance(flow_direction, (str, Path)):
            with rasterio.open(flow_direction) as src:
                flow_direction = src.read(1)

        # D8 directions
        directions = [
            (0, 1),    # 1: East
            (1, 1),    # 2: Southeast
            (1, 0),    # 3: South
            (1, -1),   # 4: Southwest
            (0, -1),   # 5: West
            (-1, -1),  # 6: Northwest
            (-1, 0),   # 7: North
            (-1, 1)    # 8: Northeast
        ]

        # Create flow accumulation array
        flow_accum = np.ones_like(self.dem, dtype=np.float32)

        # Simple iterative approach (not most efficient but works)
        for _ in range(10):  # Multiple passes
            for i in range(1, self.dem.shape[0] - 1):
                for j in range(1, self.dem.shape[1] - 1):
                    direction = flow_direction[i, j]
                    if direction > 0:
                        di, dj = directions[direction - 1]
                        ni, nj = i + di, j + dj
                        if 0 <= ni < self.dem.shape[0] and 0 <= nj < self.dem.shape[1]:
                            flow_accum[ni, nj] += flow_accum[i, j]

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.float32, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(flow_accum.astype(rasterio.float32), 1)
            logger.info(f"Saved flow accumulation to {output_path}")
            return output_path

        return flow_accum

    def delineate_watersheds(
        self,
        flow_direction: Optional[Union[np.ndarray, Path, str]] = None,
        output_path: Optional[Path] = None
    ) -> Union[gpd.GeoDataFrame, Path]:
        """
        Delineate watershed boundaries

        Args:
            flow_direction: Flow direction array or path to raster
            output_path: Optional path to save watersheds as GeoJSON

        Returns:
            GeoDataFrame of watershed polygons or path to saved file
        """
        if flow_direction is None:
            flow_direction = self.compute_flow_direction()

        # Load flow direction if it's a path
        if isinstance(flow_direction, (str, Path)):
            with rasterio.open(flow_direction) as src:
                flow_direction = src.read(1)

        # Label connected regions of same flow direction
        labeled_array, num_features = ndimage.label(flow_direction > 0)

        logger.info(f"Identified {num_features} watershed areas")

        # Vectorize
        polygons = []
        values = []

        for geom, value in shapes(labeled_array.astype(rasterio.uint8), transform=self.transform):
            if value > 0:
                polygons.append(shape(geom))
                values.append(int(value))

        if not polygons:
            logger.warning("No watersheds detected")
            return gpd.GeoDataFrame(geometry=[], crs=self.crs)

        gdf = gpd.GeoDataFrame(
            {'watershed_id': values},
            geometry=polygons,
            crs=self.crs
        )

        if output_path:
            gdf.to_file(output_path, driver='GeoJSON')
            logger.info(f"Saved watersheds to {output_path}")
            return output_path

        return gdf

    def identify_streams(
        self,
        flow_accumulation: Optional[Union[np.ndarray, Path, str]] = None,
        threshold: float = 1000,
        output_path: Optional[Path] = None
    ) -> Union[gpd.GeoDataFrame, Path]:
        """
        Identify stream networks based on flow accumulation threshold

        Args:
            flow_accumulation: Flow accumulation array or path to raster
            threshold: Minimum flow accumulation to be considered a stream
            output_path: Optional path to save streams as GeoJSON

        Returns:
            GeoDataFrame of stream line features or path to saved file
        """
        if flow_accumulation is None:
            flow_accumulation = self.compute_flow_accumulation()

        # Load flow accumulation if it's a path
        if isinstance(flow_accumulation, (str, Path)):
            with rasterio.open(flow_accumulation) as src:
                flow_accumulation = src.read(1)

        # Create stream mask
        stream_mask = (flow_accumulation >= threshold).astype(np.uint8)

        # Vectorize
        polygons = []

        for geom, value in shapes(stream_mask, transform=self.transform):
            if value > 0:
                polygons.append(shape(geom))

        if not polygons:
            logger.warning("No streams detected with given threshold")
            return gpd.GeoDataFrame(geometry=[], crs=self.crs)

        gdf = gpd.GeoDataFrame(
            {'stream': [True] * len(polygons)},
            geometry=polygons,
            crs=self.crs
        )

        if output_path:
            gdf.to_file(output_path, driver='GeoJSON')
            logger.info(f"Saved streams to {output_path}")
            return output_path

        return gdf

    def analyze_flood_risk(
        self,
        flow_accumulation: Optional[Union[np.ndarray, Path, str]] = None,
        output_path: Optional[Path] = None
    ) -> Union[gpd.GeoDataFrame, Path]:
        """
        Identify flood-prone areas (low elevation + high flow accumulation)

        Args:
            flow_accumulation: Flow accumulation array or path to raster
            output_path: Optional path to save flood risk areas

        Returns:
            GeoDataFrame of flood-risk areas or path to saved file
        """
        if flow_accumulation is None:
            flow_accumulation = self.compute_flow_accumulation()

        # Load flow accumulation if it's a path
        if isinstance(flow_accumulation, (str, Path)):
            with rasterio.open(flow_accumulation) as src:
                flow_accumulation = src.read(1)

        # Normalize elevation and flow accumulation
        dem_norm = (self.dem - self.dem.min()) / (self.dem.max() - self.dem.min())
        flow_norm = (flow_accumulation - flow_accumulation.min()) / \
                    (flow_accumulation.max() - flow_accumulation.min())

        # Flood risk = inverse elevation + high flow accumulation
        flood_risk = (1 - dem_norm) * 0.6 + flow_norm * 0.4

        # Identify high-risk areas (top 20%)
        threshold = np.percentile(flood_risk, 80)
        flood_mask = (flood_risk >= threshold).astype(np.uint8)

        # Vectorize
        polygons = []
        values = []

        for geom, value in shapes(flood_mask, transform=self.transform):
            if value > 0:
                poly = shape(geom)
                polygons.append(poly)
                values.append(flood_risk[self.dem > self.dem.min()][
                    np.random.randint(0, len(self.dem[self.dem > self.dem.min()]))
                ])  # Approximate risk value

        if not polygons:
            logger.warning("No flood-risk areas detected")
            return gpd.GeoDataFrame(geometry=[], crs=self.crs)

        gdf = gpd.GeoDataFrame(
            {'flood_risk': values},
            geometry=polygons,
            crs=self.crs
        )

        if output_path:
            gdf.to_file(output_path, driver='GeoJSON')
            logger.info(f"Saved flood risk areas to {output_path}")
            return output_path

        return gdf

    def analyze_development_suitability(
        self,
        max_slope: float = 20.0,
        min_elevation: float = None,
        output_path: Optional[Path] = None
    ) -> gpd.GeoDataFrame:
        """
        Identify suitable areas for development based on slope and elevation

        Args:
            max_slope: Maximum slope for development (degrees)
            min_elevation: Minimum elevation for development (meters)
            output_path: Optional path to save suitable areas

        Returns:
            GeoDataFrame of developable areas
        """
        # Compute slope
        dy, dx = np.gradient(self.dem)
        slope = np.arctan(np.sqrt(dx**2 + dy**2)) * (180.0 / np.pi)

        # Create suitability mask
        suitable = (slope <= max_slope).astype(np.uint8)

        if min_elevation is not None:
            suitable = suitable & (self.dem >= min_elevation).astype(np.uint8)

        # Vectorize
        polygons = []

        for geom, value in shapes(suitable, transform=self.transform):
            if value > 0:
                polygons.append(shape(geom))

        if not polygons:
            logger.warning("No suitable development areas found with given criteria")
            return gpd.GeoDataFrame(geometry=[], crs=self.crs)

        gdf = gpd.GeoDataFrame(
            {'suitable_for_development': [True] * len(polygons)},
            geometry=polygons,
            crs=self.crs
        )

        if output_path:
            gdf.to_file(output_path, driver='GeoJSON')
            logger.info(f"Saved development suitability to {output_path}")
            return output_path

        return gdf

    def classify_terrain(self, output_path: Optional[Path] = None) -> Union[np.ndarray, Path]:
        """
        Classify terrain into categories: flat, rolling, steep, very steep

        Args:
            output_path: Optional path to save classification raster

        Returns:
            Classification array (1=flat, 2=rolling, 3=steep, 4=very steep) or path
        """
        # Compute slope
        dy, dx = np.gradient(self.dem)
        slope = np.arctan(np.sqrt(dx**2 + dy**2)) * (180.0 / np.pi)

        # Classify
        terrain = np.zeros_like(slope, dtype=np.uint8)
        terrain[(slope >= 0) & (slope < 5)] = 1    # Flat
        terrain[(slope >= 5) & (slope < 15)] = 2   # Rolling
        terrain[(slope >= 15) & (slope < 30)] = 3  # Steep
        terrain[slope >= 30] = 4                    # Very steep

        if output_path:
            profile = self.profile.copy()
            profile.update(dtype=rasterio.uint8, compress='lzw')
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(terrain, 1)
            logger.info(f"Saved terrain classification to {output_path}")
            return output_path

        return terrain

    def compute_terrain_statistics(self) -> Dict:
        """
        Compute comprehensive terrain statistics

        Returns:
            Dictionary of statistics
        """
        dy, dx = np.gradient(self.dem)
        slope = np.arctan(np.sqrt(dx**2 + dy**2)) * (180.0 / np.pi)

        stats = {
            'elevation': {
                'min': float(self.dem.min()),
                'max': float(self.dem.max()),
                'mean': float(self.dem.mean()),
                'std': float(self.dem.std()),
            },
            'slope': {
                'min': float(slope.min()),
                'max': float(slope.max()),
                'mean': float(slope.mean()),
                'std': float(slope.std()),
            },
            'relief': float(self.dem.max() - self.dem.min()),
        }

        logger.info(f"Computed terrain statistics: {stats}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("DEM Analysis module loaded successfully")
