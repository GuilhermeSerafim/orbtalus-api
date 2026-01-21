from sqlalchemy import Column, Integer, String
from geoalchemy2 import Geometry
from database import Base

class WaterBody(Base):
    __tablename__ = "water_bodies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    type = Column(String, nullable=True)
    # Usamos GEOMETRY para aceitar qualquer formato de rio (linha ou área)
    geom = Column(Geometry("GEOMETRY", srid=4326))