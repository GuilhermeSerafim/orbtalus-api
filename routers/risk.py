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

router = APIRouter()

osm_service = OSMService()

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

    # 5. INTELIGÊNCIA ARTIFICIAL (Laudo Técnico)
    queda_rel_str = f"{queda_rel:.1f}m" if queda_rel is not None else "N/A"

    prompt = (
        f"Com base nas seguintes informações de geoprocessamento:\n"
        f"- Distância até o corpo d'água ({rio.type}): {dist_m:.1f} metros\n"
        f"- Rio/Córrego mais próximo: {rio_nome}\n"
        f"- Queda relativa (diferença de altitude): {queda_rel_str}\n\n"
        "Como especialista em gestão de riscos hídricos, classifique o risco de alagamento "
        "como Baixo, Médio ou Alto e forneça uma justificativa técnica objetiva."
    )

    ai = get_ai_assessment(prompt)

    return {
        "distancia_rio_m": round(dist_m, 1),
        "queda_relativa_m": round(queda_rel, 1) if queda_rel is not None else None,
        "rio_mais_proximo": rio_nome,
        "tipo_hidrografia": rio.type,
        "resposta_ia": ai.explanation,
        "risk_level": ai.risk_level,
        "debug_coords": {"rio_lat": rio_lat, "rio_lon": rio_lon},
    }
