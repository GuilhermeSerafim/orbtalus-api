import unittest
import io
import json
import logging
from email.message import Message
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import urllib.request
import urllib.response

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


class OSMTransportTests(unittest.TestCase):
    """Keep query construction and Overpy parsing real; replace only HTTP I/O."""
    def setUp(self):
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.requests = []
        self.status = 200
        self.error = None
        self.read_error = None
        self.payload = {'elements': [
            {'type': 'node', 'id': 1, 'lat': -23.0, 'lon': -46.0},
            {'type': 'node', 'id': 2, 'lat': -23.1, 'lon': -46.1},
            {'type': 'way', 'id': 7, 'nodes': [1, 2],
             'tags': {'name': 'Rio diagnóstico', 'waterway': 'river'}},
        ]}
        case = self
        class Wire(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
            def http_open(self, request):
                case.requests.append(request)
                if case.error:
                    raise case.error
                headers = Message()
                headers['Content-Type'] = 'application/json'
                response = urllib.response.addinfourl(
                    io.BytesIO(json.dumps(case.payload).encode()), headers,
                    request.full_url, case.status)
                response.msg = 'diagnostic response'
                if case.read_error:
                    response.read = MagicMock(side_effect=case.read_error)
                return response
            https_open = http_open
        self.enterContext(patch('urllib.request._opener', urllib.request.build_opener(Wire())))
        self.session = MagicMock()
        self.session.query.return_value.filter.return_value.count.return_value = 0

    def fetch(self):
        with patch('services.osm_service.SessionLocal', return_value=self.session):
            OSMService().fetch_and_save_rivers(-23, -46)

    def test_identifies_project_on_the_wire_and_preserves_real_osm_parsing(self):
        self.fetch()
        self.assertEqual(len(self.requests), 1)
        req = self.requests[0]
        self.assertIn('OrbTalus', req.get_header('User-agent'))
        self.assertIn('https://github.com/GuilhermeSerafim/orbtalus', req.get_header('User-agent'))
        self.assertEqual(req.get_method(), 'POST')
        self.assertIn(b'way["waterway"](around:5000,-23,-46)', req.data)
        self.assertIn(b'relation["waterway"](around:5000,-23,-46)', req.data)
        rivers = self.session.add_all.call_args.args[0]
        self.assertEqual((len(rivers), rivers[0].name, rivers[0].type), (1, 'Rio diagnóstico', 'river'))
        self.session.commit.assert_called_once()

    def test_sets_a_finite_transport_timeout_separate_from_ql_timeout(self):
        self.fetch()
        timeout = self.requests[0].timeout
        self.assertIsInstance(timeout, (int, float))
        self.assertGreater(timeout, 25)
        self.assertLessEqual(timeout, 60)

    def test_refusal_and_timeout_do_not_retry_or_write_hydrology(self):
        for status, error in ((429, None), (502, None), (200, TimeoutError('PRIVATE_DETAIL'))):
            with self.subTest(status=status, error=type(error).__name__):
                self.requests.clear()
                self.session.reset_mock()
                self.status, self.error = status, error
                with self.assertLogs('services.osm_service', level='WARNING') as logs:
                    self.fetch()
                self.assertEqual(len(self.requests), 1)
                self.session.add_all.assert_not_called()
                self.session.commit.assert_not_called()
                self.session.rollback.assert_called_once()
                self.session.close.assert_called_once()
                self.assertNotIn('PRIVATE_DETAIL', '\n'.join(logs.output))

    def test_overpass_remark_is_not_accepted_as_empty_success(self):
        self.payload = {'elements': [], 'remark': 'runtime error: Query timed out'}
        self.fetch()
        self.session.add_all.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_called_once()

    def diagnostic_events(self, action=None):
        """Exercise message-only output, as used by the live API's warning log."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter('%(message)s'))
        log = logging.getLogger('services.osm_service')
        with patch.object(log, 'handlers', [handler]), patch.object(log, 'propagate', False), \
                patch.object(log, 'level', logging.WARNING):
            (action or self.fetch)()
        text = stream.getvalue()
        self.assertNotIn('PRIVATE_', text)
        events = [json.loads(line.removeprefix('OSM diagnostic '))
                  for line in text.splitlines() if line.startswith('OSM diagnostic ')]
        self.assertTrue(events, text)
        for event in events:
            self.assertIn('http_status', event)
            self.assertGreaterEqual(event['elapsed_ms'], 0)
        return events

    def test_http_failure_and_unknown_transport_code_reach_rendered_log(self):
        for status, error, expected, types in (
                (502, None, 502, ['HTTPError']),
                (200, TimeoutError('PRIVATE_TIMEOUT'), None, ['TimeoutError']),
                (200, OSError(502, 'PRIVATE_NOT_HTTP'), None, ['OSError'])):
            with self.subTest(status=status, error=type(error).__name__):
                self.status, self.error = status, error
                event = self.diagnostic_events()[0]
                self.assertEqual(event['code'], 'OSM_ENRICHMENT_FAILED')
                self.assertEqual(event['stage'], 'overpass_open')
                self.assertEqual(event['http_status'], expected)
                self.assertEqual(event['exception_types'], types)
                self.assertGreaterEqual(event['overpass_elapsed_ms'], 0)

    def test_http_200_parser_failure_keeps_successful_transport_status(self):
        self.payload = {'elements': [], 'remark': 'runtime error: PRIVATE_REMARK'}
        event = self.diagnostic_events()[0]
        self.assertEqual((event['stage'], event['http_status']), ('overpass_parse', 200))
        self.assertEqual(event['exception_types'], ['OverpassRuntimeError'])
        self.session.commit.assert_not_called()

    def test_read_timeout_is_distinct_from_open_timeout(self):
        self.read_error = TimeoutError('PRIVATE_READ')
        event = self.diagnostic_events()[0]
        self.assertEqual((event['stage'], event['http_status']), ('overpass_read', 200))
        self.assertEqual(event['exception_types'], ['TimeoutError'])

    def test_cache_and_db_write_failures_keep_their_stage(self):
        for operation, stage, status in (
                ('query', 'cache_lookup', None),
                ('add_all', 'db_add_all', 200),
                ('commit', 'db_commit', 200)):
            with self.subTest(operation=operation):
                getattr(self.session, operation).side_effect = ValueError('PRIVATE_DB')
                event = self.diagnostic_events()[0]
                self.assertEqual((event['stage'], event['http_status']), (stage, status))
                self.assertEqual(event['exception_types'], ['ValueError'])
                getattr(self.session, operation).side_effect = None

    def test_chained_primary_survives_rollback_and_close_failures(self):
        primary = RuntimeError('PRIVATE_PRIMARY')
        primary.__cause__ = ValueError('PRIVATE_CAUSE')
        self.error = primary
        self.session.rollback.side_effect = LookupError('PRIVATE_ROLLBACK')
        self.session.close.side_effect = OSError('PRIVATE_CLOSE')
        events = self.diagnostic_events()
        self.assertEqual([event['code'] for event in events], [
            'OSM_ENRICHMENT_FAILED', 'OSM_CACHE_ROLLBACK_FAILED', 'OSM_CACHE_CLOSE_FAILED'])
        self.assertEqual(events[0]['exception_types'], ['RuntimeError', 'ValueError'])
        self.assertFalse(events[0]['chain_truncated'])
        for event, stage in zip(events[1:], ['db_rollback', 'db_close']):
            self.assertEqual(event['primary'], events[0])
            self.assertEqual(event['stage'], stage)
        self.session.rollback.assert_called_once()
        self.session.close.assert_called_once()

    def test_reentrant_calls_do_not_mix_transport_or_primary_context(self):
        service = OSMService()
        nested = MagicMock()
        nested.query.side_effect = LookupError('PRIVATE_NESTED')
        def commit_outer():
            service.fetch_and_save_rivers(-22, -45)
            raise ValueError('PRIVATE_OUTER')
        self.session.commit.side_effect = commit_outer
        def action():
            with patch('services.osm_service.SessionLocal', side_effect=[self.session, nested]):
                service.fetch_and_save_rivers(-23, -46)
        events = self.diagnostic_events(action)
        self.assertEqual([(event['stage'], event['http_status'], event['exception_types'])
                          for event in events], [
            ('cache_lookup', None, ['LookupError']), ('db_commit', 200, ['ValueError'])])

    def test_session_failure_and_close_only_failure_have_explicit_nulls(self):
        def factory_failure():
            with patch('services.osm_service.SessionLocal', side_effect=ValueError('PRIVATE_FACTORY')):
                OSMService().fetch_and_save_rivers(-23, -46)
        event = self.diagnostic_events(factory_failure)[0]
        self.assertEqual(event['stage'], 'db_session')
        self.assertIsNone(event['http_status'])
        self.assertIsNone(event['overpass_elapsed_ms'])
        self.session.query.return_value.filter.return_value.count.return_value = 6
        self.session.close.side_effect = OSError('PRIVATE_CLOSE')
        event = self.diagnostic_events()[0]
        self.assertEqual(event['code'], 'OSM_CACHE_CLOSE_FAILED')
        self.assertIsNone(event['primary'])
        self.assertIsNone(event['http_status'])

    def test_only_allowlisted_application_error_codes_are_retained(self):
        from core.errors import ServiceUnavailable
        for error, expected in ((ServiceUnavailable('CONFIG_UNAVAILABLE'), 'CONFIG_UNAVAILABLE'),
                                (ValueError('PRIVATE_ERROR'), None)):
            with self.subTest(error=type(error).__name__):
                if isinstance(error, ValueError):
                    error.code = 'PRIVATE_NOT_A_PUBLIC_CODE'
                def action():
                    with patch('services.osm_service.SessionLocal', side_effect=error):
                        OSMService().fetch_and_save_rivers(-23, -46)
                event = self.diagnostic_events(action)[0]
                self.assertEqual(event['error_code'], expected)

    def test_missing_way_nodes_is_hydrology_failure_after_valid_json(self):
        self.payload['elements'] = self.payload['elements'][1:]
        event = self.diagnostic_events()[0]
        self.assertEqual((event['stage'], event['http_status']), ('hydrology_build', 200))
        self.assertEqual(event['exception_types'], ['DataIncomplete'])
        self.assertEqual(len(self.requests), 1)
        self.session.commit.assert_not_called()

    def test_cyclic_and_long_exception_chains_are_bounded(self):
        first = RuntimeError('PRIVATE_FIRST')
        second = ValueError('PRIVATE_SECOND')
        first.__cause__ = second
        second.__context__ = first
        self.error = first
        event = self.diagnostic_events()[0]
        self.assertEqual(event['exception_types'], ['RuntimeError', 'ValueError'])
        self.assertTrue(event['chain_truncated'])
        for _ in range(10):
            outer = RuntimeError('PRIVATE_OUTER')
            outer.__cause__ = self.error
            self.error = outer
        event = self.diagnostic_events()[0]
        self.assertEqual(len(event['exception_types']), 8)
        self.assertTrue(event['chain_truncated'])

    def test_empty_usable_response_is_not_reported_as_transport_failure(self):
        self.payload = {'elements': []}
        event = self.diagnostic_events()[0]
        self.assertEqual((event['code'], event['stage'], event['http_status']),
                         ('OSM_ENRICHMENT_EMPTY', 'hydrology_build', 200))
        self.assertEqual(event['exception_types'], [])
        self.session.commit.assert_not_called()
