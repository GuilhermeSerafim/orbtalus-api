# GeoRisk Backend

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PostGIS-336791?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?logo=openai&logoColor=white)
![Google Earth Engine](https://img.shields.io/badge/Google%20Earth%20Engine-MapBiomas-4285F4)

GeoRisk Backend is the API layer behind GeoRisk. The service receives a GeoJSON polygon, queries hydrological context in PostGIS, enriches the analysis with elevation and environmental data, runs a weighted flood-risk calculation, and stores the assessment history.

The current backend is no longer just a simple FastAPI + LLM service. It also includes:

- PostGIS persistence for water bodies and analysis history
- Runtime enrichment from OpenStreetMap via Overpass
- Environmental providers through Google Earth Engine and MapBiomas
- Fallback provider support when GEE is unavailable
- Dockerized database infrastructure and Alembic migrations

## Project overview

Main backend flow for `POST /geo/risk`:

1. Receives a GeoJSON polygon and extracts a representative point.
2. Fetches nearby waterways from OpenStreetMap when the area is not yet cached in PostGIS.
3. Finds the nearest water body with PostGIS spatial functions.
4. Looks up elevation with Open-Meteo.
5. Retrieves soil and historical water-frequency signals from MapBiomas through Google Earth Engine.
6. Applies the business scoring logic in `core/risk_calculator.py`.
7. Uses OpenAI through LangChain to generate a technical explanation.
8. Persists the result in `risk_assessments`.

## Main features

- `POST /geo/distance` to query the nearest water body already stored in PostGIS
- `POST /geo/risk` to calculate flood risk with spatial, environmental, and AI-enriched context
- `POST /ai/ask-ai` to ask technical questions grounded in local documents
- `GET /ping`, `GET /`, and `GET /debug-db` for health and infrastructure checks
- Persistent history of risk analyses in PostgreSQL/PostGIS
- Provider abstraction for MapBiomas and future integrations such as Nottus

## Tech stack

| Category | Technologies |
| --- | --- |
| Language | Python 3.9+ |
| API | FastAPI, Uvicorn, Pydantic |
| ORM and database | SQLAlchemy, GeoAlchemy2, PostgreSQL, PostGIS, psycopg2-binary |
| Migrations | Alembic |
| Geospatial processing | Shapely, PostGIS spatial functions |
| OSM integration | OpenStreetMap, Overpass API, Overpy |
| Environmental data | Open-Meteo Elevation API, Google Earth Engine, MapBiomas |
| AI and RAG | OpenAI API (`gpt-4o`, `text-embedding-3-small`), LangChain, langchain-openai, langchain-core, langchain-community, langchain-text-splitters, NumPy |
| Configuration and auth | python-dotenv, google-auth |
| Infrastructure | Docker, Docker Compose, Cloud Run-ready container entrypoint |

## Architecture overview

```text
Client
  └─ FastAPI app (main.py)
      ├─ /geo/distance -> routers/distance.py
      │   └─ PostGIS query on water_bodies
      ├─ /geo/risk -> routers/risk.py
      │   ├─ OSMService -> OpenStreetMap / Overpass
      │   ├─ PostGIS -> nearest water body lookup
      │   ├─ elevation_service -> Open-Meteo
      │   ├─ MapBiomasAdapter / NottusAdapter -> environmental signals
      │   ├─ RiskCalculator -> weighted business rules
      │   ├─ ai_service -> LangChain + OpenAI
      │   └─ PostgreSQL/PostGIS -> risk_assessments persistence
      └─ /ai/ask-ai -> routers/ai_vertical.py
          └─ ai_service -> local-document grounded answer
```

## Data sources and external services

| Source | Usage |
| --- | --- |
| OpenStreetMap / Overpass Turbo | Local GeoJSON exports in `data/` used to preload rivers |
| OpenStreetMap / Overpass API | Runtime fetch of nearby waterways in `/geo/risk` |
| Open-Meteo | Elevation lookup for the analyzed point and nearest river point |
| MapBiomas Collection 8 | Land cover / soil-permeability proxy |
| MapBiomas Water Collection | Historical water-frequency signal |
| Google Earth Engine | Execution layer for MapBiomas queries |
| Local documents in `data/` | RAG context for AI responses |

## Project structure

```text
geo-risk-back/
├── alembic/
├── core/
│   ├── __init__.py
│   ├── config.py
│   └── risk_calculator.py
├── data/
│   ├── bart_flood_model.txt
│   ├── export.geojson
│   ├── exportCuritiba.geojson
│   ├── exportCurtibaTypeAllRivers.geojson
│   └── flood_risk_brazil.txt
├── docs/
├── providers/
│   ├── base.py
│   ├── mapbiomas_adapter.py
│   └── nottus_adapter.py
├── routers/
│   ├── ai_vertical.py
│   ├── distance.py
│   └── risk.py
├── services/
│   ├── ai_service.py
│   ├── elevation_service.py
│   ├── mapbiomas_service.py
│   ├── osm_service.py
│   ├── soil_service.py
│   └── water_service.py
├── database.py
├── Dockerfile
├── docker-compose.yml
├── main.py
├── migrate_rivers.py
├── models.py
├── requirements.txt
├── setup_gee.py
└── test_risk_api.py
```

## Installation

### Prerequisites

- Python 3.9 or newer
- Docker and Docker Compose
- An OpenAI API key
- A PostgreSQL/PostGIS connection string
- Google Earth Engine credentials if you want real MapBiomas data instead of fallback mode

### Local setup

Run the commands below from `geo-risk-back/`:

```bash
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
docker compose up -d db
```

### Environment variables

Create a `.env` file in the backend root:

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | SQLAlchemy connection string for PostgreSQL/PostGIS |
| `OPENAI_API_KEY` | Yes | OpenAI key used by the AI endpoints |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | Path to a Google service-account JSON file for Earth Engine |
| `GEE_SERVICE_ACCOUNT_JSON` | No | Inline service-account JSON for Earth Engine, useful in cloud deployments |
| `PORT` | No | Container port used by the Docker image / Cloud Run entrypoint |

Example:

```bash
DATABASE_URL=postgresql://admin:georisk_pass@localhost:5432/georisk_db
OPENAI_API_KEY=sk-proj-your_key_here
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\georisk-auth.json
```

Notes:

- Configure either `GOOGLE_APPLICATION_CREDENTIALS` or `GEE_SERVICE_ACCOUNT_JSON` for MapBiomas.
- If Earth Engine initialization fails, the API falls back to `NottusAdapter`, which currently returns placeholder data.

### Optional: preload Curitiba waterways

If you want `/geo/distance` to work immediately with the bundled dataset, load the GeoJSON into PostGIS:

```bash
python migrate_rivers.py
```

`/geo/risk` can also fetch nearby waterways on demand from OpenStreetMap and cache them in the database.

## Running locally

Start the API with:

```bash
python -m uvicorn main:app --reload
```

Available URLs:

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/ping`

## API overview

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | `GET` | Basic online status |
| `/ping` | `GET` | Health check for infrastructure |
| `/debug-db` | `GET` | Confirms database connectivity and water-body count |
| `/geo/distance` | `POST` | Returns the nearest stored water body and the queried point |
| `/geo/risk` | `POST` | Runs the full risk pipeline and persists the result |
| `/ai/ask-ai` | `POST` | Sends a grounded technical question to the AI layer |

## Input expectations

- `POST /geo/distance` and `POST /geo/risk` expect a GeoJSON polygon in the `polygon` field
- Coordinates must follow GeoJSON order: `[longitude, latitude]`
- The route accepts either a raw Polygon geometry or a `Feature.geometry`-like object

Example request:

```json
{
  "polygon": {
    "type": "Polygon",
    "coordinates": [
      [
        [-49.283, -25.461],
        [-49.282, -25.461],
        [-49.282, -25.460],
        [-49.283, -25.460],
        [-49.283, -25.461]
      ]
    ]
  }
}
```

Example `POST /geo/risk` response:

```json
{
  "distancia_rio_m": 1750.7,
  "queda_relativa_m": 9.0,
  "rio_mais_proximo": "Rio Agua Verde",
  "tipo_hidrografia": "river",
  "resposta_ia": "A area apresenta risco medio, com influencia combinada da topografia, proximidade hidrica e caracteristicas ambientais.",
  "risk_level": "Medio",
  "risk_calculation": {
    "confidence": 1.0,
    "total_score": 0.48,
    "component_scores": {
      "topography": 0.34,
      "water_frequency": 0.4,
      "soil_permeability": 1.0
    },
    "weights_applied": {
      "topography": 0.5,
      "water_frequency": 0.3,
      "soil_permeability": 0.2
    }
  },
  "environmental_data": {
    "soil": {
      "class_id": 24,
      "class_name": "Area Urbanizada",
      "is_permeable": false
    },
    "water_frequency": {
      "years": 4,
      "confidence": 1.0
    },
    "data_source": "MapBiomas (GEE)",
    "provider_status": "OK"
  },
  "debug_coords": {
    "rio_lat": -25.46,
    "rio_lon": -49.28
  }
}
```

Example `POST /ai/ask-ai` request:

```json
{
  "pergunta": "Quais fatores tecnicos o backend usa para classificar risco de alagamento?"
}
```

## Backend notes

- `main.py` creates tables automatically with `Base.metadata.create_all(bind=engine)`.
- Alembic is available in the repository for schema evolution.
- The Docker image uses `python:3.9-slim` and starts Uvicorn with `main:app`.
- `test_risk_api.py` is a manual smoke-test script for the `/geo/risk` endpoint.

## Contributing

Contributions are welcome. For larger changes, align scope and architectural impact before opening a pull request.
