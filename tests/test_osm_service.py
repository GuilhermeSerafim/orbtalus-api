import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from offline_guard import offline_boundaries

with offline_boundaries():
    from services.osm_service import OSMService


class OSMServiceTests(unittest.TestCase):
    def setUp(self):
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.service = OSMService()
        self.service.api = MagicMock()

    def test_skips_fetch_when_area_is_already_mapped(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 6

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        self.service.api.query.assert_not_called()
        session.commit.assert_not_called()
        session.close.assert_called_once()

    def test_sanitizes_osm_text_fields_before_commit(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        self.service.api.query.return_value = SimpleNamespace(
            relations=[],
            ways=[
                SimpleNamespace(
                    id=123,
                    tags={"name": "Rio\x00Teste", "waterway": "river\x1f"},
                    nodes=[
                        SimpleNamespace(lon=-46.0, lat=-23.0),
                        SimpleNamespace(lon=-46.1, lat=-23.1),
                    ],
                )
            ],
        )

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        rivers = session.add_all.call_args[0][0]
        self.assertEqual(len(rivers), 1)
        self.assertEqual(rivers[0].name, "RioTeste")
        self.assertEqual(rivers[0].type, "river")
        session.commit.assert_called_once()
        session.close.assert_called_once()

    def test_rolls_back_when_commit_fails(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        session.commit.side_effect = ValueError(
            "A string literal cannot contain NUL (0x00) characters."
        )
        self.service.api.query.return_value = SimpleNamespace(
            relations=[],
            ways=[
                SimpleNamespace(
                    id=456,
                    tags={"name": "Rio Teste", "waterway": "river"},
                    nodes=[
                        SimpleNamespace(lon=-46.0, lat=-23.0),
                        SimpleNamespace(lon=-46.1, lat=-23.1),
                    ],
                )
            ],
        )

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    def test_factory_failure_is_best_effort_and_logs_no_secrets(self):
        with patch('services.osm_service.SessionLocal', side_effect=RuntimeError('PRIVATE_DSN')):
            with self.assertLogs('services.osm_service', level='WARNING') as captured:
                self.service.fetch_and_save_rivers(-23, -46)
        self.assertNotIn('PRIVATE_DSN', '\n'.join(captured.output))
        self.service.api.query.assert_not_called()

    def test_rollback_and_close_failures_do_not_escape_or_log_private_exception(self):
        session = MagicMock()
        session.query.side_effect = RuntimeError('PRIVATE_QUERY')
        session.rollback.side_effect = RuntimeError('PRIVATE_ROLLBACK')
        session.close.side_effect = RuntimeError('PRIVATE_CLOSE')
        with patch('services.osm_service.SessionLocal', return_value=session):
            with self.assertLogs('services.osm_service', level='WARNING') as captured:
                self.service.fetch_and_save_rivers(-23, -46)
        session.rollback.assert_called_once()
        session.close.assert_called_once()
        self.assertNotIn('PRIVATE_', '\n'.join(captured.output))

    def test_cache_threshold_radius_and_query_are_unchanged(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 5
        self.service.api.query.return_value = SimpleNamespace(relations=[], ways=[])
        with patch('services.osm_service.SessionLocal', return_value=session):
            self.service.fetch_and_save_rivers(-23, -46)
        query = self.service.api.query.call_args.args[0]
        self.assertIn('way["waterway"](around:5000,-23,-46)', query)
        self.assertIn('relation["waterway"](around:5000,-23,-46)', query)
        self.assertIn('[timeout:25]', query)
        session.commit.assert_not_called()

    def test_client_construction_failure_is_best_effort(self):
        service = OSMService()
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        with patch('services.osm_service.SessionLocal', return_value=session), \
                patch('services.osm_service.overpy.Overpass', side_effect=RuntimeError('PRIVATE_API')):
            with self.assertLogs('services.osm_service', level='WARNING') as captured:
                service.fetch_and_save_rivers(-23, -46)
        self.assertNotIn('PRIVATE_API', '\n'.join(captured.output))
        session.rollback.assert_called_once()
        session.close.assert_called_once()

    def test_relation_names_and_types_still_inherited(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        self.service.api.query.return_value = SimpleNamespace(
            relations=[SimpleNamespace(id=3, tags={'name': 'Rio relação', 'waterway': 'river'},
                                       members=[SimpleNamespace(_type_value='way', ref=123)])],
            ways=[SimpleNamespace(id=123, tags={}, nodes=[
                SimpleNamespace(lon=-46, lat=-23), SimpleNamespace(lon=-45, lat=-22)])])
        with patch('services.osm_service.SessionLocal', return_value=session):
            self.service.fetch_and_save_rivers(-23, -46)
        river = session.add_all.call_args.args[0][0]
        self.assertEqual((river.name, river.type), ('Rio relação', 'river'))
