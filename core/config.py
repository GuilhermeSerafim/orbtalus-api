"""Read only explicitly supplied environment variables, on demand."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

from core.errors import ServiceUnavailable


@dataclass(frozen=True)
class Settings:
    database_url: str | None = field(repr=False)
    openai_api_key: str | None = field(repr=False)
    gee_project: str | None
    cors_origins: tuple[str, ...]


def get_settings() -> Settings:
    raw_origins = os.environ.get("CORS_ORIGINS", "").strip()
    origins = tuple(part.strip() for part in raw_origins.split(",")) if raw_origins else ()
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            parsed.port  # Validate malformed ports too.
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and not parsed.netloc.endswith(":")
                     and not parsed.path and not parsed.query and not parsed.fragment
                     and "*" not in origin and not any(c.isspace() for c in origin)
                     and "?" not in origin and "#" not in origin)
        except ValueError:
            valid = False
        if not valid:
            raise ServiceUnavailable("CONFIG_UNAVAILABLE")
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        gee_project=os.environ.get("GEE_PROJECT") or None,
        cors_origins=origins,
    )
