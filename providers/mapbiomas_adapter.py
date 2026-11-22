"""
MapBiomas Adapter - Google Earth Engine Integration
Implements real data fetching from MapBiomas Collections via GEE.
"""

import ee
import json
import logging
import os

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from requests import RequestException

from core.config import get_settings
from core.errors import ServiceUnavailable
from core.validation import finite_number

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

        project = get_settings().gee_project
        if not project or not project.strip():
            raise ServiceUnavailable("CONFIG_UNAVAILABLE")

        try:
            # Check for service account credentials
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            credentials_json = os.environ.get("GEE_SERVICE_ACCOUNT_JSON")

            if credentials_path:
                # Option 1: Local file path (development)
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=["https://www.googleapis.com/auth/earthengine"],
                )
            elif credentials_json:
                # Option 2: JSON string (Cloud Run / production)
                from google.oauth2 import service_account

                info = json.loads(credentials_json)
                if not isinstance(info, dict):
                    raise ServiceUnavailable("CONFIG_UNAVAILABLE")
                credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/earthengine"],
                )
            else:
                # Option 3: Default (ADC or previously authenticated)
                credentials = None
        except (OSError, ValueError, GoogleAuthError):
            raise ServiceUnavailable("CONFIG_UNAVAILABLE") from None

        try:
            if credentials is None:
                ee.Initialize(project=project)
            else:
                ee.Initialize(credentials=credentials, project=project)
            self._initialized = True
        except (ee.EEException, GoogleAuthError, HttpError, RequestException, OSError):
            raise ServiceUnavailable("DATA_UNAVAILABLE") from None

    @property
    def name(self) -> str:
        return "MapBiomas (GEE)"

    def get_soil_data(self, lat: float, lon: float) -> SoilData | None:
        """
        Fetch soil/land cover data from MapBiomas Collection 8.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            SoilData with classification
        """
        if not self._initialized:
            raise ServiceUnavailable("DATA_UNAVAILABLE")

        try:
            # Create point geometry
            point = ee.Geometry.Point([lon, lat])

            # Load MapBiomas Collection 8 (Integration)
            # Using the correct asset path for Collection 8
            collection = ee.Image(
                "projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1"
            )

            # Get classification for year 2022 (or latest available)
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
                return None

            finite_number(class_value)
            if class_value not in MAPBIOMAS_SOIL_CLASSES:
                raise ServiceUnavailable("DATA_UNAVAILABLE")
            class_id = int(class_value)
            class_info = MAPBIOMAS_SOIL_CLASSES[class_id]

            return {
                "class_id": class_id,
                "class_name": class_info["name"],
                "is_permeable": class_info["is_permeable"],
            }

        except (ee.EEException, GoogleAuthError, HttpError, RequestException, OSError):
            raise ServiceUnavailable("DATA_UNAVAILABLE") from None

    # Known band names for MapBiomas Water frequency across versions
    WATER_FREQUENCY_BANDS = [
        "water_frequency_1985_2023",
        "frequency",
        "water_frequency",
        "water_frequency_1985_2022",
    ]

    def _detect_water_band(self, image: "ee.Image") -> str:
        """
        Auto-detect the correct band name from the MapBiomas Water asset.
        Only known frequency bands have the required scientific meaning.
        """
        available_bands = image.bandNames().getInfo()
        if not isinstance(available_bands, list):
            raise ServiceUnavailable("DATA_UNAVAILABLE")

        for candidate in self.WATER_FREQUENCY_BANDS:
            if candidate in available_bands:
                logger.info(f"Using water frequency band: '{candidate}'")
                return candidate

        raise ServiceUnavailable("DATA_UNAVAILABLE")

    def get_water_frequency(self, lat: float, lon: float) -> WaterData | None:
        """
        Fetch 30-year water frequency from MapBiomas Water Collection.

        Uses a 1km buffer around the point with max reducer to capture
        nearby water pixels, since the point itself is typically on land.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            WaterData with frequency (0-30 years)
        """
        if not self._initialized:
            raise ServiceUnavailable("DATA_UNAVAILABLE")

        try:
            logger.info(f"Fetching water frequency for ({lat}, {lon})")
            point = ee.Geometry.Point([lon, lat])

            # Buffer 1km around the point to capture nearby water bodies
            buffer = point.buffer(1000)

            # Load MapBiomas Water Collection 3 (official water frequency dataset)
            water_collection = ee.Image(
                "projects/mapbiomas-public/assets/brazil/water/collection3/mapbiomas_water_frequency_v1"
            )

            # Auto-detect the correct band name
            band_name = self._detect_water_band(water_collection)
            frequency_band = water_collection.select(band_name)

            # Use max reducer within the buffer — captures the highest water
            # frequency in the surrounding area (e.g. nearby river pixels)
            sample = frequency_band.reduceRegion(
                reducer=ee.Reducer.max(),
                geometry=buffer,
                scale=30,
                maxPixels=5000,
            )

            # Get the computed value
            frequency_value = sample.get(band_name).getInfo()
            if frequency_value is None:
                return None

            # MapBiomas water frequency is 0-100 (percentage of years with water)
            # Convert to years out of 30 — use round() to avoid truncation
            frequency_pct = finite_number(frequency_value)
            if not 0 <= frequency_pct <= 100:
                raise ServiceUnavailable("DATA_UNAVAILABLE")
            frequency_years = round((frequency_pct / 100.0) * 30)

            logger.info(
                f"Water frequency at ({lat}, {lon}): {frequency_years} years "
                f"(from {frequency_pct:.1f}%, band='{band_name}', buffer=1km)"
            )
            return {"frequency_years": frequency_years, "confidence": 1.0}

        except (ee.EEException, GoogleAuthError, HttpError, RequestException, OSError):
            raise ServiceUnavailable("DATA_UNAVAILABLE") from None

    def get_elevation(self, lat: float, lon: float) -> float:
        """
        Fetch elevation data from SRTM (Shuttle Radar Topography Mission) via GEE.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            Elevation in meters. Unavailable data raises ServiceUnavailable.
        """
        if not self._initialized:
            raise ServiceUnavailable("DATA_UNAVAILABLE")

        try:
            point = ee.Geometry.Point([lon, lat])

            # SRTM Digital Elevation Model (30m resolution)
            srtm = ee.Image("USGS/SRTMGL1_003")

            # Sample elevation at point
            elevation_data = (
                srtm.sample(region=point, scale=30, geometries=True)
                .first()
                .get("elevation")
            )

            elevation_m = elevation_data.getInfo()

            logger.debug(f"SRTM elevation at ({lat}, {lon}): {elevation_m}m")
            return finite_number(elevation_m)

        except (ee.EEException, GoogleAuthError, HttpError, RequestException, OSError):
            raise ServiceUnavailable("DATA_UNAVAILABLE") from None
