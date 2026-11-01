"""Lazy database resources and shared request session lifecycle."""
from functools import lru_cache
import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import get_settings
from core.errors import ServiceUnavailable

logger = logging.getLogger(__name__)
Base = declarative_base()


@lru_cache(maxsize=1)
def get_engine():
    raw_url = get_settings().database_url
    try:
        if not raw_url:
            raise ValueError("Missing database URL")
        url = make_url(raw_url)
        if (url.drivername not in {"postgresql", "postgresql+psycopg2"}
                or not url.host or not url.database):
            raise ValueError("Explicit PostgreSQL target required")
        return create_engine(url, pool_pre_ping=True)
    except (ArgumentError, ValueError):
        raise ServiceUnavailable("CONFIG_UNAVAILABLE") from None


def SessionLocal():
    """Keep the callable API used by importers and the OSM cache."""
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())()


def _cleanup(db, operation, preserve_error):
    try:
        getattr(db, operation)()
    except Exception:
        if not preserve_error:
            raise
        logger.error("Database session %s failed; preserving prior outcome", operation)


def get_db():
    # Factory failures are distinct from exceptions thrown back through yield.
    try:
        db = SessionLocal()
    except SQLAlchemyError:
        raise ServiceUnavailable("DATABASE_UNAVAILABLE") from None

    failed = False
    try:
        yield db
    except BaseException as error:
        failed = True
        _cleanup(db, "rollback", preserve_error=True)
        if isinstance(error, SQLAlchemyError):
            raise ServiceUnavailable("DATABASE_UNAVAILABLE") from None
        raise
    finally:
        try:
            committed = db.info.get('risk_assessment_committed') is True
            _cleanup(db, "close", preserve_error=failed or committed)
        except SQLAlchemyError:
            raise ServiceUnavailable("DATABASE_UNAVAILABLE") from None
