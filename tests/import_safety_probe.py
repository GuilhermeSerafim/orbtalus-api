"""Executed in a clean child process; never contacts a provider or database."""
import importlib
import json
import socket
from unittest.mock import patch

attempts = []


def forbidden(*args, **kwargs):
    attempts.append("forbidden_boundary")
    raise AssertionError("Import attempted an external boundary")


socket.create_connection = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden

with (
    patch("sqlalchemy.create_engine", side_effect=forbidden),
    patch("sqlalchemy.schema.MetaData.create_all", side_effect=forbidden),
    patch("psycopg2.connect", side_effect=forbidden),
    patch("dotenv.load_dotenv", side_effect=forbidden),
    patch("ee.Initialize", side_effect=forbidden),
    patch("ee.Authenticate", side_effect=forbidden),
    patch("overpy.Overpass", side_effect=forbidden),
    patch("langchain_openai.OpenAIEmbeddings", side_effect=forbidden),
    patch("langchain_openai.ChatOpenAI", side_effect=forbidden),
    patch("requests.sessions.Session.request", side_effect=forbidden),
):
    for name in (
        "core.config", "database", "models", "main", "routers.risk",
        "routers.distance", "routers.ai_vertical", "providers.mapbiomas_adapter",
        "services.ai_service", "services.osm_service", "migrate_rivers",
        "setup_gee", "test_risk_api", "ai_vertical", "core.db_target", "scripts.init_original_db",
    ):
        importlib.import_module(name)

assert not attempts, attempts
print(json.dumps({"boundary_attempts": len(attempts), "imports": 16}))
