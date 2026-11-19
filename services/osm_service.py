import errno
import json
import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import monotonic
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import overpy
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

import models
from core.errors import MESSAGES, ServiceUnavailable
from core.validation import HYDROLOGY_RADIUS_KM, within_hydrology_radius
from database import SessionLocal
from services.text_sanitizer import sanitize_text

logger = logging.getLogger(__name__)

OSM_SOURCE = 'osm'
COVERAGE_TTL = timedelta(days=30)
FETCH_MARGIN_M = 1000


def covering_fetch_time(lat, lon, radius_m):
    """SQL expression for the newest complete fetch covering the requested disk."""
    receipt = models.HydrographyFetch
    point = f"SRID=4326;POINT({lon} {lat})"
    return select(func.max(receipt.fetched_at)).where(
        receipt.fetched_at >= func.now() - COVERAGE_TTL,
        func.ST_DistanceSphere(receipt.center, point) + radius_m <= receipt.radius_m,
    ).scalar_subquery()


def eligible_water_body(lat, lon, *, allow_undated=False):
    # Read the receipt and the water geometry in the same database snapshot.
    cutoff = covering_fetch_time(lat, lon, HYDROLOGY_RADIUS_KM * 1000)
    water = models.WaterBody
    observed = (water.source == OSM_SOURCE) & (water.fetched_at >= cutoff)
    if allow_undated:
        return observed | (water.source.is_(None) & cutoff.is_(None))
    return observed


def nearest_water_body(db, lat, lon, *, allow_undated=False, include_contact=False):
    water = models.WaterBody
    point = f"SRID=4326;POINT({lon} {lat})"
    columns = [water, func.ST_DistanceSphere(water.geom, point).label("dist_m")]
    if include_contact:
        columns.append(func.ST_AsText(func.ST_ClosestPoint(water.geom, point)).label("rio_ponto_wkt"))
    nearest = (
        db.query(*columns)
        .filter(eligible_water_body(lat, lon, allow_undated=allow_undated))
        .order_by("dist_m", water.id)
        .first()
    )
    if nearest is not None and within_hydrology_radius(nearest[1]):
        return nearest
    return None


def _exception_chain(error):
    """Types only: never serialize exception messages, args, SQL or response bodies."""
    types, seen = [], set()
    while error is not None and id(error) not in seen and len(types) < 8:
        seen.add(id(error))
        types.append(type(error).__name__)
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return {'exception_types': types, 'chain_truncated': error is not None}


def _open_transport_fields(error):
    # urllib wraps socket errors in .reason; it may also contain arbitrary text.
    reason = error.reason if isinstance(error, URLError) else error
    number = reason.errno if isinstance(reason, OSError) else None
    if not isinstance(number, int) or isinstance(number, bool) or not -(2**31) <= number < 2**31:
        number = None
    if isinstance(reason, (socket.gaierror, socket.herror)):
        category = 'dns'
    elif isinstance(reason, ssl.SSLError):
        category = 'tls'
    elif isinstance(reason, TimeoutError) or number == errno.ETIMEDOUT:
        category = 'timeout'
    elif isinstance(reason, ConnectionError) or number in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        category = 'connection'
    else:
        category = 'unknown'
    return {'transport_category': category, 'transport_errno': number}


def _diagnostic(code, observation, started, error=None):
    transport = {}
    if observation['stage'] == 'overpass_open' and isinstance(error, OSError) and not isinstance(error, HTTPError):
        transport = _open_transport_fields(error)
    return dict(code=code, **observation, **transport,
                error_code=(error.code if isinstance(error, ServiceUnavailable)
                            and error.code in MESSAGES else None),
                elapsed_ms=round((monotonic() - started) * 1000, 3),
                **_exception_chain(error))


def _log_diagnostic(event):
    # Message text survives the API's message-only formatter; no reliance on extra.
    logger.warning('OSM diagnostic %s', json.dumps(event, sort_keys=True))


def _http_status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


def _validate_elements(elements):
    """Overpy silently defaults missing elements/members and ignores unknown types."""
    if not isinstance(elements, list):
        raise ValueError('Incomplete Overpass response')
    for element in elements:
        kind = element.get('type')
        if kind not in ('node', 'way', 'relation') or type(element.get('id')) is not int:
            raise ValueError('Unexpected Overpass element')
        if kind == 'relation':
            members = element.get('members')
            if not isinstance(members, list) or any(
                member.get('type') not in ('node', 'way', 'relation')
                or type(member.get('ref')) is not int for member in members
            ):
                raise ValueError('Incomplete Overpass relation')


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
                data=urlencode({'data': query}).encode('ascii'),
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
                    'User-Agent': 'OrbTalus-local/0.1 (+https://github.com/GuilhermeSerafim/orbtalus; development hydrology)',
                },
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
                payload = json.loads(body, parse_float=Decimal)
                if 'remark' in payload:
                    # Preserve Overpy's typed timeout/refusal diagnostics.
                    return self.parser.parse_json(body)
                _validate_elements(payload.get('elements'))
                result = overpy.Result.from_json(payload, api=self.parser)
                observation['stage'] = 'overpass_close'
                return result
        except HTTPError as error:
            observation['http_status'] = _http_status(error.code)
            raise
        finally:
            observation['overpass_elapsed_ms'] = round((monotonic() - started) * 1000, 3)


@dataclass(frozen=True)
class Coverage:
    fetched_at: datetime
    origin: Literal['cache', 'overpass']


class OSMService:
    def __init__(self):
        self.api = None

    def fetch_and_save_rivers(self, lat: float, lon: float, radius_km: int = HYDROLOGY_RADIUS_KM):
        coverage = self.ensure_coverage(lat, lon, radius_km)
        return coverage.fetched_at if coverage is not None else None

    def ensure_coverage(self, lat: float, lon: float, radius_km: int = HYDROLOGY_RADIUS_KM) -> Coverage | None:
        db = None
        # Call-local, also when the same service/client is reused or interleaved.
        started = monotonic()
        observation = dict(stage='db_session', http_status=None, overpass_elapsed_ms=None)
        primary = None
        try:
            db = SessionLocal()
            return self._fetch_and_save_rivers(db, lat, lon, radius_km, observation, started)
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
        observation['stage'] = 'cache_lookup'
        radius_m = radius_km * 1000
        covered_at = db.query(covering_fetch_time(lat, lon, radius_m)).scalar()
        if covered_at is not None:
            return Coverage(covered_at, 'cache')

        fetched_at = db.scalar(select(func.clock_timestamp()))
        fetch_radius = radius_m + FETCH_MARGIN_M
        observation['stage'] = 'query_build'
        query = f"""
        [out:json][timeout:25];
        relation["waterway"](around:{fetch_radius},{lat},{lon})->.rivers;
        .rivers out body;
        (way["waterway"](around:{fetch_radius},{lat},{lon}); way(r.rivers);)->.ways;
        .ways out meta;
        node(w.ways); out skel qt;
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
                rel.tags.get("waterway"),
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

        ways = sorted(result.ways, key=lambda way: way.id)
        if way_relation_info.keys() - {way.id for way in ways}:
            raise ValueError('Missing waterway relation members')

        rows = []
        for way in ways:
            nodes = way.nodes
            if len(nodes) < 2 or any(
                not (-180 <= node.lon <= 180 and -90 <= node.lat <= 90) for node in nodes
            ):
                raise ValueError('Incomplete waterway geometry')
            coords = ",".join(f"{node.lon} {node.lat}" for node in nodes)
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

            if not waterway_type:
                raise ValueError('Way lacks a waterway tag or waterway relation')

            # Overpy parses OSM's UTC timestamps as naive datetimes.
            updated_at = getattr(way, 'attributes', {}).get('timestamp')
            rows.append(dict(
                name=name, type=waterway_type, geom=f"SRID=4326;{wkt}",
                source=OSM_SOURCE, source_id=f'way/{way.id}', fetched_at=fetched_at,
                source_updated_at=updated_at.replace(tzinfo=timezone.utc) if updated_at else None,
            ))

        if rows:
            observation['stage'] = 'db_upsert'
            table = models.WaterBody.__table__
            stmt = insert(table)
            changed = ('name', 'type', 'geom', 'source_updated_at', 'fetched_at')
            upsert = stmt.on_conflict_do_update(
                index_elements=[table.c.source, table.c.source_id],
                set_={column: stmt.excluded[column] for column in changed},
                where=table.c.fetched_at.is_(None) | (table.c.fetched_at < stmt.excluded.fetched_at),
            )
            db.execute(upsert, rows)
        else:
            _log_diagnostic(_diagnostic('OSM_ENRICHMENT_EMPTY', observation, started))

        # Keep only reusable receipts; the delete shares the successful refresh transaction.
        observation['stage'] = 'db_receipt'
        db.query(models.HydrographyFetch).filter(
            models.HydrographyFetch.fetched_at < fetched_at - COVERAGE_TTL
        ).delete(synchronize_session=False)
        db.add(models.HydrographyFetch(
            center=f"SRID=4326;POINT({lon} {lat})", radius_m=fetch_radius, fetched_at=fetched_at,
        ))
        observation['stage'] = 'db_commit'
        db.commit()
        return Coverage(fetched_at, 'overpass')
