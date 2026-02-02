def get_soil_data(lat: float, lon: float) -> dict:
    """
    Simulates fetching soil data.
    Returns a dictionary: {"class": str, "is_permeable": bool}
    """
    # Simulated logic based on coordinates parity to give different results
    if int((lat * 1000) + (lon * 1000)) % 2 == 0:
        return {"class": "Argissolo Vermelho", "is_permeable": True}
    else:
        return {"class": "Área Urbanizada / Solo Compactado", "is_permeable": False}
