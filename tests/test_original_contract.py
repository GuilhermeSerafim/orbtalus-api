import copy
import json
from types import SimpleNamespace
from unittest.mock import call, patch

from risk_support import RiskTestCase, POLYGON
from core.errors import MESSAGES


class OriginalContractTests(RiskTestCase):
    def test_polygon_and_feature_keep_exact_original_success_and_projection(self):
        for polygon in (POLYGON, {'type': 'Feature', 'geometry': POLYGON, 'properties': {}}):
            with self.subTest(kind=polygon['type']):
                self.elevation.side_effect = [0, 8]
                self.db.reset_mock()
                response = self.post_risk(polygon)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {
                    'distancia_rio_m': 120.1, 'queda_relativa_m': -8.0,
                    'rio_mais_proximo': 'Rio Original', 'tipo_hidrografia': 'river',
                    'resposta_ia': 'Parecer técnico original.', 'risk_level': 'Médio',
                    'risk_calculation': {'confidence': 1.0, 'total_score': 0.47,
                        'component_scores': {'topography': 0.7, 'water_frequency': 0.4,
                                             'soil_permeability': 0.0},
                        'weights_applied': {'topography': 0.5, 'water_frequency': 0.3,
                                            'soil_permeability': 0.2}},
                    'environmental_data': {'soil': {'class_id': 3, 'class_name': 'Formação Florestal',
                        'is_permeable': True}, 'water_frequency': {'years': 0, 'confidence': 1.0},
                        'data_source': 'MapBiomas', 'provider_status': 'OK'},
                    'debug_coords': {'rio_lat': -23.0, 'rio_lon': -46.0}})
                self.calculate.assert_called_with(distance_m=120.123, elevation_diff_m=-8.0,
                    water_frequency_years=0, is_permeable=True, soil_class_id=3)
                self.assertEqual(self.elevation.call_args_list[-1], call(-23.0, -46.0))
                self.db.add.assert_called_once()
                assessment = self.db.add.call_args.args[0]
                projection = {key: getattr(assessment, key) for key in (
                    'lat', 'lon', 'risk_level', 'explanation', 'river_name', 'distance_m',
                    'water_frequency_30y', 'soil_type', 'soil_class_id', 'is_permeable')}
                self.assertEqual(projection, dict(lat=-23.1, lon=-46.1, risk_level='Médio',
                    explanation='Parecer técnico original.', river_name='Rio Original',
                    distance_m=120.123, water_frequency_30y=0, soil_type='Formação Florestal',
                    soil_class_id=3, is_permeable=True))
                self.db.commit.assert_called_once()
                self.db.refresh.assert_not_called()
                self.db.close.assert_called_once()

    def test_zero_elevations_are_valid(self):
        self.elevation.side_effect = [0, 0]
        response = self.post_risk()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['queda_relativa_m'], 0)
        self.assertEqual(self.calculate.call_args.kwargs['elevation_diff_m'], 0)

    def test_invalid_input_precedes_session_and_all_providers_without_configuration(self):
        invalid = [None, {}, [], 'private input', {'type': 'Point', 'coordinates': [-46, -23]},
            {'type': 'Feature', 'geometry': None}, {'type': 'FeatureCollection', 'features': []},
            {'type': 'Polygon', 'coordinates': []},
            {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1], [2, 2], [0, 0]]]},
            {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]}]
        for value in (True, None, '0', float('nan'), float('inf'), -float('inf'), 181, -181):
            item = copy.deepcopy(POLYGON)
            item['coordinates'][0][1][0] = value
            invalid.append(item)
        item = copy.deepcopy(POLYGON)
        item['coordinates'][0][1][1] = 91
        invalid.append(item)
        item = copy.deepcopy(POLYGON)
        item['coordinates'][0].pop()
        invalid.append(item)
        item = copy.deepcopy(POLYGON)
        item['coordinates'].append([[0, 0], [1, 0], [1, 1], [0, 0]])  # hole outside
        invalid.append(item)
        for route in ('risk', 'distance', 'hydrology'):
            for polygon in invalid:
                with self.subTest(route=route, polygon=polygon):
                    response = self.client.post('/geo/' + route,
                        content=json.dumps({'polygon': polygon}), headers={'Content-Type': 'application/json'})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.json(), {'detail': {'code': 'INPUT_INVALID',
                        'message': MESSAGES['INPUT_INVALID']}})
            for content in ('{}', 'null', '[]', '{broken', '{"private":"secret"}'):
                response = self.client.post('/geo/' + route, content=content,
                                            headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()['detail']['code'], 'INPUT_INVALID')
        self.factory.assert_not_called()
        self.osm.assert_not_called()
        self.elevation.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_analysis()

    def test_missing_hydrography_risk_503_distance_404(self):
        self.db.query.return_value.order_by.return_value.first.return_value = None
        response = self.post_risk()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['code'], 'HYDROLOGY_UNAVAILABLE')
        self.assertEqual(self.client.post('/geo/distance', json={'polygon': POLYGON}).status_code, 404)
        self.elevation.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_analysis()

    def test_distant_river_cannot_supply_local_hydrography(self):
        first = self.db.query.return_value.order_by.return_value.first
        river, _, contact = first.return_value
        for meters in (306476.416, 5000.01):
            with self.subTest(meters=meters):
                self.elevation.side_effect = [0, 8]
                first.return_value = (river, meters, contact)
                response = self.post_risk()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'HYDROLOGY_UNAVAILABLE')
                self.elevation.assert_not_called()
                self.provider_factory.assert_not_called()
                self.assert_no_analysis()

    def test_distance_endpoint_rejects_nearest_record_outside_search_radius(self):
        first = self.db.query.return_value.order_by.return_value.first
        river, _, _ = first.return_value
        first.return_value = (river, 5000.01)
        response = self.client.post('/geo/distance', json={'polygon': POLYGON})
        self.assertEqual(response.status_code, 404, response.text)

    def test_search_radius_includes_its_boundary(self):
        first = self.db.query.return_value.order_by.return_value.first
        river, _, contact = first.return_value
        first.return_value = (river, 5000, contact)
        self.assertEqual(self.post_risk().json()['distancia_rio_m'], 5000)
        first.return_value = (river, 5000)
        response = self.client.post('/geo/distance', json={'polygon': POLYGON})
        self.assertEqual(response.json()['distancia_rio_m'], 5000)

    def test_distance_uses_original_columns_and_shape(self):
        row = self.db.query.return_value.order_by.return_value.first.return_value
        self.db.query.return_value.order_by.return_value.first.return_value = row[:2]
        response = self.client.post('/geo/distance', json={'polygon': POLYGON})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'distancia_rio_m': 120.1,
            'rio_mais_proximo': 'Rio Original', 'waterway': 'river',
            'nearest_point': {'lon': -46.1, 'lat': -23.1}})
        self.assert_no_analysis()

    def test_polygon_with_hole_and_feature_distance_are_accepted(self):
        polygon = copy.deepcopy(POLYGON)
        polygon['coordinates'].append([
            [-46.15, -23.15], [-46.1, -23.15], [-46.1, -23.1], [-46.15, -23.15]])
        row = self.db.query.return_value.order_by.return_value.first.return_value
        self.db.query.return_value.order_by.return_value.first.return_value = row[:2]
        response = self.client.post('/geo/distance', json={'polygon': {
            'type': 'Feature', 'geometry': polygon, 'properties': {}}})
        self.assertEqual(response.status_code, 200, response.text)

    def test_shapely_failure_is_input_invalid_before_session(self):
        from shapely.errors import ShapelyError
        with patch('core.geometry.shape', side_effect=ShapelyError('private geometry')):
            response = self.post_risk()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['code'], 'INPUT_INVALID')
        self.factory.assert_not_called()
        self.osm.assert_not_called()

    def test_invalid_distance_rejected_by_distance_endpoint(self):
        row = self.db.query.return_value.order_by.return_value.first.return_value
        for value in (None, True, float('nan'), float('inf'), -1):
            with self.subTest(value=value):
                self.db.query.return_value.order_by.return_value.first.return_value = (row[0], value)
                response = self.client.post('/geo/distance', json={'polygon': POLYGON})
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'DATA_UNAVAILABLE')
        self.db.query.return_value.order_by.return_value.first.return_value = (row[0], 0)
        self.assertEqual(self.client.post('/geo/distance', json={'polygon': POLYGON}).json()['distancia_rio_m'], 0)

    def test_invalid_environmental_structure_and_domains_never_calculate(self):
        original_soil = self.provider.get_soil_data.return_value
        original_water = self.provider.get_water_frequency.return_value
        cases = [('get_soil_data', value) for value in (None, {}, [], {'class_id': 3})]
        cases += [('get_water_frequency', value) for value in (None, {}, [], {'frequency_years': 0})]
        for key, values, original, method in (
            ('is_permeable', (None, 0, 1, 'true', False), original_soil, 'get_soil_data'),
            ('class_id', (0, 999, 3.5), original_soil, 'get_soil_data'),
            ('class_name', ('', ' ', None, 3, '\x00'), original_soil, 'get_soil_data'),
            ('frequency_years', (-1, 31, 0.5), original_water, 'get_water_frequency'),
            ('confidence', (-0.1, 1.1), original_water, 'get_water_frequency')):
            cases += [(method, {**original, key: value}) for value in values]
        for method, value in cases:
            with self.subTest(method=method, value=value):
                self.elevation.side_effect = [0, 8]
                self.provider.get_soil_data.return_value = original_soil
                self.provider.get_water_frequency.return_value = original_water
                getattr(self.provider, method).return_value = value
                response = self.post_risk()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'DATA_UNAVAILABLE')
                self.assert_no_analysis()

    def test_invalid_required_ai_explanation_never_persists(self):
        for explanation in (None, '', ' ', '\x00', 0, True, [], {}):
            with self.subTest(explanation=explanation):
                self.elevation.side_effect = [0, 8]
                self.ai.return_value = SimpleNamespace(explanation=explanation)
                response = self.post_risk()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'AI_UNAVAILABLE')
                self.db.add.assert_not_called()
                self.db.commit.assert_not_called()

    def test_finite_elevations_with_overflowing_difference_are_unavailable(self):
        self.elevation.side_effect = [1e308, -1e308]
        response = self.post_risk()
        self.assertEqual(response.status_code, 503)
        self.assert_no_analysis()

    def test_invalid_measurements_stop_before_calculation_ai_and_persistence(self):
        original_row = self.db.query.return_value.order_by.return_value.first.return_value
        for field in ('distance', 'point_elevation', 'river_elevation', 'frequency', 'confidence', 'class_id'):
            for value in (None, float('nan'), float('inf'), -float('inf'), True, False):
                with self.subTest(field=field, value=value):
                    self.db.query.return_value.order_by.return_value.first.return_value = original_row
                    self.elevation.side_effect = [0, 8]
                    self.provider.get_water_frequency.return_value = {'frequency_years': 0, 'confidence': 1.0}
                    self.provider.get_soil_data.return_value = {
                        'class_id': 3, 'class_name': 'Formação Florestal', 'is_permeable': True}
                    if field == 'distance':
                        self.db.query.return_value.order_by.return_value.first.return_value = (
                            original_row[0], value, original_row[2])
                    elif field.endswith('elevation'):
                        self.elevation.side_effect = [value, 8] if field == 'point_elevation' else [0, value]
                    elif field in ('frequency', 'confidence'):
                        key = 'frequency_years' if field == 'frequency' else field
                        self.provider.get_water_frequency.return_value[key] = value
                    else:
                        self.provider.get_soil_data.return_value[field] = value
                    response = self.post_risk()
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertEqual(response.json()['detail']['code'], 'DATA_UNAVAILABLE')
                    self.assert_no_analysis()

    def test_invalid_river_point_rejected_before_elevation(self):
        row = self.db.query.return_value.order_by.return_value.first.return_value
        for value in (None, '', 'private invalid', 'POINT EMPTY', 'POINT(NaN -23)',
                      'POINT(-46 Infinity)', 'LINESTRING(0 0, 1 1)', 'POINT(181 -23)', 'POINT(-46 -91)'):
            with self.subTest(value=value):
                self.db.query.return_value.order_by.return_value.first.return_value = (row[0], row[1], value)
                response = self.post_risk()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'DATA_UNAVAILABLE')
                self.elevation.assert_not_called()
                self.assert_no_analysis()
