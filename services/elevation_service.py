import requests

from core.errors import ServiceUnavailable
from core.validation import finite_number


def elevation_m(lat, lon):
    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        raise ServiceUnavailable("DATA_UNAVAILABLE") from None
    try:
        data = response.json()
    except ValueError:
        raise ServiceUnavailable("DATA_UNAVAILABLE") from None
    values = data.get("elevation") if isinstance(data, dict) else None
    if not isinstance(values, list) or len(values) != 1:
        raise ServiceUnavailable("DATA_UNAVAILABLE")
    return finite_number(values[0])
