"""
MapBiomas Adapter - Google Earth Engine Integration
Implements real data fetching from MapBiomas Collections via GEE.
"""

import ee
from typing import Optional
import logging

from .base import DataProvider, SoilData, WaterData

logger = logging.getLogger(__name__)


# MapBiomas Collection 8 - Land Cover Classification
# Key classes for flood risk assessment
MAPBIOMAS_SOIL_CLASSES = {
    # Urban and impermeable
    24: {"name": "Área Urbanizada", "is_permeable": False},
    30: {"name": "Mineração", "is_permeable": False},
    25: {"name": "Outras Áreas não Vegetadas", "is_permeable": False},
    # Semi-permeable
    15: {"name": "Pastagem", "is_permeable": True},
    21: {"name": "Mosaico de Agricultura e Pastagem", "is_permeable": True},
    # Permeable natural
    3: {"name": "Formação Florestal", "is_permeable": True},
    4: {"name": "Formação Savânica", "is_permeable": True},
    5: {"name": "Mangue", "is_permeable": True},
    11: {"name": "Campo Alagado", "is_permeable": True},
    12: {"name": "Formação Campestre", "is_permeable": True},
    32: {"name": "Apicum", "is_permeable": True},
    # Agriculture (semi-permeable)
    39: {"name": "Soja", "is_permeable": True},
    20: {"name": "Cana de Açúcar", "is_permeable": True},
    40: {"name": "Arroz", "is_permeable": True},
    41: {"name": "Outras Culturas Temporárias", "is_permeable": True},
    # Water bodies
    33: {"name": "Rio, Lago e Oceano", "is_permeable": True},
    26: {"name": "Água", "is_permeable": True},
}


class MapBiomasAdapter(DataProvider):
    """
    Google Earth Engine adapter for MapBiomas data.
    Requires GEE authentication (service account or oauth).
    """

    def __init__(self, initialize_gee: bool = True):
        """
        Initialize the adapter.

        Args:
            initialize_gee: Whether to initialize GEE on instantiation
        """
        self._initialized = False
        if initialize_gee:
            self._initialize_gee()

    def _initialize_gee(self):
        """Initialize Google Earth Engine with error handling"""
        if self._initialized:
            return

        try:
            # Try to initialize (assumes credentials are configured)
            ee.Initialize()
            self._initialized = True
            logger.info("Google Earth Engine initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Earth Engine: {e}")
            logger.warning("MapBiomasAdapter will return fallback data")
            self._initialized = False

    @property
    def name(self) -> str:
        return "MapBiomas (GEE)"

    def get_soil_data(self, lat: float, lon: float) -> SoilData:
        """
        Fetch soil/land cover data from MapBiomas Collection 8.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            SoilData with classification
        """
        if not self._initialized:
            # Fallback to safe defaults on GEE failure
            logger.warning(
                f"GEE not initialized, using fallback for soil at ({lat}, {lon})"
            )
            return {
                "class_id": 0,
                "class_name": "Dado Indisponível (GEE não inicializado)",
                "is_permeable": True,  # Conservative assumption
            }

        try:
            # Create point geometry
            point = ee.Geometry.Point([lon, lat])

            # Load MapBiomas Collection 8 (latest year available, e.g., 2022)
            # Asset ID: "projects/mapbiomas-workspace/public/collection8/mapbiomas_collection80_integration_v1"
            collection = ee.Image(
                "projects/mapbiomas-workspace/public/collection8/mapbiomas_collection80_integration_v1"
            )

            # Get classification for year 2022 (band b2022 or latest available)
            # Note: Adjust band name based on latest year in collection
            class_band = collection.select("classification_2022")

            # Sample the pixel at the point
            sample = class_band.reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=point,
                scale=30,  # 30m resolution
            )

            # Get the class value
            class_value = sample.get("classification_2022").getInfo()

            if class_value is None:
                logger.warning(f"No MapBiomas data at ({lat}, {lon})")
                return {
                    "class_id": 0,
                    "class_name": "Sem Dados MapBiomas",
                    "is_permeable": True,
                }

            class_id = int(class_value)
            class_info = MAPBIOMAS_SOIL_CLASSES.get(
                class_id,
                {
                    "name": f"Classe Desconhecida (ID: {class_id})",
                    "is_permeable": True,  # Conservative default
                },
            )

            return {
                "class_id": class_id,
                "class_name": class_info["name"],
                "is_permeable": class_info["is_permeable"],
            }

        except Exception as e:
            logger.error(f"Error fetching MapBiomas soil data: {e}")
            return {
                "class_id": 0,
                "class_name": f"Erro ao acessar MapBiomas: {str(e)[:50]}",
                "is_permeable": True,
            }

    def get_water_frequency(self, lat: float, lon: float) -> WaterData:
        """
        Fetch 30-year water frequency from MapBiomas Water Collection.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            WaterData with frequency (0-30 years)
        """
        if not self._initialized:
            logger.warning(
                f"GEE not initialized, using fallback for water at ({lat}, {lon})"
            )
            return {"frequency_years": 0, "confidence": 0.0}

        try:
            point = ee.Geometry.Point([lon, lat])

            # Load MapBiomas Water Collection (30-year frequency)
            # Asset: "projects/mapbiomas-workspace/public/collection8/mapbiomas_water_collection8_annual_water_coverage_v1"
            water_collection = ee.Image(
                "projects/mapbiomas-workspace/public/collection8/mapbiomas_water_collection8_water_frequency_v1"
            )

            # Get frequency band (years with water / 30 years)
            frequency_band = water_collection.select("water_frequency")

            # Sample at point
            sample = frequency_band.reduceRegion(
                reducer=ee.Reducer.first(), geometry=point, scale=30
            )

            frequency_value = sample.get("water_frequency").getInfo()

            if frequency_value is None:
                return {"frequency_years": 0, "confidence": 0.5}

            # MapBiomas water frequency is typically 0-100 (percentage)
            # Convert to years (0-30)
            frequency_years = int((frequency_value / 100.0) * 30)

            return {"frequency_years": frequency_years, "confidence": 1.0}

        except Exception as e:
            logger.error(f"Error fetching MapBiomas water frequency: {e}")
            return {"frequency_years": 0, "confidence": 0.0}
