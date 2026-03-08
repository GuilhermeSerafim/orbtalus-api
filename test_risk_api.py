import requests
import json

# Test data - São Paulo center
data = {
    "polygon": {
        "type": "Polygon",
        "coordinates": [
            [
                [-46.633308, -23.550520],
                [-46.633208, -23.550520],
                [-46.633208, -23.550420],
                [-46.633308, -23.550420],
                [-46.633308, -23.550520],
            ]
        ],
    }
}

print("🚀 Testing /geo/risk with MapBiomas integration...\n")
response = requests.post("http://localhost:8000/geo/risk", json=data, timeout=60)

print(f"✅ Status Code: {response.status_code}\n")

if response.status_code == 200:
    result = response.json()

    print("=" * 60)
    print("📊 MAPBIOMAS DATA")
    print("=" * 60)
    env_data = result.get("environmental_data", {})
    print(f"Data Source: {env_data.get('data_source')}")

    soil = env_data.get("soil", {})
    print(f"\n🌱 Soil:")
    print(f"  - Class ID: {soil.get('class_id')}")
    print(f"  - Class Name: {soil.get('class_name')}")
    print(f"  - Permeable: {soil.get('is_permeable')}")

    water = env_data.get("water_frequency", {})
    print(f"\n💧 Water:")
    print(f"  - Frequency: {water.get('years')} years (out of 30)")
    print(f"  - Confidence: {water.get('confidence')}")

    print("\n" + "=" * 60)
    print("🎯 RISK ASSESSMENT")
    print("=" * 60)
    calc = result.get("risk_calculation", {})
    print(f"Risk Level: {result.get('risk_level')}")
    print(f"Total Score: {calc.get('total_score')}")
    print(f"Confidence: {calc.get('confidence')}")

    scores = calc.get("component_scores", {})
    print(f"\n📈 Component Scores:")
    print(f"  - Topography: {scores.get('topography')}")
    print(f"  - Water Frequency: {scores.get('water_frequency')}")
    print(f"  - Soil Permeability: {scores.get('soil_permeability')}")

    print("\n" + "=" * 60)
    print("✅ SUCCESS! MapBiomas is working!")
    print("=" * 60)
else:
    print(f"❌ Error: {response.text}")
