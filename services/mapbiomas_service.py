def get_water_frequency(lat: float, lon: float) -> int:
    """
    Simulates fetching water frequency data from MapBiomas (0-30 years).
    For now, returns a simulated value based on a simple hash of coordinates
    to provide some deterministic variety, or just a random value.
    Let's use a simple deterministic simulation for consistency.
    """
    # Simple simulation: (lat + lon) decimal part scaled to 0-30
    val = abs((lat + lon) * 100) % 31
    return int(val)
