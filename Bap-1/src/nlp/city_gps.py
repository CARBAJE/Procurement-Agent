"""Indian city name → GPS coordinates lookup."""

CITY_GPS: dict[str, str] = {
    "bangalore": "12.9716,77.5946",
    "bengaluru": "12.9716,77.5946",
    "mumbai": "19.0760,72.8777",
    "delhi": "28.6139,77.2090",
    "new delhi": "28.6139,77.2090",
    "chennai": "13.0827,80.2707",
    "hyderabad": "17.3850,78.4867",
    "pune": "18.5204,73.8567",
    "kolkata": "22.5726,88.3639",
    "ahmedabad": "23.0225,72.5714",
    "jaipur": "26.9124,75.7873",
    "surat": "21.1702,72.8311",
    "lucknow": "26.8467,80.9462",
    "kochi": "9.9312,76.2673",
    "bhopal": "23.2599,77.4126",
}


def resolve_gps(city: str | None) -> str | None:
    """Return GPS string for a city name, or None if not found."""
    if not city:
        return None
    return CITY_GPS.get(city.strip().lower())
