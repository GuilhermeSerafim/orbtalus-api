"""Validation for measured numeric inputs, without coercing missing data to zero."""
import math

from core.errors import ServiceUnavailable


def finite_number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ServiceUnavailable("DATA_UNAVAILABLE")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ServiceUnavailable("DATA_UNAVAILABLE") from None
    if not math.isfinite(number):
        raise ServiceUnavailable("DATA_UNAVAILABLE")
    return number


def nonnegative_distance(value):
    number = finite_number(value)
    if number < 0:
        raise ServiceUnavailable('DATA_UNAVAILABLE')
    return number
