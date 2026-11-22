import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException
from fastapi.testclient import TestClient
from risk_support import POLYGON, RiskTestCase, create_app
from core.demo_quota import admit_demo_request
from core.errors import ServiceUnavailable
from services.osm_service import OSMService
from test_osm_service import FETCHED_AT, session_with_coverage


class RequestTraceTests(RiskTestCase):
    def setUp(self):
        super().setUp()
        with patch.dict(os.environ, {'CORS_ORIGINS': 'https://example.org'}):
            self.client = TestClient(create_app(), raise_server_exceptions=False)

    def post(self, path):
        with self.assertLogs(level='INFO') as logs:
            response = self.client.post(path, json={'polygon': POLYGON}, headers={
                'Origin': 'https://example.org', 'X-Request-ID': 'private-caller'})
        self.assertIn('x-request-id', response.headers)
        receipt = response.headers['x-request-id']
        self.assertRegex(receipt, r'^[0-9a-f]{32}$')
        self.assertEqual(response.headers['access-control-allow-origin'], 'https://example.org')
        self.assertIn('x-request-id', response.headers['access-control-expose-headers'].lower())
        messages = [r.getMessage() for r in logs.records]
        summaries = [json.loads(m.removeprefix('Geo request ')) for m in messages
                     if m.startswith('Geo request ')]
        event, = summaries
        self.assertEqual((event['request_id'], event['path'], event['status']),
                         (receipt, path, response.status_code))
        self.assertGreaterEqual(event['duration_ms'], 0)
        self.assertNotIn('private-', str(messages))
        self.assertNotIn('-46.2', str(messages))
        return response, event, [json.loads(m.removeprefix('OSM diagnostic ')) for m in messages
                                 if m.startswith('OSM diagnostic ')]

    def test_cache_on_risk_and_overpass_on_hydrology(self):
        service = OSMService()
        self.osm.return_value = service
        self.client.app.dependency_overrides[OSMService] = lambda: service
        sessions = [session_with_coverage(FETCHED_AT), session_with_coverage()]
        with patch('services.osm_service.SessionLocal', side_effect=sessions), patch(
            'services.osm_service._OverpassClient.query',
            return_value=SimpleNamespace(relations=[], ways=[])
        ), patch('routers.distance.nearest_water_body', return_value=None):
            risk, cached, _ = self.post('/geo/risk')
            hydro, refreshed, _ = self.post('/geo/hydrology')
        self.assertEqual((risk.status_code, hydro.status_code), (200, 200))
        self.assertEqual(cached['origin'], 'cache')
        self.assertEqual(refreshed['origin'], hydro.json()['consulta'])
        self.assertEqual(refreshed['origin'], 'overpass')
        self.assertNotEqual(cached['request_id'], refreshed['request_id'])

    def test_cold_open_failure_matches_diagnostic(self):
        with patch('services.osm_service.SessionLocal', return_value=session_with_coverage()), patch(
            'services.osm_service.urlopen', side_effect=URLError('private-transport')
        ):
            response, event, diagnostics = self.post('/geo/hydrology')
        diagnostic, = diagnostics
        self.assertEqual(response.status_code, 503)
        self.assertEqual(event['origin'], 'unknown')
        self.assertEqual(event['failure_code'], response.json()['detail']['code'])
        self.assertEqual(event['failure_stage'], 'overpass_open')
        self.assertEqual(diagnostic['request_id'], event['request_id'])
        self.assertIsNone(diagnostic['http_status'])

    def test_later_failure_retains_origin(self):
        self.osm.return_value = OSMService()
        self.ai.side_effect = ServiceUnavailable('AI_UNAVAILABLE')
        with patch('services.osm_service.SessionLocal', return_value=session_with_coverage(FETCHED_AT)):
            response, event, _ = self.post('/geo/risk')
        self.assertEqual(response.status_code, 503)
        self.assertEqual((event['origin'], event['failure_code']), ('cache', 'AI_UNAVAILABLE'))

    def test_quota_refusal_before_hydrology(self):
        def refuse():
            raise HTTPException(429, {'code': 'DEMO_IP_LIMIT'}, headers={'Retry-After': '42'})
        self.client.app.dependency_overrides[admit_demo_request] = refuse
        response, event, _ = self.post('/geo/risk')
        self.assertEqual((response.status_code, response.headers['Retry-After']), (429, '42'))
        self.assertEqual((event['origin'], event['failure_code']), ('not_reached', 'DEMO_IP_LIMIT'))
