"""Upgrade an explicitly identified, initialized OrbTalus database in one transaction."""
import argparse
import os
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

import models
from core.db_target import load_contract, require_target, validate_target
from scripts.init_original_db import _check_objects, expected_manifest, read_manifest, schema_objects


def verify_schema(connection, expected):
    _check_objects(schema_objects(connection), expected)
    if read_manifest(connection, expected) != expected:
        raise ValueError('Hydrography upgrade requires an exact supported schema')


def upgrade(contract, *, url, runtime_role=None):
    target = validate_target(contract, url, purpose='hydrography-cache-upgrade')
    engine = create_engine(target)
    try:
        with engine.begin() as connection:
            require_target(connection, contract)
            # Keep concurrent migration runs from inspecting partially completed DDL.
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('orbtalus:hydrography:v2'))"))
            if connection.scalar(text("SELECT to_regclass('public.hydrography_fetches') IS NULL")):
                verify_schema(connection, expected_manifest())
                connection.execute(text("""
                    ALTER TABLE public.water_bodies
                      ADD COLUMN source varchar,
                      ADD COLUMN source_id varchar,
                      ADD COLUMN source_updated_at timestamptz,
                      ADD COLUMN fetched_at timestamptz
                """))
                connection.execute(text("""
                    CREATE UNIQUE INDEX uq_water_bodies_source_id
                    ON public.water_bodies (source, source_id)
                """))
                models.HydrographyFetch.__table__.create(connection)
            verify_schema(connection, expected_manifest(models.Base.metadata, 'orbtalus-hydrography-v2'))
            if runtime_role is not None:
                role = connection.dialect.identifier_preparer.quote_identifier(runtime_role)
                connection.exec_driver_sql(
                    'GRANT UPDATE (name, type, geom, source_updated_at, fetched_at) '
                    f'ON public.water_bodies TO {role}')
                connection.exec_driver_sql(f'GRANT SELECT, INSERT, DELETE ON public.hydrography_fetches TO {role}')
                connection.exec_driver_sql(f'GRANT USAGE ON SEQUENCE public.hydrography_fetches_id_seq TO {role}')
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-contract', required=True)
    parser.add_argument('--runtime-role', help='Existing restricted API role that receives cache permissions.')
    args = parser.parse_args(argv)
    try:
        upgrade(load_contract(args.target_contract), url=os.environ.get('DATABASE_URL'),
                runtime_role=args.runtime_role)
    except (ValueError, OSError, SQLAlchemyError):
        print('Hydrography upgrade failed. Verify target, schema, owner access and role.', file=sys.stderr)
        return 1
    print('Hydrography schema validated and transaction committed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
