from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, Base, engine
import models

# Importação dos seus routers modulares
from routers.distance import router as distance_router
from routers.risk import router as risk_router
from routers.ai_vertical import router as ai_router

# 1. Garante a infraestrutura: Criação automática das tabelas no PostGIS
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GeoRisk API",
    description="Plataforma global e agnóstica para análise de risco hidrológico com foco em resiliência",
    version="2.0.0",
)

# 2. Middleware de CORS: Essencial para seu frontend em React/Angular
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Roteamento Modular (Organização Clean Architecture)
app.include_router(distance_router, prefix="/geo", tags=["Geoprocessamento"])
app.include_router(risk_router, prefix="/geo", tags=["Análise de Risco"])
app.include_router(ai_router, prefix="/ai", tags=["Inteligência Artificial"])


# 4. Dependency Injection para o Banco de Dados
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 5. Endpoints de Saúde e Debug
@app.get("/ping", tags=["Health"])
def ping():
    """Verificação para Cloud Run e monitoramento de infraestrutura."""
    return {
        "status": "ok",
        "service": "GeoRisk API",
        "infra": "Agnostic/Multi-cloud",
        "database": "Connected (PostGIS)",
    }


@app.get("/", tags=["Health"])
def read_root():
    return {"message": "GeoRisk API está online e resiliente!"}


@app.get("/debug-db", tags=["Health"])
def check_database(db: Session = Depends(get_db)):
    """Valida se os dados de Curitiba (ou globais) estão acessíveis."""
    count = db.query(models.WaterBody).count()
    return {"status": "Conectado ao PostGIS", "total_rios_cadastrados": count}
