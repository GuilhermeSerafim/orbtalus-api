import os
import unittest
from unittest.mock import patch
import requests
from offline_guard import offline_boundaries

with offline_boundaries() as import_attempts:
    from core.errors import ServiceUnavailable
    from services.elevation_service import elevation_m
assert not import_attempts


class ElevationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.get = self.enterContext(patch('services.elevation_service.requests.get'))
        self.response = self.get.return_value

    def test_zero_negative_and_positive_are_real_measurements(self):
        for value in (0, -8, 123.5):
            self.response.json.return_value = {'elevation': [value]}
            self.assertEqual(elevation_m(-23, -46), value)
        self.get.assert_called_with(
            'https://api.open-meteo.com/v1/elevation?latitude=-23&longitude=-46', timeout=10)
        self.assertEqual(self.response.raise_for_status.call_count, 3)

    def test_missing_malformed_nonfinite_and_boolean_values_fail(self):
        for payload in (None, [], {}, {'elevation': None}, {'elevation': []},
                        {'elevation': '0'}, {'elevation': [None]}, {'elevation': [True]},
                        {'elevation': [False]}, {'elevation': ['0']},
                        {'elevation': [float('nan')]}, {'elevation': [float('inf')]},
                        {'elevation': [-float('inf')]}, {'elevation': [0, 8]}):
            with self.subTest(payload=payload):
                self.response.json.return_value = payload
                with self.assertRaises(ServiceUnavailable) as error:
                    elevation_m(-23, -46)
                self.assertEqual(error.exception.code, 'DATA_UNAVAILABLE')

    def test_transport_http_and_json_errors_are_safe(self):
        for target, failure in ((self.get, requests.Timeout('private URL')),
                                (self.response.raise_for_status, requests.HTTPError('private body')),
                                (self.response.json, ValueError('private invalid JSON'))):
            with self.subTest(failure=type(failure).__name__):
                target.side_effect = failure
                with self.assertRaises(ServiceUnavailable) as error:
                    elevation_m(-23, -46)
                self.assertEqual(error.exception.code, 'DATA_UNAVAILABLE')
                self.assertNotIn('private', str(error.exception))
                target.side_effect = None

    def test_unexpected_programming_error_remains_an_error(self):
        self.get.side_effect = RuntimeError('bug')
        with self.assertRaisesRegex(RuntimeError, 'bug'):
            elevation_m(-23, -46)
