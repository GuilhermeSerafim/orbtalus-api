import unittest

from offline_guard import offline_boundaries


class HydrographySchemaTests(unittest.TestCase):
    def test_runtime_models_can_store_source_identity_and_fetch_evidence(self):
        with offline_boundaries():
            import models
        water = models.WaterBody.__table__
        self.assertTrue({'source', 'source_id', 'fetched_at', 'source_updated_at'} <= set(water.c.keys()))
        self.assertTrue(all(water.c[name].nullable for name in
                            ('source', 'source_id', 'fetched_at', 'source_updated_at')))
        self.assertTrue(water.c.fetched_at.type.timezone)
        self.assertTrue(water.c.source_updated_at.type.timezone)
        self.assertTrue(any(i.unique and i.columns.keys() == ['source', 'source_id'] for i in water.indexes))
        fetch = models.HydrographyFetch.__table__
        self.assertTrue({'id', 'center', 'radius_m', 'fetched_at'} <= set(fetch.c.keys()))
        self.assertEqual((fetch.c.center.type.geometry_type, fetch.c.center.type.srid), ('POINT', 4326))
        self.assertTrue(fetch.c.fetched_at.type.timezone)
        self.assertFalse(any(fetch.c[name].nullable for name in ('center', 'radius_m', 'fetched_at')))

    def test_upgrade_never_connects_with_an_original_or_mismatched_target(self):
        from unittest.mock import patch
        from scripts import upgrade_hydrography
        contract = dict(host='localhost', port=5555, database='scratch', schema='public',
                        purpose='hydrography-cache-upgrade')
        with patch.object(upgrade_hydrography, 'create_engine') as engine:
            for target, url in ((contract, 'postgresql://localhost:5555/other'),
                                (dict(contract, purpose='disposable-original-baseline'),
                                 'postgresql://localhost:5555/scratch')):
                with self.assertRaises(ValueError):
                    upgrade_hydrography.upgrade(target, url=url)
            engine.assert_not_called()
