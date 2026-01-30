from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from geoalchemy2 import Geometry
from database import Base
from datetime import datetime


class WaterBody(Base):
    __tablename__ = "water_bodies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    type = Column(String, nullable=True)
    # Usamos GEOMETRY para aceitar qualquer formato de rio (linha ou área)
    geom = Column(Geometry("GEOMETRY", srid=4326))


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)
    explanation = Column(Text, nullable=False)
    river_name = Column(String, nullable=True)
    distance_m = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
