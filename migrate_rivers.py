import json
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import Base, WaterBody
from shapely.geometry import shape

# Cria a tabela no banco caso ela não exista
Base.metadata.create_all(bind=engine)

def migrate():
    db = SessionLocal()
    # Caminho do seu arquivo de Curitiba
    path = "data/exportCurtibaTypeAllRivers.geojson"
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for feature in data['features']:
        river_geom = shape(feature['geometry'])
        props = feature['properties']
        
        new_river = WaterBody(
            name=props.get('name', 'Sem nome'),
            type=props.get('waterway', 'river'),
            geom=f"SRID=4326;{river_geom.wkt}"
        )
        db.add(new_river)
    
    db.commit()
    print("✅ Sucesso! Os rios de Curitiba agora estão no seu banco Docker!")

if __name__ == "__main__":
    migrate()