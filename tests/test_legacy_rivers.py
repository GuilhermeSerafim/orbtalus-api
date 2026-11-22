from unittest.mock import MagicMock, patch

from risk_support import RiskTestCase, POLYGON
from models import WaterBody
from services.osm_service import OSMService


class LegacyRiverTests(RiskTestCase):
    def test_undated_river_remains_in_inventory_but_cannot_classify_after_refresh_failure(self):
        river = WaterBody(id=1, name='Rio herdado', type='river', geom='SRID=4326;LINESTRING(-46 -23,-45 -22)')
        self.osm.return_value = OSMService()
        with patch('services.osm_service.SessionLocal', side_effect=RuntimeError('private DSN')):
            self.db.query.return_value.order_by.return_value.first.return_value = (river, 12, 'POINT(-46 -23)')
            response = self.post_risk()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['detail']['code'], 'HYDROLOGY_LOOKUP_FAILED')
        self.elevation.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_analysis()
        self.db.query.return_value.order_by.return_value.first.return_value = (river, 12)
        response = self.client.post('/geo/distance', json={'polygon': POLYGON})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['rio_mais_proximo'], 'Rio herdado')

    def test_osm_transaction_can_commit_while_risk_fails_without_persisting_assessment(self):
        cache = MagicMock()
        cache.query.return_value.scalar.return_value = None
        service = OSMService()
        service.api = MagicMock()
        from types import SimpleNamespace
        service.api.query.return_value = SimpleNamespace(relations=[], ways=[SimpleNamespace(
            id=1, tags={'name': 'Rio cache', 'waterway': 'river'},
            nodes=[SimpleNamespace(lon=-46, lat=-23), SimpleNamespace(lon=-45, lat=-22)])])
        self.osm.return_value = service
        self.db.query.return_value.order_by.return_value.first.return_value = None
        with patch('services.osm_service.SessionLocal', return_value=cache):
            response = self.post_risk()
        self.assertEqual(response.status_code, 503)
        cache.commit.assert_called_once()
        cache.close.assert_called_once()
        self.db.rollback.assert_called_once()
        self.db.close.assert_called_once()
        self.assert_no_analysis()
