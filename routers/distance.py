from fastapi import APIRouter, Depends, HTTPException
from shapely.geometry import Polygon
from sqlalchemy.orm import Session
from sqlalchemy import func
from core.geometry import get_geo_db, validated_polygon
from core.validation import nonnegative_distance
import models

router = APIRouter()


@router.post("/distance")
def distance_api(geom: Polygon = Depends(validated_polygon),
                 db: Session = Depends(get_geo_db, scope="function")):
    # 1. Pegamos a coordenada do polígono vindo do mapa (React/Angular)
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
    dist_m = nonnegative_distance(dist_m)

    return {
        "distancia_rio_m": round(dist_m, 1),
        "rio_mais_proximo": rio.name,
        "waterway": rio.type,
        "nearest_point": {"lon": lon, "lat": lat},  # Coordenada original da consulta
    }
