"""Offline HTTP harness: real routes/calculator/models, doubled external boundaries."""
import os
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from offline_guard import offline_boundaries

with offline_boundaries() as attempts:
    from main import create_app
    from core import RiskCalculator
assert not attempts

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

POLYGON = {'type': 'Polygon', 'coordinates': [
    [[-46.2, -23.2], [-46.2, -23], [-46, -23], [-46, -23.2], [-46.2, -23.2]]]}


def db_error():
    return OperationalError('private SQL', {}, Exception('private DSN'))


def session_double():
    session = MagicMock()
    session.info = {}
    query = session.query.return_value
    query.filter.return_value = query
    query.scalar.return_value = None
    session.query.return_value.order_by.return_value.first.return_value = (
        SimpleNamespace(name='Rio Original', type='river'), 120.123, 'POINT(-46 -23)')
    return session


class RiskTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.db = session_double()
        self.factory = self.enterContext(patch('database.SessionLocal', return_value=self.db))
        self.osm = self.enterContext(patch('routers.risk.get_osm_service'))
        self.osm.return_value.fetch_and_save_rivers.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.elevation = self.enterContext(patch('routers.risk.elevation_m', side_effect=[0, 8]))
        self.provider_factory = self.enterContext(patch('routers.risk.get_data_provider'))
        self.provider = self.provider_factory.return_value
        self.provider.name = 'MapBiomas'
        self.provider.get_soil_data.return_value = {
            'class_id': 3, 'class_name': 'Formação Florestal', 'is_permeable': True}
        self.provider.get_water_frequency.return_value = {'frequency_years': 0, 'confidence': 1.0}
        self.calculate = self.enterContext(patch('routers.risk.RiskCalculator.calculate_risk',
                                               wraps=RiskCalculator.calculate_risk))
        self.ai = self.enterContext(patch('routers.risk.get_ai_assessment', return_value=
            SimpleNamespace(explanation='Parecer técnico original.', risk_level='Baixo')))
        self.client = TestClient(create_app(), raise_server_exceptions=False)

    def post_risk(self, polygon=POLYGON):
        return self.client.post('/geo/risk', json={'polygon': polygon})

    def assert_no_analysis(self):
        self.calculate.assert_not_called()
        self.ai.assert_not_called()
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()
