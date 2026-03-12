import logging

import overpy
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from services.text_sanitizer import sanitize_text

logger = logging.getLogger(__name__)


class OSMService:
    def __init__(self):
        self.api = overpy.Overpass()

    def fetch_and_save_rivers(self, lat: float, lon: float, radius_km: int = 5):
        db = SessionLocal()
        try:
            self._fetch_and_save_rivers(db, lat, lon, radius_km)
        except Exception as e:
            db.rollback()
            logger.error(
                "Error fetching OSM data near (%s, %s): %s",
                lat,
                lon,
                e,
                exc_info=True,
            )
            print(f"Erro ao buscar dados do OSM: {e}")
        finally:
            db.close()

    def _fetch_and_save_rivers(
        self, db: Session, lat: float, lon: float, radius_km: int = 5
    ):
        """
        Fetch waterways from OpenStreetMap and save to PostGIS.

        Handles both individual ways AND relations (large rivers like
        Tiete/Pinheiros are modeled as relations in OSM, with the name
        tag on the relation, not on individual way segments).
        """
        # 1. Cache check: skip if area is already well-mapped.
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
            return

        # 2. Query Overpass: ways + relations with full resolution.
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
        result = self.api.query(query)

        # 3. Build relation name/type lookup for member ways.
        way_relation_info = {}
        for rel in result.relations:
            rel_name = sanitize_text(
                rel.tags.get("name"),
                field_name="name",
                logger=logger,
                context=f"osm_relation[{rel.id}]",
            )
            rel_type = sanitize_text(
                rel.tags.get("waterway", "river"),
                field_name="type",
                logger=logger,
                context=f"osm_relation[{rel.id}]",
            )
            logger.info(
                "OSM relation found: %s (type=%s, members=%s)",
                rel_name,
                rel_type,
                len(rel.members),
            )
            for member in rel.members:
                if member._type_value == "way":
                    way_relation_info[member.ref] = {
                        "name": rel_name,
                        "type": rel_type,
                    }

        # 4. Process all ways with relation name fallback.
        new_rivers = []
        for way in result.ways:
            if len(way.nodes) < 2:
                continue

            coords = ",".join(f"{node.lon} {node.lat}" for node in way.nodes)
            wkt = f"LINESTRING({coords})"

            name = way.tags.get("name")
            waterway_type = way.tags.get("waterway")

            if way.id in way_relation_info:
                rel_info = way_relation_info[way.id]
                if name is None:
                    name = rel_info["name"]
                if waterway_type is None:
                    waterway_type = rel_info["type"]

            name = sanitize_text(
                name,
                field_name="name",
                logger=logger,
                context=f"osm_way[{way.id}]",
            )
            waterway_type = sanitize_text(
                waterway_type,
                field_name="type",
                logger=logger,
                context=f"osm_way[{way.id}]",
            )

            if waterway_type is None:
                waterway_type = "stream"

            river = models.WaterBody(
                name=name,
                type=waterway_type,
                geom=f"SRID=4326;{wkt}",
            )
            new_rivers.append(river)

        if not new_rivers:
            logger.warning("No waterways found near (%s, %s)", lat, lon)
            return

        db.add_all(new_rivers)
        db.commit()
        logger.info(
            "OSM: %s water bodies saved (%s from relations)",
            len(new_rivers),
            len(way_relation_info),
        )
        print(
            f"Sucesso: {len(new_rivers)} corpos d'agua salvos "
            f"({len(way_relation_info)} via relations com nomes)."
        )
