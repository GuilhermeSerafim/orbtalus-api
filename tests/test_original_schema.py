import copy
import importlib.util
import os
import unittest
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from offline_guard import offline_boundaries

CONTRACT = {'host': 'db.example.invalid', 'port': 55442, 'database': 'disposable_test',
            'schema': 'public', 'purpose': 'disposable-original-baseline'}
URL = 'postgresql+psycopg2://owner:unused@db.example.invalid:55442/disposable_test'


class OriginalSchemaTests(unittest.TestCase):
    def setUp(self):
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])

    def baseline(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.init_original_db'),
                             'Explicit guarded original baseline is required')
        from scripts import init_original_db
        return init_original_db

    def test_target_mismatch_and_connection_overrides_refused_before_engine(self):
        baseline = self.baseline()
        for url in (None, URL.replace('55442', '5432'), URL.replace('disposable_test', 'preview'),
                    URL + '?host=preview', URL.replace('db.example.invalid', 'other.invalid')):
            with self.subTest(url=url), patch.object(baseline, 'create_engine') as engine:
                with self.assertRaises(ValueError):
                    baseline.run(CONTRACT, url=url, initialize=True)
                engine.assert_not_called()

    def test_original_manifest_contains_exact_schema_and_python_default(self):
        baseline = self.baseline()
        manifest = baseline.expected_manifest()
        tables = manifest['tables']
        self.assertEqual(set(tables), {'water_bodies', 'risk_assessments'})
        self.assertEqual([c['name'] for c in tables['water_bodies']['columns']],
                         ['id', 'name', 'type', 'geom'])
        self.assertEqual(len(tables['risk_assessments']['columns']), 12)
        created = tables['risk_assessments']['columns'][-1]
        self.assertEqual((created['name'], created['nullable'], created['default']),
                         ('created_at', False, None))
        self.assertEqual(manifest['python_defaults'], {'risk_assessments.created_at': 'datetime.utcnow'})
        self.assertEqual(tables['water_bodies']['columns'][-1]['type'], 'geometry(GEOMETRY,4326)')
        self.assertEqual(len(manifest['sequences']), 2)

    def test_inherited_libpq_redirection_refused_before_engine_and_import_session(self):
        baseline = self.baseline()
        import migrate_rivers
        for overrides in ({'PGHOSTADDR': '192.0.2.123'}, {'PGSERVICE': 'other-target'},
                          {'PGSERVICEFILE': 'unread-test-service.conf', 'PGSERVICE': 'other-target'}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, {'DATABASE_URL': URL, **overrides}, clear=True), \
                    patch.object(baseline, 'create_engine') as engine, \
                    patch.object(migrate_rivers, 'SessionLocal') as session, \
                    patch.object(migrate_rivers, 'load_rivers', return_value=[]):
                with self.assertRaises(ValueError):
                    baseline.run(CONTRACT, url=URL, initialize=True)
                engine.assert_not_called()
                with self.assertRaises(ValueError):
                    migrate_rivers.migrate(target_contract=CONTRACT)
                session.assert_not_called()

    def test_manifest_write_flush_close_failure_rolls_back_before_commit(self):
        import io
        baseline = self.baseline()
        for stage in ('write', 'flush', 'close', None):
            with self.subTest(stage=stage):
                engine, connection, ddl = self.configure_db(baseline)
                output = MagicMock()
                output.__enter__.return_value = output
                if stage:
                    getattr(output, stage).side_effect = OSError('private output path')
                else:
                    def transaction_exit(*args):
                        output.flush.assert_called_once()
                        output.close.assert_called_once()
                        return False
                    connection.begin.return_value.__exit__.side_effect = transaction_exit
                error = io.StringIO()
                with patch.object(baseline, 'load_contract', return_value=CONTRACT), \
                        patch.object(baseline, 'read_manifest', return_value=baseline.expected_manifest()), \
                        patch.object(Path, 'open', return_value=output) as opened, \
                        patch.dict(os.environ, {'DATABASE_URL': URL}, clear=True), \
                        patch('sys.stderr', error):
                    code = baseline.main(['--initialize', '--target-contract', 'unused.json',
                                          '--manifest-out', 'unused-manifest.json'])
                self.assertEqual(code, 1 if stage else 0)
                opened.assert_called_once_with('x', encoding='utf-8')
                transaction_error = connection.begin.return_value.__exit__.call_args.args[0]
                self.assertIs(transaction_error, OSError if stage else None)
                self.assertNotIn('private', error.getvalue())
                ddl.assert_called_once()
                engine.dispose.assert_called_once()

    def configure_db(self, baseline, objects=None, postgis=True, database='disposable_test', schema='public'):
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        connection.begin.return_value.__enter__.return_value = MagicMock()
        self.enterContext(patch.object(baseline, 'create_engine', return_value=engine))
        self.enterContext(patch.object(baseline, 'inspect_target', return_value={
            'database': database, 'schema': schema, 'schemas': ['public'], 'postgis': postgis}))
        self.enterContext(patch.object(baseline, 'schema_objects', return_value=objects or []))
        ddl = self.enterContext(patch.object(baseline.Base.metadata, 'create_all'))
        return engine, connection, ddl

    def test_guards_refuse_before_ddl(self):
        baseline = self.baseline()
        for condition in ({'postgis': False}, {'database': 'preview'}, {'schema': 'shadow'},
                          {'objects': [{'kind': 'pg_proc', 'name': 'unknown_function'}]},
                          {'objects': [{'kind': 'pg_class', 'name': 'water_bodies'}]}):
            with self.subTest(condition=condition):
                with patch.object(baseline, 'create_engine'):
                    _, _, ddl = self.configure_db(baseline, **condition)
                    with self.assertRaises(ValueError):
                        baseline.run(CONTRACT, url=URL, initialize=True)
                    ddl.assert_not_called()

    def test_initialize_exports_reflected_manifest_and_validate_only_never_ddl(self):
        baseline = self.baseline()
        _, connection, ddl = self.configure_db(baseline)
        manifest = baseline.expected_manifest()
        with patch.object(baseline, 'read_manifest', return_value=manifest):
            self.assertEqual(baseline.run(CONTRACT, url=URL, initialize=True), manifest)
            ddl.assert_called_once_with(connection, checkfirst=False)
            ddl.reset_mock()
            self.assertEqual(baseline.run(CONTRACT, url=URL, initialize=False, manifest=manifest), manifest)
            ddl.assert_not_called()
        self.assertTrue(any('READ ONLY' in str(c.args[0]) for c in connection.execute.call_args_list))

    def test_manifest_drift_refused_and_unknown_objects_refused_on_validate(self):
        baseline = self.baseline()
        _, _, ddl = self.configure_db(baseline)
        expected = baseline.expected_manifest()
        changed = copy.deepcopy(expected)
        changed['tables']['risk_assessments']['columns'][-1]['default'] = 'now()'
        for actual, supplied in ((changed, expected), (expected, changed)):
            with patch.object(baseline, 'read_manifest', return_value=actual):
                with self.assertRaises(ValueError):
                    baseline.run(CONTRACT, url=URL, initialize=False, manifest=supplied)
        ddl.assert_not_called()

    def test_alembic_missing_url_refuses_before_engine_or_dotenv(self):
        import runpy
        import sqlalchemy
        from alembic import context
        from alembic.config import Config
        cfg = Config()
        cfg.set_main_option('sqlalchemy.url', URL)
        with patch.dict(os.environ, {}, clear=True), patch.object(context, 'config', cfg, create=True), \
                patch('dotenv.load_dotenv') as dotenv, patch.object(sqlalchemy, 'engine_from_config') as engine:
            with self.assertRaises((ValueError, RuntimeError)):
                runpy.run_path('alembic/env.py')
        dotenv.assert_not_called()
        engine.assert_not_called()

    def test_reflected_manifest_includes_actual_defaults_indexes_and_sequences(self):
        baseline = self.baseline()
        from models import Base
        expected = baseline.expected_manifest()
        inspector = MagicMock()
        inspector.get_columns.side_effect = lambda name, schema: [
            {**c, 'type': Base.metadata.tables[name].c[c['name']].type}
            for c in expected['tables'][name]['columns']]
        inspector.get_pk_constraint.side_effect = lambda name, schema: {
            'name': expected['tables'][name]['primary_key']['name'], 'constrained_columns': ['id']}
        inspector.get_indexes.side_effect = lambda name, schema: [
            {'name': i['name'], 'column_names': i['columns'], 'unique': i['unique'],
             'dialect_options': {'postgresql_using': i['method']}}
            for i in expected['tables'][name]['indexes']]
        for method in ('get_foreign_keys', 'get_check_constraints', 'get_unique_constraints'):
            getattr(inspector, method).return_value = []
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value = expected['sequences']
        with patch.object(baseline, 'inspect', return_value=inspector):
            self.assertEqual(baseline.read_manifest(connection), expected)
            for option in ('postgresql_invalid', 'postgresql_nulls_not_distinct'):
                with self.subTest(option=option):
                    original_indexes = inspector.get_indexes.side_effect
                    inspector.get_indexes.side_effect = lambda name, schema: [
                        {'name': 'ix_water_bodies_id', 'column_names': ['id'], 'unique': False,
                         'dialect_options': {option: True}}]
                    with self.assertRaises(ValueError):
                        baseline.read_manifest(connection)
                    inspector.get_indexes.side_effect = original_indexes
            inspector.get_columns.side_effect = None
            inspector.get_columns.return_value = [{'name': 'unexpected', 'type': Base.metadata.tables['water_bodies'].c.id.type,
                                                  'nullable': True, 'default': '7'}]
            self.assertNotEqual(baseline.read_manifest(connection), expected)
            inspector.get_columns.return_value[0]['computed'] = {'sqltext': '7', 'persisted': True}
            with self.assertRaises(ValueError):
                baseline.read_manifest(connection)
        self.assertIn('pg_sequence', str(connection.execute.call_args.args[0]))

    def test_validate_only_unknown_objects_and_wrong_index_kind_refuse_without_ddl(self):
        baseline = self.baseline()
        _, _, ddl = self.configure_db(baseline)
        for obj in ({'kind': 'pg_proc', 'name': 'unknown', 'relation_kind': None},
                    {'kind': 'pg_class', 'name': 'water_bodies', 'relation_kind': 'v'},
                    {'kind': 'pg_type', 'name': 'unexpected', 'relation_kind': None}):
            with self.subTest(obj=obj), patch.object(baseline, 'schema_objects', return_value=[obj]):
                with self.assertRaises(ValueError):
                    baseline.run(CONTRACT, url=URL, manifest=baseline.expected_manifest())
        ddl.assert_not_called()

    def test_ddl_or_reflection_failure_rolls_back_and_disposes(self):
        baseline = self.baseline()
        engine, connection, ddl = self.configure_db(baseline)
        ddl.side_effect = RuntimeError('simulated DDL failure')
        with self.assertRaises(RuntimeError):
            baseline.run(CONTRACT, url=URL, initialize=True)
        self.assertIs(connection.begin.return_value.__exit__.call_args.args[0], RuntimeError)
        engine.dispose.assert_called_once()

    def test_cli_validate_only_writes_no_files_and_existing_output_refuses_before_db(self):
        import json
        baseline = self.baseline()
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        contract = folder / 'target.json'
        manifest = folder / 'manifest.json'
        contract.write_text(json.dumps(CONTRACT), encoding='utf-8')
        manifest.write_text(json.dumps(baseline.expected_manifest()), encoding='utf-8')
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        with patch.object(baseline, 'run') as run:
            self.assertEqual(baseline.main(['--validate-only', '--target-contract', str(contract),
                                            '--manifest', str(manifest)]), 0)
            run.assert_called_once()
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})
        with patch.object(baseline, 'run') as run:
            self.assertEqual(baseline.main(['--initialize', '--target-contract', str(contract),
                                            '--manifest-out', str(manifest)]), 1)
            run.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_contract_rejects_credentials_unknown_fields_and_nonpublic_schema(self):
        from core.db_target import validate_target
        for change in ({'password': 'must-not-be-here'}, {'schema': 'preview'}, {'port': True},
                       {'purpose': 'production'}, {'port': None}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_target({**CONTRACT, **change}, URL)

    def test_commit_failure_retains_complete_manifest_without_claiming_success(self):
        import io
        import json
        from sqlalchemy.exc import SQLAlchemyError
        baseline = self.baseline()
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        output = folder / 'retained-manifest.json'
        _, connection, _ = self.configure_db(baseline)
        expected = baseline.expected_manifest()
        def failed_commit(*args):
            # Readback here also proves flush/close preceded the commit attempt.
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), expected)
            raise SQLAlchemyError('private connection details')
        connection.begin.return_value.__exit__.side_effect = failed_commit
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch.object(baseline, 'load_contract', return_value=CONTRACT), \
                patch.object(baseline, 'read_manifest', return_value=expected), \
                patch.dict(os.environ, {'DATABASE_URL': URL}, clear=True), \
                patch('sys.stderr', stderr), patch('sys.stdout', stdout):
            code = baseline.main(['--initialize', '--target-contract', 'unused.json',
                                  '--manifest-out', str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), expected)
        self.assertEqual(stdout.getvalue(), '')
        self.assertNotIn('private', stderr.getvalue())
