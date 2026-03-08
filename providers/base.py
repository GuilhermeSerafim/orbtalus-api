"""
Base Provider Interface
Defines the contract for all data providers (MapBiomas, Nottus, etc.)
"""

from abc import ABC, abstractmethod
from typing import TypedDict, Optional


class SoilData(TypedDict):
    """Standardized soil data structure"""

    class_id: int
    class_name: str
    is_permeable: bool


class WaterData(TypedDict):
    """Standardized water frequency data structure"""

    frequency_years: int
    confidence: Optional[float]  # 0-1 confidence score


class DataProvider(ABC):
    """
    Abstract base class for all data providers.
    Ensures all adapters implement the same interface.
    """

    @abstractmethod
    def get_soil_data(self, lat: float, lon: float) -> SoilData:
        """
        Fetch soil classification data for coordinates.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees

        Returns:
            SoilData with classification and permeability

        Raises:
            Exception: If data cannot be retrieved
        """
        pass

    @abstractmethod
    def get_water_frequency(self, lat: float, lon: float) -> WaterData:
        """
        Fetch historical water frequency data for coordinates.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees

        Returns:
            WaterData with frequency (0-30 years)

        Raises:
            Exception: If data cannot be retrieved
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/debugging"""
        pass
