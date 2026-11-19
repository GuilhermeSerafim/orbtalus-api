"""Import a local WGS84 GeoJSON into an already initialized original schema."""
import argparse
import json
import logging
import math
import os
from pathlib import Path
import sys

from shapely.geometry import shape
from sqlalchemy.exc import SQLAlchemyError

from core.db_target import load_contract, validate_target, require_target
from database import SessionLocal
from models import WaterBody
from services.text_sanitizer import sanitize_text

logger = logging.getLogger(__name__)
DEFAULT_INPUT = Path(__file__).resolve().parent / 'data/exportCurtibaTypeAllRivers.geojson'


def _coordinates(value):
    if not isinstance(value, list) or not value:
        raise ValueError('Invalid GeoJSON coordinates')
    if isinstance(value[0], list):
        for child in value:
            _coordinates(child)
    elif (len(value) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
          or not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90):
        raise ValueError('Invalid WGS84 coordinates')


def _geometry(value):
    if not isinstance(value, dict) or 'crs' in value:
        raise ValueError('Invalid GeoJSON geometry')
    if value.get('type') == 'GeometryCollection':
        geometries = value.get('geometries')
        if not isinstance(geometries, list) or not geometries:
            raise ValueError('Invalid geometry collection')
        for child in geometries:
            _geometry(child)
    else:
        _coordinates(value.get('coordinates'))
    try:
        geom = shape(value)
    except Exception:
        raise ValueError('Invalid GeoJSON geometry') from None
    if geom.is_empty or not geom.is_valid or geom.has_z:
        raise ValueError('Invalid GeoJSON geometry')
    return geom


def load_rivers(path):
    with Path(path).open('r', encoding='utf-8') as source:
        data = json.load(source)
    if (not isinstance(data, dict) or data.get('type') != 'FeatureCollection'
            or not isinstance(data.get('features'), list) or 'crs' in data):
        raise ValueError('Expected WGS84 FeatureCollection without CRS override')
    rivers = []
    for feature in data['features']:
        if not isinstance(feature, dict) or feature.get('type') != 'Feature' or 'crs' in feature:
            raise ValueError('Invalid GeoJSON feature')
        geom = _geometry(feature.get('geometry'))
        props = feature.get('properties')
        if props is None:
            props = {}
        if not isinstance(props, dict):
            raise ValueError('Invalid GeoJSON properties')
        name, waterway = props.get('name', 'Sem nome'), props.get('waterway', 'river')
        if any(v is not None and not isinstance(v, str) for v in (name, waterway)):
            raise ValueError('Invalid river name or type')
        rivers.append(WaterBody(name=sanitize_text(name, field_name='name'),
                                type=sanitize_text(waterway, field_name='type'),
                                geom=f'SRID=4326;{geom.wkt}'))
    return rivers


def migrate(path=None, *, target_contract=None):
    if target_contract is not None:
        validate_target(target_contract, os.environ.get('DATABASE_URL'))
    rivers = load_rivers(DEFAULT_INPUT if path is None else path)
    db = SessionLocal()
    try:
        if target_contract is not None:
            # A cached engine may predate the current environment configuration.
            validate_target(target_contract, db.get_bind().url)
            require_target(db.connection(), target_contract)
        for river in rivers:
            db.add(river)
        db.commit()
    except BaseException:
        try:
            db.rollback()
        except Exception:
            logger.error('River import rollback failed; preserving original failure')
        raise
    finally:
        try:
            db.close()
        except Exception:
            logger.error('River import close failed; preserving transaction outcome')
    return len(rivers)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--target-contract', required=True)
    args = parser.parse_args(argv)
    try:
        count = migrate(args.input, target_contract=load_contract(args.target_contract))
    except (ValueError, OSError, SQLAlchemyError):
        print('River import failed; verify input, explicit target and existing schema.', file=sys.stderr)
        return 1
    print(f'Imported {count} water bodies in one transaction.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
