import json
import logging
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import overpy
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from core.errors import MESSAGES, ServiceUnavailable
from database import SessionLocal
from services.text_sanitizer import sanitize_text

logger = logging.getLogger(__name__)


def _exception_chain(error):
    """Types only: never serialize exception messages, args, SQL or response bodies."""
    types, seen = [], set()
    while error is not None and id(error) not in seen and len(types) < 8:
        seen.add(id(error))
        types.append(type(error).__name__)
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return {'exception_types': types, 'chain_truncated': error is not None}


def _diagnostic(code, observation, started, error=None):
    return dict(code=code, **observation,
                error_code=(error.code if isinstance(error, ServiceUnavailable)
                            and error.code in MESSAGES else None),
                elapsed_ms=round((monotonic() - started) * 1000, 3),
                **_exception_chain(error))


def _log_diagnostic(event):
    # Message text survives the API's message-only formatter; no reliance on extra.
    logger.warning('OSM diagnostic %s', json.dumps(event, sort_keys=True))


def _http_status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


class _OverpassClient:
    def __init__(self):
        self.parser = overpy.Overpass()

    def query(self, query, *, diagnostic=None):
        observation = diagnostic if diagnostic is not None else {}
        observation.update(stage='overpass_request', http_status=None, overpass_elapsed_ms=None)
        started = monotonic()
        try:
            request = Request(
                'https://overpass-api.de/api/interpreter',
                data=query.encode('utf-8'),
                headers={'User-Agent': 'OrbTalus-local/0.1 (+https://github.com/GuilhermeSerafim/orbtalus; development hydrology)'},
            )
            # QL timeout is server-side; this is a separate socket inactivity limit.
            # No retry, fallback endpoint or global opener mutation on refusal.
            observation['stage'] = 'overpass_open'
            with urlopen(request, timeout=45) as response:
                observation.update(stage='overpass_content_type', http_status=_http_status(response.getcode()))
                if response.headers.get_content_type() != 'application/json':
                    raise overpy.exception.OverpassUnknownContentType(response.headers.get('Content-Type'))
                observation['stage'] = 'overpass_read'
                body = response.read()
                observation['stage'] = 'overpass_parse'
                result = self.parser.parse_json(body)
                observation['stage'] = 'overpass_close'
                return result
        except HTTPError as error:
            observation['http_status'] = _http_status(error.code)
            raise
        finally:
            observation['overpass_elapsed_ms'] = round((monotonic() - started) * 1000, 3)


class OSMService:
    def __init__(self):
        self.api = None

    def fetch_and_save_rivers(self, lat: float, lon: float, radius_km: int = 5):
        db = None
        # Call-local, also when the same service/client is reused or interleaved.
        started = monotonic()
        observation = dict(stage='db_session', http_status=None, overpass_elapsed_ms=None)
        primary = None
        try:
            db = SessionLocal()
            self._fetch_and_save_rivers(db, lat, lon, radius_km, observation, started)
        except Exception as error:
            primary = _diagnostic('OSM_ENRICHMENT_FAILED', observation, started, error)
            _log_diagnostic(primary)
            if db is not None:
                try:
                    db.rollback()
                except Exception as cleanup_error:
                    event = _diagnostic('OSM_CACHE_ROLLBACK_FAILED',
                                        dict(observation, stage='db_rollback'), started, cleanup_error)
                    _log_diagnostic(dict(event, primary=primary))
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as cleanup_error:
                    event = _diagnostic('OSM_CACHE_CLOSE_FAILED',
                                        dict(observation, stage='db_close'), started, cleanup_error)
                    _log_diagnostic(dict(event, primary=primary))

    def _fetch_and_save_rivers(
        self, db: Session, lat: float, lon: float, radius_km: int, observation, started
    ):
        """
        Fetch waterways from OpenStreetMap and save to PostGIS.

        Handles both individual ways AND relations (large rivers like
        Tiete/Pinheiros are modeled as relations in OSM, with the name
        tag on the relation, not on individual way segments).
        """
        # 1. Cache check: skip if area is already well-mapped.
        observation['stage'] = 'cache_lookup'
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
        observation['stage'] = 'query_build'
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
        if self.api is None:
            observation['stage'] = 'client_init'
            self.api = _OverpassClient()
        observation['stage'] = 'overpass_query'
        result = self.api.query(query, diagnostic=observation)

        # 3. Build relation name/type lookup for member ways.
        observation['stage'] = 'hydrology_build'
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
            _log_diagnostic(_diagnostic('OSM_ENRICHMENT_EMPTY', observation, started))
            return

        observation['stage'] = 'db_add_all'
        db.add_all(new_rivers)
        observation['stage'] = 'db_commit'
        db.commit()
        observation['stage'] = 'post_commit_log'
        logger.info(
            "OSM: %s water bodies saved (%s from relations)",
            len(new_rivers),
            len(way_relation_info),
        )
        print(
            f"Sucesso: {len(new_rivers)} corpos d'agua salvos "
            f"({len(way_relation_info)} via relations com nomes)."
        )
