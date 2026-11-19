import logging

from fastapi import APIRouter, Depends
from shapely.geometry import Polygon
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from core import RiskCalculator
from core.demo_quota import admit_demo_request
from core.errors import ServiceUnavailable
from core.geometry import get_geo_db, validated_polygon, river_coordinates
from core.validation import finite_number, nonnegative_distance
from providers import MapBiomasAdapter
from providers.mapbiomas_adapter import MAPBIOMAS_SOIL_CLASSES
from services.ai_service import get_ai_assessment
from services.elevation_service import elevation_m
from services.osm_service import OSMService
from services.text_sanitizer import sanitize_text

router = APIRouter()
logger = logging.getLogger(__name__)

def get_data_provider():
    return MapBiomasAdapter(initialize_gee=True)


def get_osm_service():
    return OSMService()


@router.post("/risk", dependencies=[Depends(admit_demo_request)])
def risk_api(geom: Polygon = Depends(validated_polygon),
             db: Session = Depends(get_geo_db, scope="function")):
    # 1. Initial geospatial processing
    rep = geom.representative_point()
    lon, lat = rep.x, rep.y

    # OSM enrichment is best effort and uses its own transaction.
    get_osm_service().fetch_and_save_rivers(lat, lon)

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
        raise ServiceUnavailable('DATA_UNAVAILABLE')

    rio, dist_m, rio_ponto_wkt = result
    dist_m = nonnegative_distance(dist_m)
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
    rio_lon, rio_lat = river_coordinates(rio_ponto_wkt)

    # 4. Topography analysis.
    elev_ponto = finite_number(elevation_m(lat, lon))
    elev_rio = finite_number(elevation_m(rio_lat, rio_lon))
    queda_rel = finite_number(elev_ponto - elev_rio)

    # 5. Environmental data (provider pattern).
    data_provider = get_data_provider()
    soil_data = data_provider.get_soil_data(lat, lon)
    water_data = data_provider.get_water_frequency(lat, lon)

    if not isinstance(soil_data, dict) or not isinstance(water_data, dict):
        raise ServiceUnavailable('DATA_UNAVAILABLE')
    class_id = finite_number(soil_data.get('class_id'))
    known_soil = MAPBIOMAS_SOIL_CLASSES.get(class_id)
    if (known_soil is None or type(soil_data.get('is_permeable')) is not bool
            or soil_data['is_permeable'] != known_soil['is_permeable']):
        raise ServiceUnavailable('DATA_UNAVAILABLE')
    years = finite_number(water_data.get('frequency_years'))
    confidence = finite_number(water_data.get('confidence'))
    if not years.is_integer() or not 0 <= years <= 30 or not 0 <= confidence <= 1:
        raise ServiceUnavailable('DATA_UNAVAILABLE')
    if not isinstance(soil_data.get('class_name'), str) or not soil_data['class_name'].strip():
        raise ServiceUnavailable('DATA_UNAVAILABLE')
    soil_data = dict(soil_data)

    soil_data["class_name"] = (
        sanitize_text(
            soil_data.get("class_name"),
            field_name="soil_type",
            logger=logger,
            context="risk.provider",
        )
    )
    if not soil_data['class_name']:
        raise ServiceUnavailable('DATA_UNAVAILABLE')

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

    ai = get_ai_assessment(prompt, expected_risk_level=risk_result['risk_level'])
    if not isinstance(ai.explanation, str):
        raise ServiceUnavailable('AI_UNAVAILABLE')
    ai_explanation = sanitize_text(
        ai.explanation,
        field_name="explanation",
        logger=logger,
        context="risk.assessment",
    )
    if not isinstance(ai_explanation, str) or not ai_explanation.strip():
        raise ServiceUnavailable('AI_UNAVAILABLE')

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
    # Prepare the original response before the commit; no refresh is needed.
    response = {
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
            "provider_status": "OK",
        },
        "debug_coords": {"rio_lat": rio_lat, "rio_lon": rio_lon},
    }
    db.add(assessment)
    db.commit()
    db.info['risk_assessment_committed'] = True
    return response
