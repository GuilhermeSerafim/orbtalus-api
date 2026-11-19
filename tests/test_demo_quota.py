import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import main
from core.demo_quota import client_bucket, reserve


class DemoQuotaCounterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text("ATTACH DATABASE ':memory:' AS orbtalus_demo"))
            conn.execute(text("""
                CREATE TABLE orbtalus_demo.daily_usage (
                    day DATE NOT NULL, bucket TEXT NOT NULL, used INTEGER NOT NULL,
                    PRIMARY KEY (day, bucket)
                )
            """))

    def call(self, bucket, day=19):
        with self.engine.begin() as conn:
            reserve(conn, datetime(2026, 11, day, 23, 59, 59), bucket, 1, 2)

    def test_rejected_ip_does_not_spend_global_quota_and_global_blocks_other_ips(self):
        self.call('198.51.100.10')
        with self.assertRaises(HTTPException) as ip:
            self.call('198.51.100.10')
        self.assertEqual(ip.exception.status_code, 429)
        self.assertEqual(ip.exception.detail['code'], 'DEMO_IP_LIMIT')
        self.assertEqual(ip.exception.headers['Retry-After'], '1')
        self.call('198.51.100.11')
        with self.assertRaises(HTTPException) as global_cap:
            self.call('198.51.100.12')
        self.assertEqual(global_cap.exception.detail['code'], 'DEMO_DAILY_LIMIT')
        self.call('198.51.100.10', day=20)

    def test_ipv6_rotations_and_untrusted_forwarded_header_do_not_change_bucket(self):
        for address in (b'2001:db8:1:2::1', b'2001:db8:1:2::4'):
            request = Request({'type': 'http', 'headers': [
                (b'cf-connecting-ip', address), (b'x-forwarded-for', b'203.0.113.5'),
            ]})
            self.assertEqual(client_bucket(request), '2001:db8:1:2::/64')


class DemoQuotaRouteTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict('os.environ', {'RENDER': 'true'}))
        self.client = self.enterContext(TestClient(main.create_app()))
        self.osm = self.enterContext(patch('routers.risk.get_osm_service', side_effect=AssertionError('provider reached')))
        self.ai = self.enterContext(patch('routers.ai_vertical.get_ai_assessment', return_value='unmetered'))

    def test_demo_closes_generic_ai_route(self):
        response = self.client.post('/ai/ask-ai', json={'pergunta': 'Oi'})
        self.assertEqual(response.status_code, 404)
        self.ai.assert_not_called()

    def test_missing_edge_ip_stops_risk_before_any_database_or_provider(self):
        polygon = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        response = self.client.post('/geo/risk', json={'polygon': polygon},
                                    headers={'X-Forwarded-For': '198.51.100.2'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['code'], 'DEMO_UNAVAILABLE')
        self.osm.assert_not_called()
