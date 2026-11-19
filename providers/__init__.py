"""
Data Provider Package
Implements the Adapter Pattern for data source abstraction.
"""

from .base import DataProvider, SoilData, WaterData
from .mapbiomas_adapter import MapBiomasAdapter

__all__ = ["DataProvider", "SoilData", "WaterData", "MapBiomasAdapter"]
