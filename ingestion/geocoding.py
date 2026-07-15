"""
BioSetu - Location Search / Geocoding
----------------------------------------
Lets users search for a location by name (e.g. "Pauri Garhwal") instead
of manually typing latitude/longitude. Uses Open-Meteo's free geocoding
API - no API key required, same provider already used for weather data.

Docs: https://open-meteo.com/en/docs/geocoding-api
"""

import requests


def search_location(query: str, max_results: int = 5):
    """
    Searches for a place name and returns matching locations with
    coordinates. Returns an empty list on failure or no matches
    (never raises - callers should handle empty results gracefully).
    """
    if not query or not query.strip():
        return []

    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": query.strip(), "count": max_results, "language": "en", "format": "json"}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        return []

    results = data.get("results", [])
    return [
        {
            "name": r.get("name"),
            "admin1": r.get("admin1"),  # state/region
            "country": r.get("country"),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "label": f"{r.get('name')}"
                     + (f", {r.get('admin1')}" if r.get("admin1") else "")
                     + (f", {r.get('country')}" if r.get("country") else ""),
        }
        for r in results
    ]


if __name__ == "__main__":
    results = search_location("Pauri Garhwal")
    for r in results:
        print(r)
