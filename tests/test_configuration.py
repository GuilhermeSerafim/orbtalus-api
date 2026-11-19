import os
import socket
import unittest
from unittest.mock import MagicMock, patch
from offline_guard import offline_boundaries

# Guard before project imports, including the baseline failure.
def forbidden(*args, **kwargs):
    raise AssertionError("Tests must not contact external services")


with patch.dict(os.environ, {}, clear=True), offline_boundaries() as import_attempts:
    import database
    from core.config import get_settings
    from core.errors import ServiceUnavailable
    from main import create_app

assert not import_attempts, import_attempts

from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def db_error():
    return OperationalError("private SQL", {}, Exception("private DSN"))


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        attempts = self.enterContext(offline_boundaries())
        self.addCleanup(self.assertEqual, attempts, [])
        self.addCleanup(database.get_engine.cache_clear)



class ConfigurationTests(OfflineTestCase):
    def test_local_hydrology_app_serves_river_lookup_without_analysis_routes(self):
        from main import create_hydrology_app
        local = TestClient(create_hydrology_app())
        paths = local.get("/openapi.json").json()["paths"]
        self.assertIn("post", paths["/geo/hydrology"])
        body = paths["/geo/hydrology"]["post"]["requestBody"]["content"]["application/json"]
        self.assertIn("example", body, "Swagger should open with a usable hydrology polygon")
        self.assertNotIn("/geo/risk", paths)
        self.assertNotIn("/ai/ask-ai", paths)
        self.assertIn("/geo/risk", create_app().openapi()["paths"])

    def test_config_is_read_on_use_and_never_defaults_to_database(self):
        self.assertIsNone(get_settings().database_url)
        with self.assertRaises(ServiceUnavailable) as error:
            database.SessionLocal()
        self.assertEqual(error.exception.code, "CONFIG_UNAVAILABLE")
        for url in ("sqlite:///test.db", "not a url", "postgresql://localhost"):
            with self.subTest(url=url), patch.dict(os.environ, {"DATABASE_URL": url}):
                with self.assertRaises(ServiceUnavailable):
                    database.SessionLocal()

    def test_engine_and_sessions_are_lazy_and_reused(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:unused@db/example"}), \
                patch("database.create_engine") as engine, patch("database.sessionmaker") as factory:
            self.assertEqual(engine.call_count, 0)
            database.SessionLocal()
            database.SessionLocal()
            engine.assert_called_once()
            self.assertEqual(factory.return_value.call_count, 2)

    def test_liveness_and_missing_readiness(self):
        with patch("database.SessionLocal", side_effect=ServiceUnavailable("CONFIG_UNAVAILABLE")) as factory:
            client = TestClient(create_app())
            response = client.get("/ping")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("database", response.json())
            factory.assert_not_called()
            self.assertEqual(client.get("/ready").status_code, 503)

    def test_cors_exact_origin_and_no_credentials(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "http://127.0.0.1:3310,https://example.com"}):
            client = TestClient(create_app())
        for origin, status in (("http://127.0.0.1:3310", 200),
                               ("http://localhost:3310", 400),
                               ("https://example.com.attacker.test", 400)):
            response = client.options("/geo/risk", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
            self.assertEqual(response.status_code, status)
            self.assertNotIn("access-control-allow-credentials", response.headers)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin if status == 200 else None)
        self.assertEqual(get_settings().cors_origins, ())

    def test_bad_cors_configuration_rejected(self):
        for value in ("*", "https://example.com/path", "https://u:p@example.com",
                      "ftp://example.com", "https://example.com?x=1", "https://example.com/#a",
                      "https://@example.com", "https://example.com:", "https://example.com:invalid", "https://example.com,", "https://example.com/"):
            with self.subTest(value=value), patch.dict(os.environ, {"CORS_ORIGINS": value}):
                with self.assertRaises(ServiceUnavailable):
                    get_settings()

    def test_ready_checks_database_postgis_and_runtime_schema(self):
        import models
        session = MagicMock()
        inspector = MagicMock()
        inspector.get_columns.side_effect = lambda table, schema: [
            {"name": col.name, "type": col.type, "nullable": col.nullable}
            for col in models.Base.metadata.tables[table].columns]
        inspector.get_indexes.return_value = [{
            'name': 'uq_water_bodies_source_id', 'unique': True, 'column_names': ['source', 'source_id']}]
        session.execute.return_value.scalar_one.side_effect = [1, '3.5.0', 'public', True, True, True]
        with patch("database.SessionLocal", return_value=session), \
                patch("main.inspect", return_value=inspector), \
                patch("routers.risk.get_data_provider", side_effect=forbidden):
            response = TestClient(create_app()).get("/ready")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "local_dependencies")
        self.assertEqual(response.json()["providers"], "not_verified")
        sql = [str(call.args[0]) for call in session.execute.call_args_list]
        self.assertEqual(sql[:3], ["SELECT 1", "SELECT PostGIS_Version()", "SELECT current_schema()"])
        self.assertEqual(len(sql), 6)
        for query in sql[3:]:
            self.assertIn('to_regclass', query)
        self.assertEqual([c.kwargs for c in inspector.get_columns.call_args_list],
                         [{'schema': 'public'}] * 3)
        session.close.assert_called_once()

    def test_readiness_rejects_missing_hydrology_upsert_index(self):
        import models
        session, inspector = MagicMock(), MagicMock()
        inspector.get_columns.side_effect = lambda table, **kw: [
            {'name': c.name, 'type': c.type, 'nullable': c.nullable}
            for c in models.Base.metadata.tables[table].columns]
        inspector.get_indexes.return_value = []
        session.execute.return_value.scalar_one.side_effect = [1, '3.5.0', 'public', True, True, True]
        with patch('database.SessionLocal', return_value=session), patch('main.inspect', return_value=inspector):
            response = TestClient(create_app()).get('/ready')
        self.assertEqual(response.status_code, 503, response.text)

    def test_readiness_rejects_alternate_or_shadow_schema(self):
        import models
        for effective, resolved in (('shadow', True), ('public', False)):
            session, inspector = MagicMock(), MagicMock()
            inspector.get_columns.side_effect = lambda table, **kwargs: [
                {'name': col.name, 'type': col.type, 'nullable': col.nullable}
                for col in models.Base.metadata.tables[table].columns]
            session.execute.return_value.scalar_one.side_effect = [1, '3.5.0', effective, resolved]
            with self.subTest(effective=effective, resolved=resolved), \
                    patch('database.SessionLocal', return_value=session), \
                    patch('main.inspect', return_value=inspector):
                response = TestClient(create_app()).get('/ready')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['detail']['code'], 'DATABASE_UNAVAILABLE')
            session.rollback.assert_called_once()
            session.close.assert_called_once()

    def test_readiness_rejects_failed_database_postgis_or_schema(self):
        for mode in ("db", "postgis", "schema"):
            session = MagicMock()
            inspector = MagicMock()
            inspector.get_columns.return_value = []
            if mode == "db":
                session.execute.side_effect = db_error()
            elif mode == "postgis":
                session.execute.side_effect = [MagicMock(), db_error()]
            with self.subTest(mode=mode), patch("database.SessionLocal", return_value=session), \
                    patch("main.inspect", return_value=inspector):
                response = TestClient(create_app()).get("/ready")
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private", response.text)
                session.rollback.assert_called_once()
                session.close.assert_called_once()


class SessionTests(OfflineTestCase):
    def test_factory_failure_known_vs_programming_error(self):
        for error, status in ((db_error(), 503), (ValueError("bug"), 500)):
            with self.subTest(status=status), patch("database.SessionLocal", side_effect=error):
                response = TestClient(create_app(), raise_server_exceptions=False).get("/debug-db")
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private", response.text)

    def test_yield_preserves_http_and_bug_even_if_cleanup_fails(self):
        for original in (HTTPException(422, "invalid"), HTTPException(503, "unavailable"), ValueError("bug")):
            for cleanup_fails in (False, True):
                session = MagicMock()
                if cleanup_fails:
                    session.rollback.side_effect = db_error()
                    session.close.side_effect = db_error()
                with self.subTest(original=type(original), cleanup=cleanup_fails), \
                        patch("database.SessionLocal", return_value=session):
                    dependency = database.get_db()
                    self.assertIs(next(dependency), session)
                    with self.assertRaises(type(original)) as caught:
                        dependency.throw(original)
                    self.assertIs(caught.exception, original)
                    session.rollback.assert_called_once()
                    session.close.assert_called_once()

    def test_query_commit_failures_rollback_close_and_next_request_works(self):
        for stage in ("query", "commit"):
            failed, clean = MagicMock(), MagicMock()
            getattr(failed, stage).side_effect = db_error()
            app = create_app()

            @app.get("/session-test")
            def route(db=Depends(database.get_db, scope="function")):
                db.query()
                db.commit()
                return {"ok": True}

            with self.subTest(stage=stage), patch("database.SessionLocal", side_effect=[failed, clean]):
                client = TestClient(app)
                response = client.get("/session-test")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["detail"]["code"], "DATABASE_UNAVAILABLE")
                self.assertNotIn("private", response.text)
                self.assertEqual(client.get("/session-test").status_code, 200)
            failed.rollback.assert_called_once()
            failed.close.assert_called_once()
            clean.close.assert_called_once()

    def test_http_errors_remain_422_503_and_unexpected_bug_remains_500(self):
        for status in (422, 503, 500):
            session = MagicMock()
            session.rollback.side_effect = db_error()
            session.close.side_effect = db_error()
            app = create_app()

            @app.get("/error-test")
            def route(db=Depends(database.get_db, scope="function")):
                if status == 500:
                    raise ValueError("private programming error")
                raise HTTPException(status, "safe message")

            with self.subTest(status=status), patch("database.SessionLocal", return_value=session):
                response = TestClient(app, raise_server_exceptions=False).get("/error-test")
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private", response.text)
                session.rollback.assert_called_once()
                session.close.assert_called_once()

    def test_close_failure_is_safe(self):
        session = MagicMock()
        session.close.side_effect = db_error()
        with patch("database.SessionLocal", return_value=session):
            dep = database.get_db()
            next(dep)
            with self.assertRaises(ServiceUnavailable) as caught:
                next(dep)
        self.assertEqual(caught.exception.code, "DATABASE_UNAVAILABLE")

    def test_close_failure_before_response_returns_503(self):
        session = MagicMock()
        session.query.return_value.count.return_value = 1
        session.close.side_effect = db_error()
        with patch("database.SessionLocal", return_value=session):
            response = TestClient(create_app()).get("/debug-db")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "DATABASE_UNAVAILABLE")
