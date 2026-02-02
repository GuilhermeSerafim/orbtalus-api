from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shapely.geometry import shape
from sqlalchemy.orm import Session
from sqlalchemy import func
import re

from database import SessionLocal
import models
from services.elevation_service import elevation_m
from services.ai_service import get_ai_assessment
from services.osm_service import OSMService

# Clean Architecture imports
from providers import MapBiomasAdapter, NottusAdapter
from core import RiskCalculator

router = APIRouter()

osm_service = OSMService()

# Initialize data provider (can be switched via config)
# For now, use MapBiomas. Change to NottusAdapter() when ready.
try:
    data_provider = MapBiomasAdapter(initialize_gee=True)
except Exception as e:
    # Fallback to Nottus (mock) if GEE fails
    print(f"Warning: MapBiomas initialization failed, using Nottus fallback: {e}")
    data_provider = NottusAdapter()


# Dependência para o banco de dados
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
    # 1. Processamento Geográfico Inicial
    geom = shape(req.polygon.get("geometry", req.polygon))
    rep = geom.representative_point()
    lon, lat = rep.x, rep.y

    osm_service.fetch_and_save_rivers(db, lat, lon)

    # 2. CONSULTA POSTGIS: Busca o rio mais próximo e o ponto exato de contato
    user_point = f"SRID=4326;POINT({lon} {lat})"

    # Buscamos o rio, a distância e o ponto do rio mais próximo para o cálculo de altitude
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
            status_code=404, detail="Nenhum corpo d'água encontrado na base de dados."
        )

    rio, dist_m, rio_ponto_wkt = result
    rio_nome = rio.name or "Rio/Córrego não identificado"

    # 3. EXTRAÇÃO DE COORDENADAS DO RIO (para o serviço de altitude)
    # Extrai números do formato 'POINT(LON LAT)'
    coords = re.findall(r"[-+]?\d*\.\d+|\d+", rio_ponto_wkt)
    rio_lon, rio_lat = float(coords[0]), float(coords[1])

    # 4. ANÁLISE DE ALTITUDE (Topografia)
    elev_ponto = elevation_m(lat, lon)
    elev_rio = elevation_m(rio_lat, rio_lon)
    queda_rel = (elev_ponto - elev_rio) if elev_ponto and elev_rio else None

    # 5. DADOS AMBIENTAIS (via Provider Pattern)
    try:
        soil_data = data_provider.get_soil_data(lat, lon)
        water_data = data_provider.get_water_frequency(lat, lon)
    except Exception as e:
        # Graceful degradation on provider failure
        print(f"Provider error: {e}")
        soil_data = {"class_id": 0, "class_name": "Indisponível", "is_permeable": True}
        water_data = {"frequency_years": 0, "confidence": 0.0}

    # 6. CÁLCULO DE RISCO (Business Logic Layer)
    risk_result = RiskCalculator.calculate_risk(
        distance_m=dist_m,
        elevation_diff_m=queda_rel,
        water_frequency_years=water_data["frequency_years"],
        is_permeable=soil_data["is_permeable"],
        soil_class_id=soil_data.get("class_id"),
    )

    # 7. INTELIGÊNCIA ARTIFICIAL (Laudo Técnico Enriquecido)
    queda_rel_str = f"{queda_rel:.1f}m" if queda_rel is not None else "N/A"

    prompt = (
        f"Com base nas seguintes informações de geoprocessamento:\n"
        f"- Distância até o corpo d'água ({rio.type}): {dist_m:.1f} metros\n"
        f"- Rio/Córrego mais próximo: {rio_nome}\n"
        f"- Queda relativa (diferença de altitude): {queda_rel_str}\n"
        f"- Frequência histórica de água (30 anos): {water_data['frequency_years']} anos\n"
        f"- Tipo de solo: {soil_data['class_name']} (Permeável: {soil_data['is_permeable']})\n"
        f"- Classificação de risco calculada: {risk_result['risk_level']} (Score: {risk_result['total_score']:.2f})\n\n"
        "Como especialista em gestão de riscos hídricos, valide e explique esta classificação "
        "de forma técnica e objetiva, considerando os pesos aplicados (Topografia 50%, Água 30%, Solo 20%)."
    )

    ai = get_ai_assessment(prompt)

    # 8. PERSISTÊNCIA DO HISTÓRICO
    assessment = models.RiskAssessment(
        lat=lat,
        lon=lon,
        risk_level=risk_result["risk_level"],  # Use calculated risk
        explanation=ai.explanation,
        river_name=rio_nome,
        distance_m=dist_m,
        water_frequency_30y=water_data["frequency_years"],
        soil_type=soil_data["class_name"],
        soil_class_id=soil_data.get("class_id"),  # Store for audit
        is_permeable=soil_data["is_permeable"],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    # 9. RESPOSTA ENRIQUECIDA (Audit-Ready)
    return {
        # Existing fields (backward compatibility)
        "distancia_rio_m": round(dist_m, 1),
        "queda_relativa_m": round(queda_rel, 1) if queda_rel is not None else None,
        "rio_mais_proximo": rio_nome,
        "tipo_hidrografia": rio.type,
        "resposta_ia": ai.explanation,
        "risk_level": risk_result["risk_level"],
        # New: Rich metadata for Sabesp audit
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
        },
        "debug_coords": {"rio_lat": rio_lat, "rio_lon": rio_lon},
    }
