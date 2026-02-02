"""
Nottus Adapter - Placeholder for Future Integration
Implements the same interface as MapBiomas for easy swap.
"""

import logging
from typing import Optional

from .base import DataProvider, SoilData, WaterData

logger = logging.getLogger(__name__)


class NottusAdapter(DataProvider):
    """
    Placeholder adapter for Nottus data integration.
    Returns mock data matching the expected structure.
    Ready for drop-in replacement when Nottus API is available.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Nottus adapter.

        Args:
            api_key: Future API key for Nottus service
        """
        self.api_key = api_key
        logger.info("NottusAdapter initialized (PLACEHOLDER MODE)")

    @property
    def name(self) -> str:
        return "Nottus (Placeholder)"

    def get_soil_data(self, lat: float, lon: float) -> SoilData:
        """
        Placeholder for Nottus soil data.

        TODO: Replace with actual Nottus API call when available.
        """
        logger.debug(f"NottusAdapter: Mock soil data for ({lat}, {lon})")

        # Mock data based on coordinate parity (for testing variety)
        if int((lat * 1000) + (lon * 1000)) % 2 == 0:
            return {
                "class_id": 24,
                "class_name": "Área Urbanizada (Mock Nottus)",
                "is_permeable": False,
            }
        else:
            return {
                "class_id": 15,
                "class_name": "Pastagem (Mock Nottus)",
                "is_permeable": True,
            }

    def get_water_frequency(self, lat: float, lon: float) -> WaterData:
        """
        Placeholder for Nottus water frequency data.

        TODO: Replace with actual Nottus API call when available.
        """
        logger.debug(f"NottusAdapter: Mock water frequency for ({lat}, {lon})")

        # Mock frequency based on coordinates
        mock_frequency = int(abs((lat + lon) * 100) % 31)

        return {
            "frequency_years": mock_frequency,
            "confidence": 0.8,  # Mock confidence
        }
