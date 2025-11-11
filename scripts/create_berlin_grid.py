#!/usr/bin/env python3
"""
Divide Berlin into a 4x4 grid for sequential OverpassAPI queries.
This helps avoid timeout issues and ensures complete coverage.
"""

import json
from pathlib import Path

# Berlin bounding box (approximate)
# Taken from OpenStreetMap administrative boundaries
BERLIN_BBOX = {
    "south": 52.338,
    "north": 52.676,
    "west": 13.088,
    "east": 13.761
}

def create_4x4_grid():
    """
    Divide Berlin into a 4x4 grid (16 cells).
    Returns list of dicts with grid cell coordinates.
    """

    # Calculate cell dimensions
    lat_range = BERLIN_BBOX["north"] - BERLIN_BBOX["south"]
    lon_range = BERLIN_BBOX["east"] - BERLIN_BBOX["west"]

    cell_lat = lat_range / 4
    cell_lon = lon_range / 4

    grid_cells = []
    cell_id = 1

    # Create 4x4 grid (iterate south to north, west to east)
    for row in range(4):
        for col in range(4):
            south = BERLIN_BBOX["south"] + (row * cell_lat)
            north = south + cell_lat
            west = BERLIN_BBOX["west"] + (col * cell_lon)
            east = west + cell_lon

            grid_cells.append({
                "id": cell_id,
                "row": row,
                "col": col,
                "south": round(south, 6),
                "north": round(north, 6),
                "west": round(west, 6),
                "east": round(east, 6),
                "bbox_string": f"{round(south, 6)},{round(west, 6)},{round(north, 6)},{round(east, 6)}"  # Overpass format: south,west,north,east
            })
            cell_id += 1

    return grid_cells


def save_grid_config(grid_cells, output_file="data/grid_config.json"):
    """Save grid configuration to JSON file."""
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump({
            "berlin_bbox": BERLIN_BBOX,
            "grid_type": "4x4",
            "total_cells": len(grid_cells),
            "cells": grid_cells
        }, f, indent=2)

    print(f"✅ Grid configuration saved to {output_file}")


def print_grid_info(grid_cells):
    """Print grid information."""
    print("\n" + "="*80)
    print("BERLIN 4x4 GRID CONFIGURATION")
    print("="*80)

    print(f"\n📍 Total Berlin Bbox:")
    print(f"   South: {BERLIN_BBOX['south']}, North: {BERLIN_BBOX['north']}")
    print(f"   West:  {BERLIN_BBOX['west']}, East:  {BERLIN_BBOX['east']}")

    print(f"\n📊 Grid Details:")
    print(f"   Grid Type: 4x4 (16 cells)")
    print(f"   Lat Range: {BERLIN_BBOX['north'] - BERLIN_BBOX['south']:.4f}°")
    print(f"   Lon Range: {BERLIN_BBOX['east'] - BERLIN_BBOX['west']:.4f}°")

    print(f"\n📍 Grid Cells (OverpassAPI bbox format: south,west,north,east):")
    print(f"\n{'ID':<4} {'Row':<4} {'Col':<4} {'BBox String':<50}")
    print("-" * 80)

    for cell in grid_cells:
        print(f"{cell['id']:<4} {cell['row']:<4} {cell['col']:<4} {cell['bbox_string']:<50}")

    print("\n" + "="*80)


if __name__ == "__main__":
    # Create grid
    grid_cells = create_4x4_grid()

    # Save configuration
    save_grid_config(grid_cells)

    # Print information
    print_grid_info(grid_cells)

    print("\n✅ Berlin grid created successfully!")
    print("   Use data/grid_config.json in download_buildings_overpass_grid.py")
