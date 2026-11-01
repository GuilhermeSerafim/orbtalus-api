"""Provider contracts with SDK doubles; never authenticate or contact EE."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from offline_guard import offline_boundaries

with offline_boundaries() as import_attempts:
    from core.errors import ServiceUnavailable, MESSAGES
    from providers.mapbiomas_adapter import MapBiomasAdapter, MAPBIOMAS_SOIL_CLASSES
    from main import create_app
assert not import_attempts

from fastapi.testclient import TestClient
from ee import EEException


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.sdk = self.enterContext(patch('providers.mapbiomas_adapter.ee'))
        self.sdk.EEException = EEException
        self.adapter = MapBiomasAdapter(initialize_gee=False)
        self.adapter._initialized = True
        self.image = self.sdk.Image.return_value
        self.sample = self.image.select.return_value.reduceRegion.return_value
        self.image.bandNames.return_value.getInfo.return_value = ['frequency']

    def assert_unavailable(self, call, code='DATA_UNAVAILABLE'):
        with self.assertRaises(ServiceUnavailable) as caught:
            call()
        self.assertEqual(caught.exception.detail, {'code': code, 'message': MESSAGES[code]})
        self.assertNotIn('private', str(caught.exception))

    def test_uninitialized_provider_never_returns_fabricated_data(self):
        self.adapter._initialized = False
        for method in (self.adapter.get_soil_data, self.adapter.get_water_frequency,
                       self.adapter.get_elevation):
            with self.subTest(method=method.__name__):
                self.assert_unavailable(lambda: method(-23, -46))
        self.sdk.Image.assert_not_called()

    def test_missing_project_prevents_authentication(self):
        self.assert_unavailable(MapBiomasAdapter, 'CONFIG_UNAVAILABLE')
        self.sdk.Initialize.assert_not_called()

    def test_initialization_failure_has_no_fallback(self):
        with patch.dict(os.environ, {'GEE_PROJECT': 'test-project'}):
            self.sdk.Initialize.side_effect = EEException('private upstream')
            self.assert_unavailable(MapBiomasAdapter)

    def test_explicit_project_in_all_supported_credential_modes(self):
        with patch.dict(os.environ, {'GEE_PROJECT': 'test-project'}):
            MapBiomasAdapter()
            self.sdk.Initialize.assert_called_once_with(project='test-project')
            self.sdk.Initialize.reset_mock()
            for variable, value, loader_name in (
                ('GOOGLE_APPLICATION_CREDENTIALS', 'not-a-real-credential-file.json',
                 'from_service_account_file'),
                ('GEE_SERVICE_ACCOUNT_JSON', '{"type":"service_account"}',
                 'from_service_account_info'),
            ):
                with self.subTest(mode=variable), patch.dict(os.environ, {variable: value}), \
                        patch('google.oauth2.service_account.Credentials.' + loader_name) as loader:
                    MapBiomasAdapter()
                    loader.assert_called_once()
                    self.sdk.Initialize.assert_called_once_with(
                        credentials=loader.return_value, project='test-project')
                    self.sdk.Initialize.reset_mock()

    def test_invalid_explicit_credentials_do_not_silently_switch_to_adc(self):
        with patch.dict(os.environ, {'GEE_PROJECT': 'test-project',
                                    'GOOGLE_APPLICATION_CREDENTIALS': 'missing-file.json'}), \
                patch('google.oauth2.service_account.Credentials.from_service_account_file',
                      side_effect=FileNotFoundError('private path')):
            self.assert_unavailable(MapBiomasAdapter, 'CONFIG_UNAVAILABLE')
            self.sdk.Initialize.assert_not_called()
        with patch.dict(os.environ, {'GEE_PROJECT': 'test-project',
                                    'GEE_SERVICE_ACCOUNT_JSON': 'invalid JSON'}):
            self.assert_unavailable(MapBiomasAdapter, 'CONFIG_UNAVAILABLE')
            self.sdk.Initialize.assert_not_called()

    def test_soil_requires_a_known_integral_finite_class(self):
        for value in (None, float('nan'), float('inf'), -float('inf'), True, False,
                      0, 999, 3.5, '3', {}, []):
            with self.subTest(value=value):
                self.sample.get.return_value.getInfo.return_value = value
                self.assert_unavailable(lambda: self.adapter.get_soil_data(-23, -46))

    def test_soil_retains_classes_dataset_band_and_reducer(self):
        for class_id, info in MAPBIOMAS_SOIL_CLASSES.items():
            self.sample.get.return_value.getInfo.return_value = class_id
            self.assertEqual(self.adapter.get_soil_data(-23, -46), {
                'class_id': class_id, 'class_name': info['name'], 'is_permeable': info['is_permeable']})
        self.sdk.Geometry.Point.assert_called_with([-46, -23])
        self.sdk.Image.assert_called_with(
            'projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1')
        self.image.select.assert_called_with('classification_2022')
        self.image.select.return_value.reduceRegion.assert_called_with(
            reducer=self.sdk.Reducer.first.return_value,
            geometry=self.sdk.Geometry.Point.return_value, scale=30)
        self.sample.get.assert_called_with('classification_2022')

    def test_soil_and_water_sdk_failures_are_typed_and_safe(self):
        self.sample.get.return_value.getInfo.side_effect = EEException('private URL/token')
        for method in (self.adapter.get_soil_data, self.adapter.get_water_frequency):
            self.assert_unavailable(lambda: method(-23, -46))

    def test_band_discovery_error_is_safe_and_programming_bug_is_not_masked(self):
        self.image.bandNames.return_value.getInfo.side_effect = EEException('private body')
        self.assert_unavailable(lambda: self.adapter.get_water_frequency(-23, -46))
        self.sdk.Image.side_effect = RuntimeError('bug')
        with self.assertRaisesRegex(RuntimeError, 'bug'):
            self.adapter.get_soil_data(-23, -46)

    def test_unknown_missing_or_malformed_bands_fail_without_selecting(self):
        for bands in (['arbitrary'], [], None, 'frequency', {'frequency': 1}):
            with self.subTest(bands=bands):
                self.image.bandNames.return_value.getInfo.return_value = bands
                self.assert_unavailable(lambda: self.adapter.get_water_frequency(-23, -46))
        self.image.select.assert_not_called()

    def test_known_bands_keep_original_precedence(self):
        expected = ['water_frequency_1985_2023', 'frequency', 'water_frequency',
                    'water_frequency_1985_2022']
        self.assertEqual(self.adapter.WATER_FREQUENCY_BANDS, expected)
        self.sample.get.return_value.getInfo.return_value = 50
        for index, name in enumerate(expected):
            self.image.bandNames.return_value.getInfo.return_value = list(reversed(expected[index:]))
            self.assertEqual(self.adapter.get_water_frequency(-23, -46)['frequency_years'], 15)
            self.image.select.assert_called_with(name)
            self.sample.get.assert_called_with(name)

    def test_water_requires_finite_percentage_and_preserves_real_zero(self):
        for value in (None, float('nan'), float('inf'), -float('inf'), True, False,
                      -1, 101, '0', {}, []):
            with self.subTest(value=value):
                self.sample.get.return_value.getInfo.return_value = value
                self.assert_unavailable(lambda: self.adapter.get_water_frequency(-23, -46))
        for value in (0, 2, 50, 99, 100):
            self.sample.get.return_value.getInfo.return_value = value
            self.assertEqual(self.adapter.get_water_frequency(-23, -46),
                             {'frequency_years': round(value / 100 * 30), 'confidence': 1.0})
        self.sdk.Geometry.Point.assert_called_with([-46, -23])
        self.sdk.Geometry.Point.return_value.buffer.assert_called_with(1000)
        self.sdk.Image.assert_called_with(
            'projects/mapbiomas-public/assets/brazil/water/collection3/mapbiomas_water_frequency_v1')
        self.image.select.return_value.reduceRegion.assert_called_with(
            reducer=self.sdk.Reducer.max.return_value,
            geometry=self.sdk.Geometry.Point.return_value.buffer.return_value,
            scale=30, maxPixels=5000)

    def test_srtm_rejects_invalid_values_and_preserves_zero_and_negative(self):
        sample = self.image.sample.return_value.first.return_value.get.return_value
        for value in (None, float('nan'), float('inf'), True, '0'):
            with self.subTest(value=value):
                sample.getInfo.return_value = value
                self.assert_unavailable(lambda: self.adapter.get_elevation(-23, -46))
        for value in (0, -8, 123.5):
            sample.getInfo.return_value = value
            self.assertEqual(self.adapter.get_elevation(-23, -46), value)
        self.sdk.Image.assert_called_with('USGS/SRTMGL1_003')
        self.image.sample.assert_called_with(
            region=self.sdk.Geometry.Point.return_value, scale=30, geometries=True)

    def test_risk_does_not_swallow_provider_error_or_calculate_persisted_success(self):
        app = create_app()
        db = MagicMock()
        db.query.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(name='Rio', type='river'), 120.0, 'POINT(-46.0 -23.0)')
        polygon = {'type': 'Polygon', 'coordinates': [[[-46, -23], [-46, -22.9],
                    [-45.9, -22.9], [-46, -23]]]}
        with patch('database.SessionLocal', return_value=db), \
                patch('routers.risk.get_osm_service'), patch('routers.risk.elevation_m', return_value=8), \
                patch('routers.risk.get_data_provider') as factory, \
                patch('routers.risk.RiskCalculator.calculate_risk') as calculate, \
                patch('routers.risk.get_ai_assessment') as ai:
            for method in ('get_soil_data', 'get_water_frequency'):
                provider = MagicMock()
                provider.get_soil_data.return_value = {
                    'class_id': 3, 'class_name': 'Formação Florestal', 'is_permeable': True}
                getattr(provider, method).side_effect = ServiceUnavailable('DATA_UNAVAILABLE')
                factory.return_value = provider
                response = TestClient(app, raise_server_exceptions=False).post('/geo/risk', json={'polygon': polygon})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'detail': {'code': 'DATA_UNAVAILABLE',
                                                              'message': MESSAGES['DATA_UNAVAILABLE']}})
            calculate.assert_not_called()
            ai.assert_not_called()
            db.add.assert_not_called()
            db.commit.assert_not_called()
