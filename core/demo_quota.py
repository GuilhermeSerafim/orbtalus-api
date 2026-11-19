"""Shared, persistent admission limits for the public Render demo."""
from datetime import timedelta
from ipaddress import IPv6Address, ip_address, ip_network
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.errors import ServiceUnavailable
from core.geometry import validated_polygon
from database import get_engine


_INCREMENT = text("""
    INSERT INTO orbtalus_demo.daily_usage (day, bucket, used)
    VALUES (:day, :bucket, 1)
    ON CONFLICT (day, bucket) DO UPDATE
    SET used = daily_usage.used + 1
    WHERE daily_usage.used < :limit
    RETURNING used
""")


def demo_mode():
    return os.environ.get("RENDER") == "true"


def client_bucket(request):
    try:
        header, = request.headers.getlist("CF-Connecting-IP")
        if "%" in header:
            raise ValueError
        address = ip_address(header)
    except ValueError:
        raise ServiceUnavailable("DEMO_UNAVAILABLE") from None
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ip_network((address, 64), strict=False))
    return str(address)


def reserve(connection, now, bucket, ip_limit, global_limit):
    day = now.date()
    retry_after = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
    # Global first serializes admissions across workers and deployments. Any
    # rejection rolls back both changes before the caller can reach a provider.
    for key, limit, code, message in (
        ("global", global_limit, "DEMO_DAILY_LIMIT", "O limite diario do demo foi atingido."),
        (bucket, ip_limit, "DEMO_IP_LIMIT", "O limite diario deste IP foi atingido."),
    ):
        if connection.execute(_INCREMENT, {"day": day, "bucket": key, "limit": limit}).scalar_one_or_none() is None:
            raise HTTPException(429, {"code": code, "message": message},
                                headers={"Retry-After": str(retry_after)})
    connection.execute(text("DELETE FROM orbtalus_demo.daily_usage WHERE day < :cutoff"),
                       {"cutoff": day - timedelta(days=1)})


def admit_demo_request(request: Request, _polygon=Depends(validated_polygon)):
    if not demo_mode():
        return
    bucket = client_bucket(request)
    try:
        ip_limit = int(os.environ.get("DEMO_LIMIT_PER_IP", "3"))
        global_limit = int(os.environ.get("DEMO_LIMIT_GLOBAL", "20"))
        if not 1 <= ip_limit <= global_limit <= 1000:
            raise ValueError
        with get_engine().begin() as connection:
            now = connection.execute(text("SELECT clock_timestamp() AT TIME ZONE 'UTC'")).scalar_one()
            reserve(connection, now, bucket, ip_limit, global_limit)
    except (ValueError, SQLAlchemyError, ServiceUnavailable):
        raise ServiceUnavailable("DEMO_UNAVAILABLE") from None
    if os.environ.get("DEMO_PROVIDERS_ENABLED") != "1":
        raise ServiceUnavailable("DEMO_UNAVAILABLE")
