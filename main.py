from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import TIMESTAMP, VARCHAR, inspect, text
from sqlalchemy.orm import Session

from core.config import get_settings
from core.demo_quota import demo_mode
from core.errors import MESSAGES, ServiceUnavailable
from database import get_db
import models
from routers.distance import router as distance_router
from routers.risk import router as risk_router
from routers.ai_vertical import router as ai_router


def _matches_readiness_columns(table, columns):
    expected = set(table.columns.keys())
    if columns.keys() == expected:
        return True
    # The v1 API can keep serving while the atomic hydrography upgrade adds these columns.
    if table.name != "water_bodies" or "source" in expected:
        return False
    additions = {"source": VARCHAR, "source_id": VARCHAR,
                 "source_updated_at": TIMESTAMP, "fetched_at": TIMESTAMP}
    if columns.keys() != expected.union(additions):
        return False
    for name, required_type in additions.items():
        column = columns[name]
        actual_type = column["type"]
        if column["nullable"] is not True or not isinstance(actual_type, required_type):
            return False
        if required_type is VARCHAR and actual_type.length is not None:
            return False
        if required_type is TIMESTAMP and (
            not actual_type.timezone or getattr(actual_type, "precision", None) is not None
        ):
            return False
    return True


def create_app():
    app = FastAPI(
        title="GeoRisk API",
        description="Plataforma global e agnóstica para análise de risco hidrológico com foco em resiliência",
        version="2.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(get_settings().cors_origins),
        allow_credentials=False,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ServiceUnavailable)
    async def service_unavailable(request, error):
        return JSONResponse(status_code=503, content={"detail": error.detail})

    @app.exception_handler(RequestValidationError)
    async def input_invalid(request, error):
        return JSONResponse(status_code=422, content={'detail': {
            'code': 'INPUT_INVALID', 'message': MESSAGES['INPUT_INVALID']}})

    app.include_router(distance_router, prefix="/geo", tags=["Geoprocessamento"])
    app.include_router(risk_router, prefix="/geo", tags=["Análise de Risco"])
    if not demo_mode():
        app.include_router(ai_router, prefix="/ai", tags=["Inteligência Artificial"])

    @app.get("/ping", tags=["Health"])
    def ping():
        return {"status": "ok", "service": "GeoRisk API", "infra": "Agnostic/Multi-cloud"}

    @app.get("/", tags=["Health"])
    def read_root():
        return {"message": "GeoRisk API está online e resiliente!"}

    @app.get("/ready", tags=["Health"])
    def ready(db: Session = Depends(get_db, scope="function")):
        db.execute(text("SELECT 1")).scalar_one()
        if demo_mode():
            db.execute(text("SELECT 1 FROM orbtalus_demo.daily_usage LIMIT 1"))
        if not db.execute(text("SELECT PostGIS_Version()")).scalar_one():
            raise ServiceUnavailable("DATABASE_UNAVAILABLE")
        if db.execute(text('SELECT current_schema()')).scalar_one() != 'public':
            raise ServiceUnavailable('DATABASE_UNAVAILABLE')
        inspector = inspect(db.connection())
        for table in models.Base.metadata.sorted_tables:
            # Models are unqualified: detect search_path/temporary-table shadowing.
            same_relation = db.execute(text(
                'SELECT to_regclass(:qualified) = to_regclass(:unqualified)'),
                {'qualified': 'public.' + table.name, 'unqualified': table.name}).scalar_one()
            if same_relation is not True:
                raise ServiceUnavailable('DATABASE_UNAVAILABLE')
            columns = {column["name"]: column for column in inspector.get_columns(table.name, schema='public')}
            if not _matches_readiness_columns(table, columns):
                raise ServiceUnavailable("DATABASE_UNAVAILABLE")
            for expected in table.columns:
                actual = columns[expected.name]
                if (actual["nullable"] != expected.nullable
                        or actual["type"]._type_affinity is not expected.type._type_affinity):
                    raise ServiceUnavailable("DATABASE_UNAVAILABLE")
                if expected.name == "geom" and (
                    getattr(actual["type"], "srid", None) != 4326
                    or getattr(actual["type"], "geometry_type", None) != "GEOMETRY"
                ):
                    raise ServiceUnavailable("DATABASE_UNAVAILABLE")
        return {"status": "ok", "scope": "local_dependencies",
                "database": "ok", "postgis": "ok", "schema": "ok",
                "providers": "not_verified"}

    @app.get("/debug-db", tags=["Health"])
    def check_database(db: Session = Depends(get_db, scope="function")):
        count = db.query(models.WaterBody).count()
        return {"status": "Conectado ao PostGIS", "total_rios_cadastrados": count}

    return app


app = create_app()
