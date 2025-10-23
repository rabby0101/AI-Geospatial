"""
Create Sample NDVI Data for Testing
Generates realistic NDVI rasters for Berlin (2018 and 2024)
"""

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from pathlib import Path

def create_sample_ndvi(output_path, base_ndvi=0.5, noise_level=0.15, seed=42):
    """
    Create a realistic sample NDVI raster

    Args:
        output_path: Path to save the raster
        base_ndvi: Base NDVI value (0.5 = moderate vegetation)
        noise_level: Amount of spatial variation
        seed: Random seed for reproducibility
    """
    np.random.seed(seed)

    # Berlin bounding box
    bbox = (13.088, 52.338, 13.761, 52.675)
    width = 200
    height = 200

    # Create spatial pattern (simulate urban/rural gradient)
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    X, Y = np.meshgrid(x, y)

    # Urban center (lower NDVI)
    urban_center_x, urban_center_y = 0.5, 0.5
    distance_from_center = np.sqrt((X - urban_center_x)**2 + (Y - urban_center_y)**2)

    # NDVI pattern: lower in center (urban), higher on edges (forest/parks)
    ndvi = base_ndvi + (distance_from_center * 0.3)

    # Add some parks (high NDVI patches in urban area)
    park_centers = [(0.3, 0.4), (0.6, 0.3), (0.5, 0.7)]
    for px, py in park_centers:
        park_distance = np.sqrt((X - px)**2 + (Y - py)**2)
        park_mask = park_distance < 0.1
        ndvi[park_mask] = 0.7 + np.random.rand() * 0.1

    # Add random noise for realism
    noise = np.random.randn(height, width) * noise_level
    ndvi = ndvi + noise

    # Clip to valid NDVI range [-1, 1]
    ndvi = np.clip(ndvi, -0.2, 0.9)

    # Create transform
    transform = from_bounds(*bbox, width, height)

    # Save raster
    profile = {
        'driver': 'GTiff',
        'height': height,
        'width': width,
        'count': 1,
        'dtype': rasterio.float32,
        'crs': 'EPSG:4326',
        'transform': transform,
        'compress': 'lzw',
        'nodata': -9999
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(output_path, 'w', **profile) as dst:
        dst.write(ndvi.astype(np.float32), 1)

    print(f"✅ Created {output_path}")
    print(f"   Shape: {ndvi.shape}")
    print(f"   NDVI range: [{ndvi.min():.3f}, {ndvi.max():.3f}]")
    print(f"   Mean NDVI: {ndvi.mean():.3f}")

    return ndvi


def main():
    """Create sample NDVI data for 2018 and 2024"""

    print("=" * 60)
    print("Creating Sample NDVI Data for Testing")
    print("=" * 60)

    data_dir = Path("data/raster/ndvi_timeseries")

    # Create 2018 NDVI (healthy vegetation)
    print("\n📊 Creating 2018 NDVI (baseline)...")
    ndvi_2018 = create_sample_ndvi(
        output_path=data_dir / "sample_ndvi_2018.tif",
        base_ndvi=0.55,  # Moderate-high vegetation
        noise_level=0.12,
        seed=42
    )

    # Create 2024 NDVI (some vegetation loss)
    print("\n📊 Creating 2024 NDVI (with some loss)...")
    ndvi_2024 = create_sample_ndvi(
        output_path=data_dir / "sample_ndvi_2024.tif",
        base_ndvi=0.48,  # Slightly lower (urban expansion)
        noise_level=0.12,
        seed=43  # Different seed for variation
    )

    # Calculate expected change
    diff = ndvi_2024 - ndvi_2018
    loss_pixels = np.sum(diff < -0.2)
    gain_pixels = np.sum(diff > 0.2)
    total_pixels = diff.size

    print("\n" + "=" * 60)
    print("📊 EXPECTED RESULTS")
    print("=" * 60)
    print(f"Total pixels: {total_pixels:,}")
    print(f"Vegetation loss pixels (NDVI < -0.2): {loss_pixels:,} ({loss_pixels/total_pixels*100:.1f}%)")
    print(f"Vegetation gain pixels (NDVI > 0.2): {gain_pixels:,} ({gain_pixels/total_pixels*100:.1f}%)")
    print(f"Mean NDVI change: {diff.mean():.3f}")
    print(f"Min NDVI change: {diff.min():.3f}")
    print(f"Max NDVI change: {diff.max():.3f}")

    print("\n✅ Sample data created successfully!")
    print("\n📁 Files created:")
    print(f"   - {data_dir / 'sample_ndvi_2018.tif'}")
    print(f"   - {data_dir / 'sample_ndvi_2024.tif'}")

    print("\n🧪 Next steps:")
    print("   1. Run: python examples/04_ndvi_change_detection.py")
    print("   2. Or test API: python -m uvicorn app.main:app --reload")
    print("=" * 60)


if __name__ == "__main__":
    main()
