"""
BioSetu - Layer 1b: Weather Ingestion (Open-Meteo)
----------------------------------------------------
Free, no-API-key weather forecast data - rainfall, temperature,
humidity. Used alongside GEE satellite data for the readiness score
and early-warning classifier.

Docs: https://open-meteo.com/en/docs
"""

import requests
import datetime


def get_weather_forecast(lat: float, lon: float, forecast_days: int = 3):
    """
    Returns hourly forecast for rainfall, temperature, and humidity
    for the next `forecast_days`.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,"
                  "soil_moisture_0_to_1cm",
        "forecast_days": forecast_days,
        "timezone": "auto",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def summarize_forecast_risk(forecast_json: dict):
    """
    Extracts simple derived signals from the raw forecast:
      - max expected rainfall in the window (mm)
      - max temperature (heat spike indicator)
      - avg relative humidity
    These feed directly into the early-warning classifier in Layer 3.
    """
    hourly = forecast_json.get("hourly", {})
    precipitation = hourly.get("precipitation", [])
    temperature = hourly.get("temperature_2m", [])
    humidity = hourly.get("relative_humidity_2m", [])

    if not precipitation or not temperature:
        return None

    return {
        "max_precipitation_mm": max(precipitation),
        "total_precipitation_mm": round(sum(precipitation), 2),
        "max_temperature_c": max(temperature),
        "avg_humidity_pct": round(sum(humidity) / len(humidity), 1) if humidity else None,
        "fetched_at": datetime.datetime.utcnow().isoformat(),
    }


def get_weather_snapshot(lat: float, lon: float):
    """Convenience wrapper combining fetch + summary."""
    raw = get_weather_forecast(lat, lon)
    return summarize_forecast_risk(raw)


if __name__ == "__main__":
    # Example: Pauri Garhwal, Uttarakhand coordinates
    snapshot = get_weather_snapshot(lat=30.15, lon=78.78)
    print(snapshot)
