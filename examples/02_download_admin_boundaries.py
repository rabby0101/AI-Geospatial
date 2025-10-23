"""
Example 2: Download administrative boundaries from GADM

Free and open-source country boundaries
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.data_loaders import GADMLoader
import logging

logging.basicConfig(level=logging.INFO)


def main():
    """Download administrative boundaries for multiple countries"""

    loader = GADMLoader(data_dir="data/vector/gadm")

    countries = {
        'Germany': 'DEU',
        'France': 'FRA',
        'United Kingdom': 'GBR',
        'Italy': 'ITA',
        'Spain': 'ESP'
    }

    print("=" * 60)
    print("Downloading GADM Administrative Boundaries")
    print("=" * 60)

    for country_name, country_code in countries.items():
        print(f"\n{country_name} ({country_code})")
        print("-" * 40)

        # Download country boundaries (admin level 0)
        print("  Level 0 (Country outline)...", end=" ")
        gdf0 = loader.load_boundaries(country_code, admin_level=0)
        print(f"✓ ({len(gdf0)} feature)")

        # Download state/province boundaries (admin level 1)
        print("  Level 1 (States/Provinces)...", end=" ")
        gdf1 = loader.load_boundaries(country_code, admin_level=1)
        print(f"✓ ({len(gdf1)} features)")

        # Show sample
        if 'NAME_1' in gdf1.columns:
            print(f"  Sample regions: {', '.join(gdf1['NAME_1'].head(3).tolist())}")

    print("\n" + "=" * 60)
    print("Download completed!")
    print("=" * 60)

    # Example: Load Germany and explore
    print("\nExploring Germany administrative data:")
    print("-" * 40)

    germany = loader.load_boundaries('DEU', admin_level=1)

    print(f"Number of states: {len(germany)}")
    print(f"\nColumns: {list(germany.columns)}")

    print("\nGerman states:")
    for idx, row in germany.iterrows():
        name = row.get('NAME_1', 'Unknown')
        print(f"  - {name}")

    # Calculate area of each state
    # Convert to equal-area projection for accurate area calculation
    germany_aea = germany.to_crs('EPSG:3035')  # ETRS89 LAEA
    germany['area_km2'] = germany_aea.geometry.area / 1_000_000

    print("\nLargest German states by area:")
    top_states = germany.nlargest(5, 'area_km2')[['NAME_1', 'area_km2']]
    for idx, row in top_states.iterrows():
        print(f"  {row['NAME_1']}: {row['area_km2']:,.0f} km²")


if __name__ == "__main__":
    main()
