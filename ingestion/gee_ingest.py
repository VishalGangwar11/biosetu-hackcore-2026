"""
BioSetu - Layer 1: Google Earth Engine Ingestion
--------------------------------------------------
Pulls real satellite-derived indicators for a given field location:
  - Soil moisture (SMAP)
  - NDVI (Sentinel-2)
  - Land surface temperature (MODIS)

Requires: `pip install earthengine-api`
Auth: run `earthengine authenticate` once locally before first use,
      or use a service account if deploying non-interactively.

NOTE: This module makes real network calls to Earth Engine servers.
It cannot be executed inside a sandboxed environment without internet
access to earthengine.googleapis.com — run it on your local machine
or in a Colab notebook where GEE auth is already set up.
"""

import ee
import datetime


def init_earth_engine(project_id: str):
    """
    Initialize the Earth Engine session.
    project_id: your GEE-linked Google Cloud project ID (required for
    the current API — find it in the GEE Code Editor under your account).
    """
    try:
        ee.Initialize(project=project_id)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project_id)


def get_field_geometry(lat: float, lon: float, buffer_m: int = 1000):
    """Create a point buffer representing the farmer's field."""
    point = ee.Geometry.Point([lon, lat])
    return point.buffer(buffer_m)


def get_soil_moisture(geometry, days_back_options=(10, 20, 40)):
    """
    SMAP surface soil moisture (0-5cm), volumetric fraction.
    Dataset: NASA/SMAP/SPL4SMGP/008 (007 was deprecated by NASA)

    Tries progressively wider date windows if the shortest one has
    no available passes (common in monsoon season / data latency).
    """
    end = datetime.datetime.utcnow()

    for days_back in days_back_options:
        start = end - datetime.timedelta(days=days_back)

        collection = (
            ee.ImageCollection("NASA/SMAP/SPL4SMGP/008")
            .filterDate(str(start.date()), str(end.date()))
            .select("sm_surface")
        )

        size = collection.size().getInfo()
        print(f"[soil_moisture] window={days_back}d -> {size} images found")

        if size == 0:
            continue

        mean_image = collection.mean()
        result_dict = mean_image.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=10000
        ).getInfo()

        value = result_dict.get("sm_surface") if result_dict else None
        if value is not None:
            return value

    return None


def get_ndvi(geometry, days_back_options=(14, 30, 60), cloud_thresholds=(20, 40, 80)):
    """
    Sentinel-2 NDVI, cloud-filtered.
    Dataset: COPERNICUS/S2_SR_HARMONIZED

    Tries progressively wider date windows AND looser cloud filters,
    since monsoon-season imagery over hilly terrain is often almost
    entirely cloud-covered under a strict 20% threshold.
    """
    end = datetime.datetime.utcnow()

    def add_ndvi(img):
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        return img.addBands(ndvi)

    for days_back, cloud_thresh in zip(days_back_options, cloud_thresholds):
        start = end - datetime.timedelta(days=days_back)

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(str(start.date()), str(end.date()))
            .filterBounds(geometry)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_thresh))
            .map(add_ndvi)
        )

        size = collection.size().getInfo()
        print(f"[ndvi] window={days_back}d, cloud<{cloud_thresh}% -> {size} images found")

        if size == 0:
            continue

        mean_ndvi = collection.select("NDVI").mean()
        result_dict = mean_ndvi.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=10
        ).getInfo()

        value = result_dict.get("NDVI") if result_dict else None
        if value is not None:
            return value

    return None


def get_land_surface_temp(geometry, days_back_options=(7, 20, 40)):
    """
    MODIS Land Surface Temperature (day), converted to Celsius.
    Dataset: MODIS/061/MOD11A1

    Tries progressively wider windows — MODIS LST also gets masked
    out under heavy cloud, common in monsoon conditions.
    """
    end = datetime.datetime.utcnow()

    for days_back in days_back_options:
        start = end - datetime.timedelta(days=days_back)

        collection = (
            ee.ImageCollection("MODIS/061/MOD11A1")
            .filterDate(str(start.date()), str(end.date()))
            .select("LST_Day_1km")
        )

        size = collection.size().getInfo()
        print(f"[land_surface_temp] window={days_back}d -> {size} images found")

        if size == 0:
            continue

        mean_image = collection.mean()
        result_dict = mean_image.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=1000
        ).getInfo()

        kelvin_scaled = result_dict.get("LST_Day_1km") if result_dict else None
        if kelvin_scaled is not None:
            return round((kelvin_scaled * 0.02) - 273.15, 2)

    return None


def get_field_snapshot(lat: float, lon: float, project_id: str):
    """
    Convenience wrapper: returns all three indicators for one field
    as a single dict, ready to feed into the scoring engine.
    """
    init_earth_engine(project_id)
    geometry = get_field_geometry(lat, lon)

    return {
        "lat": lat,
        "lon": lon,
        "soil_moisture": get_soil_moisture(geometry),
        "ndvi": get_ndvi(geometry),
        "land_surface_temp_c": get_land_surface_temp(geometry),
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    # Example: Pauri Garhwal, Uttarakhand coordinates
    PROJECT_ID = "htip-bah2026"  # your GEE project ID
    snapshot = get_field_snapshot(lat=30.15, lon=78.78, project_id="htip-bah2026")
    print(snapshot)
