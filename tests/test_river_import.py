import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from offline_guard import offline_boundaries

with offline_boundaries():
    import migrate_rivers as importer


FEATURES = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'properties': {'name': 'Rio teste', 'waterway': 'river'},
     'geometry': {'type': 'LineString', 'coordinates': [[-46, -23], [-46.1, -23.1]]}}]}


class RiverImportTests(unittest.TestCase):
    def setUp(self):
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.folder / 'rivers.geojson'
        self.path.write_text(json.dumps(FEATURES), encoding='utf-8')
        self.db = MagicMock()
        self.factory = self.enterContext(patch.object(importer, 'SessionLocal', return_value=self.db))

    def test_explicit_file_from_another_cwd_one_commit_and_close(self):
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            self.assertEqual(importer.migrate(self.path), 1)
        finally:
            os.chdir(previous)
        river = self.db.add.call_args.args[0]
        self.assertEqual((river.name, river.type), ('Rio teste', 'river'))
        self.assertEqual(river.geom, 'SRID=4326;LINESTRING (-46 -23, -46.1 -23.1)')
        self.db.commit.assert_called_once()
        self.db.close.assert_called_once()
        self.db.rollback.assert_not_called()

    def test_default_file_is_relative_to_module(self):
        import io
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            with patch('pathlib.Path.open', autospec=True,
                       return_value=io.StringIO(json.dumps(FEATURES))) as opened:
                importer.migrate()
        finally:
            os.chdir(previous)
        self.assertEqual(opened.call_args.args, (importer.DEFAULT_INPUT, 'r'))
        self.assertEqual(importer.DEFAULT_INPUT,
                         Path(importer.__file__).resolve().parent / 'data/exportCurtibaTypeAllRivers.geojson')

    def test_invalid_input_fails_before_session_and_before_partial_adds(self):
        for geometry in (None, {'type': 'LineString', 'coordinates': [[False, -23], [-46, -23]]},
                         {'type': 'LineString', 'coordinates': [[181, 0], [0, 0]]},
                         {'type': 'LineString', 'coordinates': [[0, 0], [float('nan'), 0]]}):
            with self.subTest(geometry=geometry):
                data = copy.deepcopy(FEATURES)
                bad = copy.deepcopy(data['features'][0])
                bad['geometry'] = geometry
                data['features'].append(bad)
                self.path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    importer.migrate(self.path)
                self.factory.assert_not_called()
                self.db.add.assert_not_called()

    def test_write_failures_rollback_close_and_preserve_original_exception(self):
        for operation in ('add', 'commit'):
            with self.subTest(operation=operation):
                self.db.reset_mock(side_effect=True)
                error = RuntimeError('original failure')
                getattr(self.db, operation).side_effect = error
                self.db.rollback.side_effect = RuntimeError('rollback failure')
                self.db.close.side_effect = RuntimeError('close failure')
                with self.assertRaises(RuntimeError) as raised:
                    importer.migrate(self.path)
                self.assertIs(raised.exception, error)
                self.db.rollback.assert_called_once()
                self.db.close.assert_called_once()

    def test_confirmed_commit_survives_close_failure(self):
        self.db.close.side_effect = RuntimeError('private close')
        self.assertEqual(importer.migrate(self.path), 1)
        self.db.commit.assert_called_once()

    def test_missing_file_and_factory_failure_do_not_write(self):
        with self.assertRaises(FileNotFoundError):
            importer.migrate(self.folder / 'absent.geojson')
        self.factory.assert_not_called()
        self.factory.side_effect = RuntimeError('factory')
        with self.assertRaises(RuntimeError):
            importer.migrate(self.path)
        self.db.add.assert_not_called()

    def test_contract_mismatch_refuses_before_session(self):
        from test_original_schema import CONTRACT
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                importer.migrate(self.path, target_contract=CONTRACT)
        self.factory.assert_not_called()

    def test_target_identity_failure_rolls_back_before_add(self):
        from test_original_schema import CONTRACT, URL
        self.db.get_bind.return_value.url = URL
        with patch.dict(os.environ, {'DATABASE_URL': URL}), \
                patch.object(importer, 'require_target', side_effect=ValueError('wrong database')):
            with self.assertRaises(ValueError):
                importer.migrate(self.path, target_contract=CONTRACT)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()
        self.db.rollback.assert_called_once()
        self.db.close.assert_called_once()

    def test_cached_session_target_mismatch_refused_before_connecting(self):
        from test_original_schema import CONTRACT, URL
        self.db.get_bind.return_value.url = URL.replace('db.example.invalid', 'preview.invalid')
        with patch.dict(os.environ, {'DATABASE_URL': URL}), patch.object(importer, 'require_target'):
            with self.assertRaises(ValueError):
                importer.migrate(self.path, target_contract=CONTRACT)
        self.db.connection.assert_not_called()
        self.db.add.assert_not_called()
        self.db.rollback.assert_called_once()
        self.db.close.assert_called_once()

    def test_matching_actual_engine_and_identity_are_checked_before_write(self):
        from test_original_schema import CONTRACT, URL
        self.db.get_bind.return_value.url = URL
        with patch.dict(os.environ, {'DATABASE_URL': URL}), patch.object(importer, 'require_target') as guard:
            self.assertEqual(importer.migrate(self.path, target_contract=CONTRACT), 1)
        guard.assert_called_once_with(self.db.connection.return_value, CONTRACT)
        self.db.commit.assert_called_once()

    def test_geometry_crs_override_is_rejected_before_session(self):
        data = copy.deepcopy(FEATURES)
        data['features'][0]['geometry']['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:3857'}}
        self.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            importer.migrate(self.path)
        self.factory.assert_not_called()
