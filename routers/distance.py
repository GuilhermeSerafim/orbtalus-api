from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shapely.geometry import shape
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal
import models

router = APIRouter()


# Dependência para conectar ao Docker
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DistanceReq(BaseModel):
    polygon: dict


@router.post("/distance")
def distance_api(req: DistanceReq, db: Session = Depends(get_db)):
    # 1. Pegamos a coordenada do polígono vindo do mapa (React/Angular)
    geom = shape(req.polygon.get("geometry", req.polygon))
    rep = geom.representative_point()
    lon, lat = rep.x, rep.y

    # 2. CONSULTA ESPACIAL: O PostGIS faz o cálculo pesado
    user_point = f"SRID=4326;POINT({lon} {lat})"

    # Buscamos o rio mais próximo usando ST_DistanceSphere (metros)
    closest_river = (
        db.query(
            models.WaterBody,
            func.ST_DistanceSphere(models.WaterBody.geom, user_point).label("dist_m"),
        )
        .order_by("dist_m")
        .first()
    )

    if not closest_river:
        raise HTTPException(status_code=404, detail="Nenhum rio no banco de dados.")

    rio, dist_m = closest_river

    return {
        "distancia_rio_m": round(dist_m, 1),
        "rio_mais_proximo": rio.name,
        "waterway": rio.type,
        "nearest_point": {"lon": lon, "lat": lat},  # Coordenada original da consulta
    }
