from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shapely.geometry import Polygon
from sqlalchemy.orm import Session
from core.demo_quota import admit_hydrology_request
from core.errors import ServiceUnavailable
from core.geometry import get_geo_db, validated_polygon
from core.validation import HYDROLOGY_RADIUS_KM
from services.osm_service import OSMService, nearest_water_body

router = APIRouter()


@router.post("/distance")
def distance_api(geom: Polygon = Depends(validated_polygon),
                 db: Session = Depends(get_geo_db, scope="function")):
    # 1. Pegamos a coordenada do polígono vindo do mapa (React/Angular)
    rep = geom.representative_point()
    lon, lat = rep.x, rep.y

    closest_river = nearest_water_body(db, lat, lon, allow_undated=True)
    if closest_river is None:
        raise HTTPException(status_code=404, detail="Nenhum corpo d'água cadastrado no raio de busca.")

    rio, dist_m = closest_river

    return {
        "distancia_rio_m": round(dist_m, 1),
        "rio_mais_proximo": rio.name,
        "waterway": rio.type,
        "nearest_point": {"lon": lon, "lat": lat},  # Coordenada original da consulta
    }


class HydrologyRiver(BaseModel):
    nome: str | None
    tipo: str | None
    distancia_m: float
    fonte: str
    id_fonte: str
    atualizado_na_fonte_em: datetime | None


class HydrologyResponse(BaseModel):
    consulta: Literal["cache", "overpass"]
    consultado_em: datetime
    raio_m: int
    rio: HydrologyRiver | None


@router.post(
    "/hydrology",
    response_model=HydrologyResponse,
    dependencies=[Depends(admit_hydrology_request)],
    summary="Consultar o rio mais próximo sem executar a análise de risco",
    responses={
        429: {"description": "Limite diário de consultas hidrográficas da demo atingido."},
        503: {"description": "Cobertura hidrográfica, banco ou serviço da demo indisponível."},
    },
)
def hydrology_api(geom: Polygon = Depends(validated_polygon),
                  db: Session = Depends(get_geo_db, scope="function"),
                  osm: OSMService = Depends(OSMService)):
    """Usa o cache vigente ou consulta o Overpass. Uma busca válida pode retornar rio nulo."""
    point = geom.representative_point()
    coverage = osm.ensure_coverage(point.y, point.x)
    if coverage is None:
        raise ServiceUnavailable("HYDROLOGY_LOOKUP_FAILED")

    nearest = nearest_water_body(db, point.y, point.x)
    river = None
    if nearest is not None:
        water, meters = nearest
        river = HydrologyRiver(nome=water.name, tipo=water.type, distancia_m=round(meters, 1),
                               fonte=water.source, id_fonte=water.source_id,
                               atualizado_na_fonte_em=water.source_updated_at)
    return HydrologyResponse(consulta=coverage.origin, consultado_em=coverage.fetched_at,
                             raio_m=HYDROLOGY_RADIUS_KM * 1000, rio=river)
