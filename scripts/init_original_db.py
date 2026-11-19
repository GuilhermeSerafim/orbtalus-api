"""Explicit original baseline. Importing this module never connects or runs DDL."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from core.db_target import load_contract, validate_target, inspect_target, validate_identity
from database import Base
import models  # Register only original metadata; no side effects.


def _type_name(column_type):
    value = str(column_type.compile(dialect=postgresql.dialect()))
    return 'DOUBLE PRECISION' if value == 'FLOAT' else value


def _default(value):
    if value is None:
        return None
    # Canonical public qualification only, for the entire nextval default.
    return re.sub(r"\Anextval\('(?:public|\"public\")\.([a-z_]+)'::regclass\)\Z",
                  r"nextval('\1'::regclass)", str(value))


def expected_manifest():
    tables, sequences = {}, []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        columns = []
        for column in table.columns:
            default = str(column.server_default.arg) if column.server_default is not None else None
            if column.primary_key and column.autoincrement in (True, 'auto'):
                default = f"nextval('{table.name}_{column.name}_seq'::regclass)"
                sequences.append({'name': f'{table.name}_{column.name}_seq', 'type': 'integer',
                                  'start': 1, 'minimum': 1, 'maximum': 2147483647,
                                  'increment': 1, 'cache': 1, 'cycle': False,
                                  'table': table.name, 'column': column.name})
            columns.append({'name': column.name, 'type': _type_name(column.type),
                            'nullable': column.nullable, 'default': default})
        indexes = [{'name': index.name, 'columns': [c.name for c in index.columns],
                    'unique': bool(index.unique),
                    'method': index.dialect_options['postgresql'].get('using') or 'btree',
                    'include': [], 'where': None} for index in table.indexes]
        tables[table.name] = {'columns': columns,
                             'primary_key': {'name': f'{table.name}_pkey', 'columns': ['id']},
                             'indexes': sorted(indexes, key=lambda i: i['name']),
                             'foreign_keys': [], 'checks': [], 'unique_constraints': []}
    return {'format': 'orbtalus-original-v1', 'schema': 'public', 'tables': tables,
            'sequences': sorted(sequences, key=lambda s: s['name']),
            'python_defaults': {'risk_assessments.created_at': 'datetime.utcnow'}}


def schema_objects(connection):
    """Inventory every schema-dependent object, excluding PostGIS and its internal objects."""
    return [dict(row) for row in connection.execute(text('''
        WITH RECURSIVE extension_objects(classid, objid) AS (
          SELECT 'pg_extension'::regclass::oid, e.oid FROM pg_extension e WHERE e.extname='postgis'
          UNION
          SELECT d.classid, d.objid FROM pg_depend d JOIN extension_objects e
            ON d.refclassid=e.classid AND d.refobjid=e.objid WHERE d.deptype IN ('e','i')
        )
        SELECT DISTINCT d.classid::regclass::text AS kind, obj.name,
               c.relkind::text AS relation_kind
        FROM pg_depend d
        JOIN pg_namespace n ON d.refclassid='pg_namespace'::regclass AND d.refobjid=n.oid
        CROSS JOIN LATERAL pg_identify_object(d.classid,d.objid,d.objsubid) obj
        LEFT JOIN pg_class c ON d.classid='pg_class'::regclass AND d.objid=c.oid
        WHERE n.nspname='public' AND NOT EXISTS (
          SELECT 1 FROM extension_objects e WHERE e.classid=d.classid AND e.objid=d.objid)
        ORDER BY kind, name
    ''')).mappings()]


def _check_objects(objects, expected):
    relations = {}
    for name, table in expected['tables'].items():
        relations[name] = 'r'
        relations[table['primary_key']['name']] = 'i'
        relations.update({index['name']: 'i' for index in table['indexes']})
    relations.update({s['name']: 'S' for s in expected['sequences']})
    types = {name for table in expected['tables'] for name in (table, '_' + table)}
    for obj in objects:
        if obj['kind'] == 'pg_class' and relations.get(obj['name']) == obj['relation_kind']:
            continue
        if obj['kind'] == 'pg_type' and obj['name'] in types:
            continue
        raise ValueError('Unexpected object in public schema')


def read_manifest(connection):
    """Reflect the live schema, including server defaults and owned serial sequences."""
    inspector = inspect(connection)
    expected = expected_manifest()
    tables = {}
    for name in expected['tables']:
        reflected_columns = inspector.get_columns(name, schema='public')
        if any(c.get('computed') or c.get('identity') for c in reflected_columns):
            raise ValueError('Computed and identity columns are not part of the original schema')
        columns = [{'name': c['name'], 'type': _type_name(c['type']),
                    'nullable': c['nullable'], 'default': _default(c.get('default'))}
                   for c in reflected_columns]
        pk = inspector.get_pk_constraint(name, schema='public')
        indexes = []
        for index in inspector.get_indexes(name, schema='public'):
            opts = index.get('dialect_options', {})
            if (index.get('column_sorting') or any(opts.get(key) for key in (
                    'postgresql_invalid', 'postgresql_nulls_not_distinct',
                    'postgresql_ops', 'postgresql_with'))):
                raise ValueError('Unexpected index options or invalid index')
            indexes.append({'name': index['name'], 'columns': index['column_names'],
                            'unique': bool(index['unique']),
                            'method': opts.get('postgresql_using', 'btree'),
                            'include': opts.get('postgresql_include', []),
                            'where': opts.get('postgresql_where')})
        tables[name] = {'columns': columns,
                        'primary_key': {'name': pk['name'], 'columns': pk['constrained_columns']},
                        'indexes': sorted(indexes, key=lambda i: i['name']),
                        'foreign_keys': inspector.get_foreign_keys(name, schema='public'),
                        'checks': inspector.get_check_constraints(name, schema='public'),
                        'unique_constraints': inspector.get_unique_constraints(name, schema='public')}
    sequences = [dict(row) for row in connection.execute(text('''
        SELECT s.relname AS name, p.seqtypid::regtype::text AS type,
               p.seqstart AS start, p.seqmin AS minimum, p.seqmax AS maximum,
               p.seqincrement AS increment, p.seqcache AS cache, p.seqcycle AS cycle,
               t.relname AS table, a.attname AS column
        FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace
        JOIN pg_sequence p ON p.seqrelid=s.oid
        LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid
          AND d.refclassid='pg_class'::regclass AND d.deptype='a'
        LEFT JOIN pg_class t ON t.oid=d.refobjid
        LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
        WHERE n.nspname='public' AND s.relname IN ('water_bodies_id_seq','risk_assessments_id_seq')
        ORDER BY s.relname
    ''')).mappings()]
    return {'format': 'orbtalus-original-v1', 'schema': 'public', 'tables': tables,
            'sequences': sequences, 'python_defaults': expected['python_defaults']}


def run(contract, *, url, initialize=False, manifest=None, before_commit=None):
    target = validate_target(contract, url)
    expected = expected_manifest()
    if not initialize and manifest != expected:
        raise ValueError('Supplied manifest does not match original metadata')
    engine = create_engine(target)
    try:
        with engine.connect() as connection:
            with connection.begin():
                if not initialize:
                    connection.execute(text('SET TRANSACTION READ ONLY'))
                validate_identity(inspect_target(connection), contract)
                objects = schema_objects(connection)
                if initialize:
                    if objects:
                        raise ValueError('Initialization requires an empty public schema except PostGIS')
                    Base.metadata.create_all(connection, checkfirst=False)
                else:
                    _check_objects(objects, expected)
                actual = read_manifest(connection)
                if actual != expected:
                    raise ValueError('Database manifest does not match original metadata')
                if initialize and before_commit is not None:
                    before_commit(actual)
                return actual
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--initialize', action='store_true')
    modes.add_argument('--validate-only', action='store_true')
    parser.add_argument('--target-contract', required=True)
    parser.add_argument('--manifest-out')
    parser.add_argument('--manifest')
    args = parser.parse_args(argv)
    if args.initialize and (not args.manifest_out or args.manifest):
        parser.error('--initialize requires only --manifest-out')
    if args.validate_only and (not args.manifest or args.manifest_out):
        parser.error('--validate-only requires only --manifest')
    try:
        contract = load_contract(args.target_contract)
        supplied = json.loads(Path(args.manifest).read_text(encoding='utf-8')) if args.manifest else None
        if args.initialize:
            # Reserve output exclusively before any database write. Retain on failure.
            with Path(args.manifest_out).open('x', encoding='utf-8') as output:
                def persist_manifest(actual):
                    json.dump(actual, output, ensure_ascii=False, indent=2)
                    output.write('\n')
                    output.flush()
                    # Close can report a deferred IO error too. Complete it while
                    # still inside the DDL transaction so errors cause rollback.
                    output.close()
                run(contract, url=os.environ.get('DATABASE_URL'), initialize=True,
                    before_commit=persist_manifest)
        else:
            run(contract, url=os.environ.get('DATABASE_URL'), manifest=supplied)
    except (ValueError, OSError, SQLAlchemyError):
        print('Original schema command failed; verify contract, schema and output artifact.', file=sys.stderr)
        return 1
    print('Original schema initialized.' if args.initialize else 'Original schema validated (read only).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
