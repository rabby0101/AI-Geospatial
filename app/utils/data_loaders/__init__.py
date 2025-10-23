"""
Data loaders for various geospatial data sources
"""

from .osm_loader import OSMLoader
from .sentinel_loader import SentinelLoader
from .dem_loader import DEMLoader
from .gadm_loader import GADMLoader
from .copernicus_loader import CopernicusLoader

__all__ = [
    'OSMLoader',
    'SentinelLoader',
    'DEMLoader',
    'GADMLoader',
    'CopernicusLoader'
]
