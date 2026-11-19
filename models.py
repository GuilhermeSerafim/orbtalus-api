from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, Index
from sqlalchemy.orm import mapped_column
from geoalchemy2 import Geometry
from database import Base
from datetime import datetime


class OriginalWaterColumns:
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    type = Column(String, nullable=True)
    # Usamos GEOMETRY para aceitar qualquer formato de rio (linha ou área)
    geom = Column(Geometry("GEOMETRY", srid=4326))


class WaterBody(OriginalWaterColumns, Base):
    __tablename__ = "water_bodies"
    __table_args__ = (Index('uq_water_bodies_source_id', 'source', 'source_id', unique=True),)

    # Legacy imports carry no source identity. Do not invent dates or IDs for them.
    # Sort after the inherited columns to match an ALTER on an existing database.
    source = mapped_column(String, nullable=True, sort_order=1)
    source_id = mapped_column(String, nullable=True, sort_order=1)
    source_updated_at = mapped_column(DateTime(timezone=True), nullable=True, sort_order=1)
    fetched_at = mapped_column(DateTime(timezone=True), nullable=True, sort_order=1)


class HydrographyFetch(Base):
    __tablename__ = "hydrography_fetches"

    id = Column(Integer, primary_key=True)
    center = Column(Geometry("POINT", srid=4326), nullable=False)
    radius_m = Column(Integer, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)
    explanation = Column(Text, nullable=False)
    river_name = Column(String, nullable=True)
    distance_m = Column(Float, nullable=True)
    water_frequency_30y = Column(Integer, nullable=True)
    soil_type = Column(String, nullable=True)
    soil_class_id = Column(Integer, nullable=True)  # MapBiomas class ID for audit
    is_permeable = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
