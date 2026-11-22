"""Offline replay through the real risk route and MapBiomas adapter."""
from types import SimpleNamespace
from unittest.mock import patch

from risk_support import RiskTestCase
from ee import EEException
from providers.mapbiomas_adapter import MapBiomasAdapter


CORUJAS = {'type': 'Polygon', 'coordinates': [[
    [-46.6958, -23.5494], [-46.6956, -23.5494], [-46.6956, -23.5492],
    [-46.6958, -23.5492], [-46.6958, -23.5494],
]]}


class PartialRiskTests(RiskTestCase):
    def setUp(self):
        super().setUp()
        sdk = self.enterContext(patch('providers.mapbiomas_adapter.ee'))
        sdk.EEException = EEException
        adapter = MapBiomasAdapter(initialize_gee=False)
        adapter._initialized = True
        self.provider_factory.return_value = adapter
        image = sdk.Image.return_value
        image.bandNames.return_value.getInfo.return_value = ['water_frequency_1985_2023']
        self.pixel = image.select.return_value.reduceRegion.return_value.get.return_value.getInfo
        self.db.query.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(name='Córrego das Corujas', type='stream'), 22.5,
            'POINT(-46.6955 -23.5493)')

    def replay(self, soil, water):
        self.elevation.side_effect = [754, 754]
        self.pixel.side_effect = [soil, water]
        return self.post_risk(CORUJAS)

    def test_corujas_null_water_sample_keeps_observations_without_assessment(self):
        response = self.replay(24, None)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['analysis_status'], 'partial')
        self.assertEqual(result['missing_indicators'], ['water_frequency'])
        self.assertEqual(result['rio_mais_proximo'], 'Córrego das Corujas')
        self.assertEqual(result['distancia_rio_m'], 22.5)
        self.assertEqual(result['queda_relativa_m'], 0.0)
        self.assertEqual(result['environmental_data'], {
            'soil': {'class_id': 24, 'class_name': 'Área Urbanizada', 'is_permeable': False},
            'water_frequency': None, 'data_source': 'MapBiomas (GEE)', 'provider_status': 'partial'})
        for field in ('risk_level', 'risk_calculation', 'resposta_ia'):
            self.assertIsNone(result[field])
        self.assert_no_analysis()

    def test_missing_soil_preserves_an_observed_zero_and_lists_each_missing_indicator(self):
        for water, missing, observed in (
            (0, ['soil'], {'years': 0, 'confidence': 1.0}),
            (None, ['soil', 'water_frequency'], None),
        ):
            with self.subTest(water=water):
                response = self.replay(None, water)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result['missing_indicators'], missing)
                self.assertIsNone(result['environmental_data']['soil'])
                self.assertEqual(result['environmental_data']['water_frequency'], observed)
                self.assert_no_analysis()

    def test_invalid_measurement_or_upstream_failure_is_still_an_error(self):
        for water in (101, EEException('upstream unavailable')):
            with self.subTest(water=water):
                response = self.replay(None, water)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['detail']['code'], 'DATA_UNAVAILABLE')
                self.assert_no_analysis()
