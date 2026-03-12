import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shapely.geometry import shape
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from core import RiskCalculator
from database import SessionLocal
from providers import MapBiomasAdapter, NottusAdapter
from services.ai_service import get_ai_assessment
from services.elevation_service import elevation_m
from services.osm_service import OSMService
from services.text_sanitizer import sanitize_text

router = APIRouter()
logger = logging.getLogger(__name__)

osm_service = OSMService()

# Initialize data provider (can be switched via config)
try:
    data_provider = MapBiomasAdapter(initialize_gee=True)
except Exception as e:
    print(f"Warning: MapBiomas initialization failed, using Nottus fallback: {e}")
    data_provider = NottusAdapter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DistanceReq(BaseModel):
    polygon: dict


@router.post("/risk")
def risk_api(req: DistanceReq, db: Session = Depends(get_db)):
    # 1. Initial geospatial processing
    geom = shape(req.polygon.get("geometry", req.polygon))
    rep = geom.representative_point()
    lon, lat = rep.x, rep.y

    # OSM enrichment is best effort and uses its own transaction.
    osm_service.fetch_and_save_rivers(lat, lon)

    # 2. Query PostGIS for nearest water body and closest contact point.
    user_point = f"SRID=4326;POINT({lon} {lat})"
    result = (
        db.query(
            models.WaterBody,
            func.ST_DistanceSphere(models.WaterBody.geom, user_point).label("dist_m"),
            func.ST_AsText(
                func.ST_ClosestPoint(models.WaterBody.geom, user_point)
            ).label("rio_ponto_wkt"),
        )
        .order_by("dist_m")
        .first()
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Nenhum corpo d'\u00e1gua encontrado na base de dados.",
        )

    rio, dist_m, rio_ponto_wkt = result
    rio_nome = (
        sanitize_text(
            rio.name,
            field_name="river_name",
            logger=logger,
            context="risk.water_body",
        )
        or "Rio/C\u00f3rrego n\u00e3o identificado"
    )
    rio_tipo = (
        sanitize_text(
            rio.type,
            field_name="type",
            logger=logger,
            context="risk.water_body",
        )
        or "stream"
    )

    # 3. Extract river coordinates for elevation lookup.
    coords = re.findall(r"[-+]?\d*\.\d+|\d+", rio_ponto_wkt)
    rio_lon, rio_lat = float(coords[0]), float(coords[1])

    # 4. Topography analysis.
    elev_ponto = elevation_m(lat, lon)
    elev_rio = elevation_m(rio_lat, rio_lon)
    queda_rel = (elev_ponto - elev_rio) if elev_ponto and elev_rio else None

    # 5. Environmental data (provider pattern).
    try:
        soil_data = data_provider.get_soil_data(lat, lon)
        water_data = data_provider.get_water_frequency(lat, lon)
    except Exception as e:
        print(f"Provider error: {e}")
        soil_data = {
            "class_id": 0,
            "class_name": "Indispon\u00edvel",
            "is_permeable": True,
        }
        water_data = {"frequency_years": 0, "confidence": 0.0}

    soil_data["class_name"] = (
        sanitize_text(
            soil_data.get("class_name"),
            field_name="soil_type",
            logger=logger,
            context="risk.provider",
        )
        or "Indisponivel"
    )

    # 6. Business risk calculation.
    risk_result = RiskCalculator.calculate_risk(
        distance_m=dist_m,
        elevation_diff_m=queda_rel,
        water_frequency_years=water_data["frequency_years"],
        is_permeable=soil_data["is_permeable"],
        soil_class_id=soil_data.get("class_id"),
    )
    risk_result["risk_level"] = (
        sanitize_text(
            risk_result["risk_level"],
            field_name="risk_level",
            logger=logger,
            context="risk.assessment",
        )
        or risk_result["risk_level"]
    )

    # 7. AI enriched technical assessment.
    queda_rel_str = f"{queda_rel:.1f}m" if queda_rel is not None else "N/A"
    prompt = (
        "Com base nas seguintes informa\u00e7\u00f5es de geoprocessamento:\n"
        f"- Dist\u00e2ncia at\u00e9 o corpo d'\u00e1gua ({rio_tipo}): {dist_m:.1f} metros\n"
        f"- Rio/C\u00f3rrego mais pr\u00f3ximo: {rio_nome}\n"
        f"- Queda relativa (diferen\u00e7a de altitude): {queda_rel_str}\n"
        f"- Frequ\u00eancia hist\u00f3rica de \u00e1gua (30 anos): {water_data['frequency_years']} anos\n"
        f"- Tipo de solo: {soil_data['class_name']} (Perme\u00e1vel: {soil_data['is_permeable']})\n"
        f"- Classifica\u00e7\u00e3o de risco calculada: {risk_result['risk_level']} (Score: {risk_result['total_score']:.2f})\n\n"
        "Como especialista em gest\u00e3o de riscos h\u00eddricos, valide e explique esta classifica\u00e7\u00e3o "
        "de forma t\u00e9cnica e objetiva, considerando os pesos aplicados (Topografia 50%, \u00c1gua 30%, Solo 20%)."
    )

    ai = get_ai_assessment(prompt)
    ai_explanation = sanitize_text(
        ai.explanation,
        field_name="explanation",
        logger=logger,
        context="risk.assessment",
    )

    # 8. Persist request history.
    assessment = models.RiskAssessment(
        lat=lat,
        lon=lon,
        risk_level=risk_result["risk_level"],
        explanation=ai_explanation,
        river_name=rio_nome,
        distance_m=dist_m,
        water_frequency_30y=water_data["frequency_years"],
        soil_type=soil_data["class_name"],
        soil_class_id=soil_data.get("class_id"),
        is_permeable=soil_data["is_permeable"],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    # 9. Enriched response.
    return {
        "distancia_rio_m": round(dist_m, 1),
        "queda_relativa_m": round(queda_rel, 1) if queda_rel is not None else None,
        "rio_mais_proximo": rio_nome,
        "tipo_hidrografia": rio_tipo,
        "resposta_ia": ai_explanation,
        "risk_level": risk_result["risk_level"],
        "risk_calculation": {
            "confidence": risk_result["confidence"],
            "total_score": risk_result["total_score"],
            "component_scores": risk_result["scores"],
            "weights_applied": risk_result["weights"],
        },
        "environmental_data": {
            "soil": {
                "class_id": soil_data.get("class_id"),
                "class_name": soil_data["class_name"],
                "is_permeable": soil_data["is_permeable"],
            },
            "water_frequency": {
                "years": water_data["frequency_years"],
                "confidence": water_data.get("confidence"),
            },
            "data_source": data_provider.name,
            "provider_status": (
                "OK"
                if "Indispon" not in soil_data.get("class_name", "")
                else "DEGRADED_USING_FALLBACK"
            ),
        },
        "debug_coords": {"rio_lat": rio_lat, "rio_lon": rio_lon},
    }
