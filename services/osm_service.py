import overpy
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func
import models

logger = logging.getLogger(__name__)


class OSMService:
    def __init__(self):
        self.api = overpy.Overpass()

    def fetch_and_save_rivers(
        self, db: Session, lat: float, lon: float, radius_km: int = 5
    ):
        """
        Fetch waterways from OpenStreetMap and save to PostGIS.

        Handles both individual ways AND relations (large rivers like
        Tietê/Pinheiros are modeled as relations in OSM, with the name
        tag on the relation, not on individual way segments).
        """
        # 1. Cache check — skip if area is already well-mapped
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
            return  # Area already mapped

        # 2. Query Overpass: ways + relations with full resolution
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

            # 3. Build relation name/type lookup for member ways
            # In OSM, large rivers have name on the RELATION, not on ways
            way_relation_info = {}
            for rel in result.relations:
                rel_name = rel.tags.get("name")
                rel_type = rel.tags.get("waterway", "river")
                logger.info(
                    f"OSM Relation found: {rel_name} (type={rel_type}, "
                    f"members={len(rel.members)})"
                )
                for member in rel.members:
                    if member._type_value == "way":
                        way_relation_info[member.ref] = {
                            "name": rel_name,
                            "type": rel_type,
                        }

            # 4. Process all ways with relation name fallback
            new_rivers = []
            for way in result.ways:
                if len(way.nodes) < 2:
                    continue

                coords = ",".join([f"{n.lon} {n.lat}" for n in way.nodes])
                wkt = f"LINESTRING({coords})"

                # Name resolution priority: way tags > relation tags > None
                name = way.tags.get("name")
                wtype = way.tags.get("waterway")

                if way.id in way_relation_info:
                    rel_info = way_relation_info[way.id]
                    if name is None:
                        name = rel_info["name"]
                    if wtype is None:
                        wtype = rel_info["type"]

                # Default type if still None (ways from skel output)
                if wtype is None:
                    wtype = "stream"

                river = models.WaterBody(
                    name=name,
                    type=wtype,
                    geom=f"SRID=4326;{wkt}",
                )
                new_rivers.append(river)

            if new_rivers:
                db.add_all(new_rivers)
                db.commit()
                logger.info(
                    f"OSM: {len(new_rivers)} water bodies saved "
                    f"({len(way_relation_info)} from relations)"
                )
                print(
                    f"Sucesso: {len(new_rivers)} corpos d'água salvos "
                    f"({len(way_relation_info)} via relations com nomes)."
                )
            else:
                logger.warning(f"No waterways found near ({lat}, {lon})")

        except Exception as e:
            logger.error(f"Error fetching OSM data: {e}", exc_info=True)
            print(f"Erro ao buscar dados do OSM: {e}")
