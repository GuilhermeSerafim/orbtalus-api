FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080
WORKDIR /app
COPY requirements.txt requirements.lock ./
# Candidate pins verified on Windows only. Linux/wheel availability is a build gate.
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.lock -r requirements.txt \
    && python -m pip check \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home app

COPY main.py database.py models.py migrate_rivers.py ./
COPY core/__init__.py core/config.py core/db_target.py core/errors.py core/geometry.py core/risk_calculator.py core/validation.py ./core/
COPY providers/__init__.py providers/base.py providers/mapbiomas_adapter.py ./providers/
COPY routers/__init__.py routers/ai_vertical.py routers/distance.py routers/risk.py ./routers/
COPY services/__init__.py services/ai_service.py services/elevation_service.py services/osm_service.py services/text_sanitizer.py ./services/
COPY scripts/init_original_db.py ./scripts/
COPY data/bart_flood_model.txt data/flood_risk_brazil.txt ./data/

USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
