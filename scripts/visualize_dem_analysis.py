#!/usr/bin/env python3
"""
Visualization Script for DEM Analysis Results
Creates maps and charts for all analyses
"""

import logging
import sys
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import numpy as np
import rasterio
import geopandas as gpd
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def plot_raster(raster_path, title, output_path, cmap='viridis', vmin=None, vmax=None):
    """Plot and save a raster as an image"""
    with rasterio.open(raster_path) as src:
        data = src.read(1)

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title, fontsize=14, fontweight='bold')
    cbar = plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"✓ Saved visualization to {output_path}")


def plot_vector(vector_path, title, output_path):
    """Plot and save vector features"""
    gdf = gpd.read_file(vector_path)

    fig, ax = plt.subplots(figsize=(12, 10))
    gdf.plot(ax=ax, alpha=0.7, edgecolor='k')
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"✓ Saved visualization to {output_path}")


def create_visualizations():
    """Create all visualizations"""

    analysis_dir = Path("data/raster/dem/analysis_results")
    viz_dir = analysis_dir / "visualizations"
    viz_dir.mkdir(exist_ok=True)

    logger.info("=" * 80)
    logger.info("CREATING DEM ANALYSIS VISUALIZATIONS")
    logger.info("=" * 80)

    visualizations = [
        # Terrain
        ("berlin_slope.tif", "Terrain Slope (degrees)", "slope_map.png", 'YlOrRd'),
        ("berlin_aspect.tif", "Terrain Aspect (0-360°)", "aspect_map.png", 'hsv'),
        ("berlin_hillshade.tif", "Hillshade (3D Visualization)", "hillshade_map.png", 'gray'),
        ("berlin_terrain_classification.tif", "Terrain Classification", "terrain_classification.png", 'tab10'),
        # Hydrological
        ("berlin_flow_direction.tif", "Flow Direction (D8)", "flow_direction_map.png", 'tab20'),
        ("berlin_flow_accumulation.tif", "Flow Accumulation", "flow_accumulation_map.png", 'Blues'),
    ]

    logger.info("\nGenerating raster visualizations...")
    for raster_file, title, output_file, cmap in visualizations:
        raster_path = analysis_dir / raster_file
        if raster_path.exists():
            output_path = viz_dir / output_file
            try:
                plot_raster(raster_path, title, output_path, cmap=cmap)
            except Exception as e:
                logger.warning(f"Failed to visualize {raster_file}: {e}")
        else:
            logger.warning(f"File not found: {raster_path}")

    # Vector features
    vector_features = [
        ("berlin_streams.geojson", "Stream Networks", "streams_map.png"),
        ("berlin_watersheds.geojson", "Watersheds", "watersheds_map.png"),
        ("berlin_flood_risk.geojson", "Flood Risk Areas", "flood_risk_map.png"),
        ("berlin_development_suitability.geojson", "Development Suitability", "development_suitability_map.png"),
    ]

    logger.info("\nGenerating vector visualizations...")
    for vector_file, title, output_file in vector_features:
        vector_path = analysis_dir / vector_file
        if vector_path.exists():
            output_path = viz_dir / output_file
            try:
                plot_vector(vector_path, title, output_path)
            except Exception as e:
                logger.warning(f"Failed to visualize {vector_file}: {e}")
        else:
            logger.warning(f"File not found: {vector_path}")

    # Create combined overview map
    logger.info("\nCreating combined overview map...")
    try:
        fig, axes = plt.subplots(2, 2, figsize=(16, 14))

        # Plot slope
        with rasterio.open(analysis_dir / "berlin_slope.tif") as src:
            slope = src.read(1)
        axes[0, 0].imshow(slope, cmap='YlOrRd')
        axes[0, 0].set_title('Terrain Slope', fontweight='bold')
        axes[0, 0].axis('off')

        # Plot aspect
        with rasterio.open(analysis_dir / "berlin_aspect.tif") as src:
            aspect = src.read(1)
        axes[0, 1].imshow(aspect, cmap='hsv')
        axes[0, 1].set_title('Terrain Aspect', fontweight='bold')
        axes[0, 1].axis('off')

        # Plot hillshade
        with rasterio.open(analysis_dir / "berlin_hillshade.tif") as src:
            hillshade = src.read(1)
        axes[1, 0].imshow(hillshade, cmap='gray')
        axes[1, 0].set_title('Hillshade', fontweight='bold')
        axes[1, 0].axis('off')

        # Plot flow accumulation
        with rasterio.open(analysis_dir / "berlin_flow_accumulation.tif") as src:
            flow_accum = src.read(1)
        im = axes[1, 1].imshow(np.log(flow_accum + 1), cmap='Blues')
        axes[1, 1].set_title('Flow Accumulation (log scale)', fontweight='bold')
        axes[1, 1].axis('off')

        plt.suptitle('Berlin DEM Analysis Overview', fontsize=16, fontweight='bold', y=0.995)
        plt.tight_layout()
        plt.savefig(viz_dir / "overview_map.png", dpi=150, bbox_inches='tight')
        plt.close()
        logger.info(f"✓ Saved overview map to {viz_dir / 'overview_map.png'}")
    except Exception as e:
        logger.warning(f"Failed to create overview map: {e}")

    logger.info("\n" + "=" * 80)
    logger.info(f"All visualizations saved to: {viz_dir}")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        create_visualizations()
        logger.info("\nVisualization complete!")
    except Exception as e:
        logger.error(f"Visualization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
