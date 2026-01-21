from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from routers.distance import router as distance_router
from routers.risk import router as risk_router
from routers.ai_vertical import router as ai_router
from sqlalchemy.orm import Session
from database import SessionLocal, Base, engine
import models

# Criação automática das tabelas no PostGIS ao iniciar
# Isso garante que rios e documentos técnicos estejam prontos no deploy
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GeoRisk API",
    description="Plataforma global e agnóstica para análise de risco hidrológico",
    version="2.0.0",
)

# Configuração de CORS para integração com seu frontend (Next.js/React)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Roteamento Modular
app.include_router(distance_router, prefix="/geo", tags=["Geoprocessamento"])
app.include_router(risk_router, prefix="/geo", tags=["Análise de Risco"])
app.include_router(ai_router, prefix="/ai", tags=["Inteligência Artificial"])


@app.get("/ping", tags=["Health"])
def ping():
    """Rota de verificação para o Cloud Run e monitoramento de saúde."""
    return {
        "status": "ok",
        "service": "GeoRisk API",
        "infra": "Agnostic/Multi-cloud",
        "database": "Connected (PostGIS)",
    }

    # Função para pegar a conexão com o banco


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"message": "GeoRisk API está online!"}


@app.get("/debug-db", tags=["Health"])
def check_database(db: Session = Depends(get_db)):
    # Contamos quantos rios existem na tabela
    count = db.query(models.WaterBody).count()
    return {"status": "Conectado ao PostGIS", "total_rios_cadastrados": count}
