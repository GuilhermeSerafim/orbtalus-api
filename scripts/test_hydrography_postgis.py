"""Run opt-in HTTP and cache integration tests against a throwaway local PostGIS.

Run with the backend Python environment and Docker image postgis/postgis:15-3.3
already available locally: python scripts/test_hydrography_postgis.py
"""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import overpy
from sqlalchemy import create_engine, text, URL

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from offline_guard import offline_boundaries

with offline_boundaries():
    import models
    from core.demo_quota import admit_demo_request
    from main import create_app
    from services.osm_service import OSMService


@contextmanager
def disposable_postgis():
    context = subprocess.check_output(["docker", "context", "show"], text=True).strip()
    docker = ["docker", "--context", context]
    host = subprocess.check_output(
        docker + ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}", context],
        text=True).strip()
    if not host.startswith(("unix://", "npipe://")):
        raise RuntimeError("Integration requires a local Docker socket")
    password = secrets.token_hex(24)
    cluster = "hydro_test_" + secrets.token_hex(8)
    container = subprocess.check_output(
        docker + ["run", "--rm", "-d", "--pull=never", "-p", "127.0.0.1::5432",
                  "-e", "POSTGRES_PASSWORD", "--tmpfs", "/var/lib/postgresql/data",
                  "postgis/postgis:15-3.3", "postgres", "-c", "cluster_name=" + cluster],
        env={**os.environ, "POSTGRES_PASSWORD": password}, text=True).strip()
    try:
        addr = subprocess.check_output(docker + ["port", container, "5432/tcp"], text=True).strip()
        ip, port = addr.rsplit(":", 1)
        if ip != "127.0.0.1":
            raise RuntimeError("Unexpected database endpoint")
        engine = create_engine(URL.create("postgresql+psycopg2", username="postgres",
                               password=password, host=ip, port=int(port), database="postgres"),
                               connect_args={"hostaddr": ip, "options": "-c statement_timeout=10000"})
        try:
            for _ in range(60):
                if subprocess.run(docker + ["exec", container, "pg_isready", "-q", "-h", ip]).returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Local PostGIS did not become ready")
            with engine.connect() as conn:
                if conn.execute(text("SHOW cluster_name")).scalar_one() != cluster:
                    raise RuntimeError("Connected to an unexpected Postgres cluster")
            models.Base.metadata.create_all(engine)
            # Pre-open connections before the offline guard blocks psycopg2.connect.
            with engine.connect(), engine.connect(), engine.connect():
                pass
            yield engine
        finally:
            engine.dispose()
    finally:
        subprocess.run(docker + ["rm", "-f", container], check=True, stdout=subprocess.DEVNULL)


def waterways(*names, latitude_step=0.001, modified="2024-03-01T12:00:00Z"):
    elements = []
    for index, name in enumerate(names, start=1):
        # The first way is about 111 m from the selection at (0, 0).
        for node, lon in [(index * 2, 0), (index * 2 + 1, 0.01)]:
            elements.append(dict(type="node", id=node, lat=index * latitude_step, lon=lon))
        elements.append(dict(type="way", id=index, nodes=[index * 2, index * 2 + 1],
                             tags=dict(name=name, waterway="stream"), timestamp=modified))
    return overpy.Overpass().parse_json(json.dumps({"elements": elements}))


class HydrographyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = cls.enterClassContext(disposable_postgis())

    def setUp(self):
        with self.engine.begin() as conn:
            conn.execute(text("TRUNCATE water_bodies, hydrography_fetches"))
        blocked = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, blocked, [])
        self.enterContext(patch("database.get_engine", return_value=self.engine))
        self.osm = OSMService()
        self.osm.api = Mock()
        self.enterContext(patch("routers.risk.get_osm_service", return_value=self.osm))
        app = create_app()
        app.dependency_overrides[admit_demo_request] = lambda: None
        self.client = self.enterContext(TestClient(app))

    def scalar(self, sql):
        with self.engine.connect() as conn:
            return conn.execute(text(sql)).scalar_one()

    def expire(self):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE hydrography_fetches SET fetched_at = now() - interval '31 days'"))

    def post(self, route):
        ring = [[-0.001, -0.001], [0.001, -0.001], [0.001, 0.001],
                [-0.001, 0.001], [-0.001, -0.001]]
        return self.client.post('/geo/' + route, json={"polygon": {"type": "Polygon", "coordinates": [ring]}})

    def assert_risk_unavailable_before_providers(self):
        with ExitStack() as stack:
            providers = [stack.enter_context(patch("routers.risk." + name))
                         for name in ("get_data_provider", "get_ai_assessment", "elevation_m")]
            response = self.post("risk")
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["detail"]["code"], "HYDROLOGY_UNAVAILABLE")
            for provider in providers:
                provider.assert_not_called()
        self.assertEqual(self.scalar("SELECT count(*) FROM risk_assessments"), 0)

    def test_six_legacy_rows_do_not_hide_a_closer_creek(self):
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO water_bodies(name, type, geom) "
                              "SELECT 'Legacy', 'river', ST_GeomFromText('LINESTRING(0 0.02, 0.01 0.02)',4326) "
                              "FROM generate_series(1,6)"))
        self.osm.api.query.return_value = waterways("New Creek")
        self.assertIsNotNone(self.osm.fetch_and_save_rivers(0, 0))
        self.osm.api.query.assert_called_once()
        distance = self.post("distance")
        self.assertEqual(distance.status_code, 200, distance.text)
        self.assertEqual(distance.json()["rio_mais_proximo"], "New Creek")
        self.assertAlmostEqual(distance.json()["distancia_rio_m"], 111, delta=1)
        updated = self.scalar("SELECT source_updated_at FROM water_bodies WHERE source='osm' AND source_id='way/1'")
        self.assertEqual(updated, datetime(2024, 3, 1, 12, tzinfo=timezone.utc))

    def test_empty_coverage_is_cached_for_fully_contained_disks_only(self):
        self.osm.api.query.return_value = waterways()
        recorded = self.osm.fetch_and_save_rivers(0, 0)
        self.assertIsNotNone(recorded)
        # About 550 m east, the 5 km search disk fits within the original 6 km.
        self.assertEqual(self.osm.fetch_and_save_rivers(0, 0.005), recorded)
        self.osm.api.query.assert_called_once()
        # About 2.2 km east. A large overlap still leaves part of the request uncovered.
        self.assertIsNotNone(self.osm.fetch_and_save_rivers(0, 0.02))
        self.assertEqual(self.osm.api.query.call_count, 2)
        self.assertEqual(self.post("risk").status_code, 503)
        self.assertEqual(self.osm.api.query.call_count, 2)

    def test_refresh_updates_in_place_and_excludes_disappeared_way(self):
        self.osm.api.query.return_value = waterways("Removed", "Survivor")
        original_fetch = self.osm.fetch_and_save_rivers(0, 0)
        self.assertIsNotNone(original_fetch)
        first = self.scalar("SELECT id FROM water_bodies WHERE source_id='way/2'")
        self.assertEqual(self.post("distance").json()["rio_mais_proximo"], "Removed")
        self.expire()
        both = waterways("Removed", "Updated", latitude_step=0.002, modified="2024-05-10T12:00:00Z")
        refreshed = overpy.Result(elements=[*both.nodes, both.ways[1]])
        self.osm.api.query.return_value = refreshed
        new_fetch = self.osm.fetch_and_save_rivers(0, 0)
        self.assertGreater(new_fetch, original_fetch)
        self.assertEqual(self.scalar("SELECT id FROM water_bodies WHERE source_id='way/2'"), first)
        self.assertEqual(self.scalar("SELECT count(*) FROM water_bodies WHERE source_id='way/2'"), 1)
        self.assertEqual(self.scalar("SELECT fetched_at FROM water_bodies WHERE source_id='way/2'"), new_fetch)
        self.assertEqual(self.scalar("SELECT source_updated_at FROM water_bodies WHERE source_id='way/2'"),
                         datetime(2024, 5, 10, 12, tzinfo=timezone.utc))
        local = self.post("distance").json()
        self.assertEqual(local["rio_mais_proximo"], "Updated")
        self.assertAlmostEqual(local["distancia_rio_m"], 445, delta=1)

    def test_expired_coverage_and_failed_refresh_prevent_risk_and_persistence(self):
        self.osm.api.query.return_value = waterways("Old Creek")
        self.assertIsNotNone(self.osm.fetch_and_save_rivers(0, 0))
        self.expire()
        stamp = self.scalar("SELECT max(fetched_at) FROM hydrography_fetches")
        self.osm.api.query.side_effect = TimeoutError("simulated outage")
        self.assert_risk_unavailable_before_providers()
        self.assertEqual(self.scalar("SELECT max(fetched_at) FROM hydrography_fetches"), stamp)
        self.assertEqual(self.post("distance").status_code, 404)
        self.osm.api.query.side_effect = None
        self.osm.api.query.return_value = waterways()
        far_receipt = self.osm.fetch_and_save_rivers(1, 1)
        self.assertIsNotNone(far_receipt)
        self.assertEqual(self.scalar("SELECT min(fetched_at) FROM hydrography_fetches"), far_receipt)
        self.assertIsNotNone(self.osm.fetch_and_save_rivers(0, 0))
        self.assertEqual(self.scalar("SELECT count(*) FROM hydrography_fetches"), 2)
        self.assertEqual(self.scalar("SELECT min(fetched_at) FROM hydrography_fetches"), far_receipt)

    def test_late_refresh_does_not_overwrite_a_newer_observation(self):
        newer = OSMService()
        newer.api = Mock()
        both = waterways("Removed", "Current", latitude_step=0.002, modified="2024-05-10T12:00:00Z")
        newer.api.query.return_value = overpy.Result(elements=[*both.nodes, both.ways[1]])

        # Complete the newer independent DB session while the older one awaits Overpass.
        def release_older_response(*args, **kwargs):
            self.assertIsNotNone(newer.fetch_and_save_rivers(0, 0))
            return waterways("Removed", "Superseded")

        self.osm.api.query.side_effect = release_older_response
        self.assertIsNotNone(self.osm.fetch_and_save_rivers(0, 0))
        self.assertEqual(self.scalar("SELECT count(*) FROM hydrography_fetches"), 2)
        newest = self.scalar("SELECT max(fetched_at) FROM hydrography_fetches")
        self.assertLess(self.scalar("SELECT min(fetched_at) FROM hydrography_fetches"), newest)
        self.assertEqual(self.scalar("SELECT fetched_at FROM water_bodies WHERE source_id='way/2'"), newest)
        self.assertEqual(self.scalar("SELECT source_updated_at FROM water_bodies WHERE source_id='way/2'"),
                         datetime(2024, 5, 10, 12, tzinfo=timezone.utc))
        response = self.post("distance")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rio_mais_proximo"], "Current")
        self.assertAlmostEqual(response.json()["distancia_rio_m"], 445, delta=1)

    def test_risk_respects_newer_empty_coverage_when_older_positive_response_arrives_last(self):
        newer = OSMService()
        newer.api = Mock()
        newer.api.query.return_value = waterways()

        def release_older_response(*args, **kwargs):
            self.assertIsNotNone(newer.fetch_and_save_rivers(0, 0))
            return waterways("Obsolete")

        self.osm.api.query.side_effect = release_older_response
        self.assert_risk_unavailable_before_providers()


if __name__ == "__main__":
    unittest.main(verbosity=2)
