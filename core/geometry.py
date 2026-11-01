"""Validate GeoJSON before opening request resources; never repair input."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from shapely import from_wkt
from shapely.errors import ShapelyError
from shapely.geometry import Point, Polygon, shape

from core.errors import MESSAGES, ServiceUnavailable
from core.validation import finite_number
from database import get_db


class DistanceReq(BaseModel):
    polygon: dict


def input_invalid():
    return HTTPException(422, detail={'code': 'INPUT_INVALID', 'message': MESSAGES['INPUT_INVALID']})


def _position(position):
    if not isinstance(position, (list, tuple)) or len(position) not in (2, 3):
        raise ValueError('Invalid coordinate dimension')
    numbers = [finite_number(value) for value in position]
    if not -180 <= numbers[0] <= 180 or not -90 <= numbers[1] <= 90:
        raise ValueError('Coordinate out of bounds')
    return numbers


def validated_polygon(req: DistanceReq) -> Polygon:
    try:
        data = req.polygon
        if data.get('type') == 'Feature':
            data = data.get('geometry')
        if not isinstance(data, dict) or data.get('type') != 'Polygon':
            raise ValueError('Polygon required')
        rings = data.get('coordinates')
        if not isinstance(rings, list) or not rings:
            raise ValueError('Empty polygon')
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError('Invalid ring')
            positions = [_position(position) for position in ring]
            if positions[0] != positions[-1] or len({tuple(p[:2]) for p in positions}) < 3:
                raise ValueError('Open or degenerate ring')
        geom = shape(data)
        if geom.is_empty or not geom.is_valid or geom.area <= 0:
            raise ValueError('Invalid polygon')
        return geom
    except (ServiceUnavailable, ShapelyError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise input_invalid() from None


def get_geo_db(geom: Polygon = Depends(validated_polygon)):
    # Explicit dependency edge: no session factory runs until geometry is valid.
    yield from get_db()


def river_coordinates(wkt):
    try:
        if not isinstance(wkt, str):
            raise ValueError('Point required')
        point = from_wkt(wkt)
        if not isinstance(point, Point) or point.is_empty or not point.is_valid:
            raise ValueError('Invalid point')
        coordinates = _position(point.coords[0])
        return coordinates[0], coordinates[1]
    except (ShapelyError, ValueError, TypeError, IndexError, OverflowError):
        raise ServiceUnavailable('DATA_UNAVAILABLE') from None
