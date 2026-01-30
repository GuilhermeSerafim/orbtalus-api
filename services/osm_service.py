import overpy
from sqlalchemy.orm import Session
from sqlalchemy import func
import models


class OSMService:
    def __init__(self):
        self.api = overpy.Overpass()

    def fetch_and_save_rivers(
        self, db: Session, lat: float, lon: float, radius_km: int = 5
    ):
        # 1. Verificar se já temos dados nessa região (Cache)
        # Se houver mais de 5 rios no raio, consideramos que a área já foi "mapeada"
        user_point = f"SRID=4326;POINT({lon} {lat})"
        existing_count = (
            db.query(models.WaterBody)
            .filter(
                func.ST_DistanceSphere(models.WaterBody.geom, user_point)
                < (radius_km * 1000)
            )
            .count()
        )

        if existing_count > 5:
            return  # Área já mapeada, economiza tempo e API

        # 2. Query Overpass: Busca 'ways' (linhas) e 'relations' (áreas/rios largos)
        query = f"""
        [out:json][timeout:25];
        (
          way["waterway"](around:{radius_km * 1000},{lat},{lon});
          relation["waterway"](around:{radius_km * 1000},{lat},{lon});
        );
        out body;
        >;
        out skel qt;
        """

        try:
            result = self.api.query(query)
            new_rivers = []

            for way in result.ways:
                # Transformamos os nós do OSM em uma LineString WKT para o PostGIS
                coords = ",".join([f"{n.lon} {n.lat}" for n in way.nodes])
                if len(way.nodes) < 2:
                    continue

                wkt = f"LINESTRING({coords})"

                river = models.WaterBody(
                    name=way.tags.get("name"),
                    type=way.tags.get("waterway", "river"),
                    geom=f"SRID=4326;{wkt}",
                )
                new_rivers.append(river)

            if new_rivers:
                db.add_all(new_rivers)
                db.commit()
                print(
                    f"Sucesso: {len(new_rivers)} novos corpos d'água salvos no Supabase."
                )

        except Exception as e:
            print(f"Erro ao buscar dados do OSM: {e}")
