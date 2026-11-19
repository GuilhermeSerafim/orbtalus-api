"""Explicit disposable target contract shared by administrative commands."""
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url


def load_contract(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_target(contract, raw_url, *, purpose='disposable-original-baseline'):
    """Validate before engine construction; never interpolate target values into SQL."""
    # These libpq defaults can redirect an otherwise exact host/port URL.
    # Inspect presence only; never read service files or include values in errors.
    if any(os.environ.get(key) for key in ('PGHOSTADDR', 'PGSERVICE')):
        raise ValueError('Inherited libpq target overrides are not allowed')
    required = {'host', 'port', 'database', 'schema', 'purpose'}
    if (not isinstance(contract, dict) or set(contract) != required
            or contract.get('schema') != 'public'
            or contract.get('purpose') != purpose
            or type(contract.get('port')) is not int or not 1 <= contract['port'] <= 65535
            or any(not isinstance(contract.get(k), str) or not contract[k].strip()
                   for k in ('host', 'database'))):
        raise ValueError('Invalid disposable target contract')
    try:
        url = make_url(raw_url)
        valid = (url.drivername in {'postgresql', 'postgresql+psycopg2'}
                 and url.host == contract['host'] and url.port == contract['port']
                 and url.database == contract['database'] and not url.query)
    except Exception:
        valid = False
    if not valid:
        raise ValueError('Explicit database URL does not match target contract')
    return url


def inspect_target(connection):
    return dict(connection.execute(text('''
        SELECT current_database() AS database, current_schema() AS schema,
               current_schemas(false) AS schemas,
               EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                       WHERE e.extname='postgis' AND n.nspname='public') AS postgis
    ''')).mappings().one())


def require_target(connection, contract):
    validate_identity(inspect_target(connection), contract)


def validate_identity(actual, contract):
    if (actual['database'] != contract['database'] or actual['schema'] != 'public'
            or actual['schemas'] != ['public'] or actual['postgis'] is not True):
        raise ValueError('Database identity, public search path or existing PostGIS does not match')
