"""
Risk Calculator - Business Logic Layer
Implements the weighted decision matrix for flood risk assessment.
"""

from typing import Dict, Any, Optional
from enum import Enum


class RiskLevel(Enum):
    """Risk classification levels"""

    BAIXO = "Baixo"
    MEDIO = "Médio"
    ALTO = "Alto"
    INDETERMINADO = "Indeterminado"


class RiskCalculator:
    """
    Centralized risk assessment logic.
    Weights: Topography (50%) > Water Frequency (30%) > Soil Permeability (20%)
    """

    # Weight configuration
    WEIGHT_TOPOGRAPHY = 0.50
    WEIGHT_WATER_FREQ = 0.30
    WEIGHT_SOIL_PERM = 0.20

    @staticmethod
    def calculate_topography_score(
        distance_m: float, elevation_diff_m: Optional[float]
    ) -> float:
        """
        Calculate topography risk score (0-1, higher = more risk)

        Factors:
        - Distance to water body (closer = higher risk)
        - Elevation difference (lower elevation = higher risk)
        """
        # Distance score: exponential decay, critical under 100m
        if distance_m < 50:
            distance_score = 1.0
        elif distance_m < 100:
            distance_score = 0.8
        elif distance_m < 200:
            distance_score = 0.5
        elif distance_m < 500:
            distance_score = 0.3
        else:
            distance_score = 0.1

        # Elevation score: negative diff = in depression (very high risk)
        if elevation_diff_m is None:
            elevation_score = 0.5  # Unknown = medium risk
        elif elevation_diff_m < -2:
            elevation_score = 1.0  # Below water level
        elif elevation_diff_m < 0:
            elevation_score = 0.9
        elif elevation_diff_m < 2:
            elevation_score = 0.7
        elif elevation_diff_m < 5:
            elevation_score = 0.4
        else:
            elevation_score = 0.1

        # Combine (weighted average)
        return (distance_score * 0.6) + (elevation_score * 0.4)

    @staticmethod
    def calculate_water_frequency_score(
        frequency_years: int, distance_m: Optional[float] = None
    ) -> float:
        """
        Calculate water frequency risk score (0-1)

        Priority 1: MapBiomas 30-year satellite water frequency
        Priority 2: PostGIS river proximity as fallback
                     (handles canalized rivers invisible to satellite)
        """
        # Priority 1: Use satellite data when available
        if frequency_years >= 20:
            return 1.0  # Flooded 2/3 of the time
        elif frequency_years >= 10:
            return 0.8
        elif frequency_years >= 5:
            return 0.6
        elif frequency_years >= 2:
            return 0.4
        elif frequency_years >= 1:
            return 0.2

        # Priority 2: Proximity fallback when satellite shows 0
        # Rationale: canalized urban rivers (Tietê, Pinheiros) are
        # invisible to MapBiomas Water but still pose flood risk
        if distance_m is not None and frequency_years == 0:
            if distance_m < 100:
                return 0.6  # Very close to water body
            elif distance_m < 300:
                return 0.4
            elif distance_m < 500:
                return 0.2
            elif distance_m < 1000:
                return 0.1

        return 0.0

    @staticmethod
    def calculate_soil_permeability_score(is_permeable: bool) -> float:
        """
        Calculate soil permeability risk score (0-1)

        Impermeable soils increase surface runoff and flood risk
        """
        return 0.0 if is_permeable else 1.0

    @classmethod
    def calculate_risk(
        cls,
        distance_m: float,
        elevation_diff_m: Optional[float],
        water_frequency_years: int,
        is_permeable: bool,
        soil_class_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive risk assessment.

        Args:
            distance_m: Distance to nearest water body
            elevation_diff_m: Elevation difference (point - river)
            water_frequency_years: Historical water frequency (0-30)
            is_permeable: Soil permeability
            soil_class_id: MapBiomas soil class ID (for metadata)

        Returns:
            Dict with risk_level, confidence, scores, and metadata
        """
        # Calculate individual scores
        topo_score = cls.calculate_topography_score(distance_m, elevation_diff_m)
        water_score = cls.calculate_water_frequency_score(
            water_frequency_years, distance_m=distance_m
        )
        soil_score = cls.calculate_soil_permeability_score(is_permeable)

        # Weighted total score
        total_score = (
            topo_score * cls.WEIGHT_TOPOGRAPHY
            + water_score * cls.WEIGHT_WATER_FREQ
            + soil_score * cls.WEIGHT_SOIL_PERM
        )

        # Classify risk level
        if total_score >= 0.7:
            risk_level = RiskLevel.ALTO
        elif total_score >= 0.4:
            risk_level = RiskLevel.MEDIO
        else:
            risk_level = RiskLevel.BAIXO

        # Calculate confidence based on data availability
        confidence = 1.0
        if elevation_diff_m is None:
            confidence *= 0.8
        if soil_class_id is None:
            confidence *= 0.9

        return {
            "risk_level": risk_level.value,
            "confidence": round(confidence, 2),
            "total_score": round(total_score, 3),
            "scores": {
                "topography": round(topo_score, 3),
                "water_frequency": round(water_score, 3),
                "soil_permeability": round(soil_score, 3),
            },
            "weights": {
                "topography": cls.WEIGHT_TOPOGRAPHY,
                "water_frequency": cls.WEIGHT_WATER_FREQ,
                "soil_permeability": cls.WEIGHT_SOIL_PERM,
            },
            "metadata": {
                "distance_m": distance_m,
                "elevation_diff_m": elevation_diff_m,
                "water_frequency_years": water_frequency_years,
                "is_permeable": is_permeable,
                "soil_class_id": soil_class_id,
            },
        }
