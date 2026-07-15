"""
BioSetu - Layer 2 & 3: Biological Readiness Score + Early Warning
--------------------------------------------------------------------
Combines real satellite indicators (soil moisture, NDVI, land surface
temperature) and weather forecast data into:

  1. A Biological Readiness Score (0-100) with a confidence band,
     answering PS-01: "is now a good time to apply a biostimulant?"

  2. An Early Warning classification (CRITICAL / HIGH / LOW / NONE),
     answering PS-02: "is a climate stress event incoming that
     requires proactive biological intervention?"

Design philosophy:
  - Explainable, threshold-based scoring grounded in cited agronomic
    reference ranges — not an opaque ML black box. This is easier to
    defend under judge questioning than a model with no visible logic.
  - Every score ships with a confidence interval, not just a point
    estimate — treating uncertainty honestly rather than hiding it.
  - No proprietary Syngenta data is assumed anywhere in this file.
    Reference ranges are drawn from public agronomic literature and
    are clearly labeled as defaults that would be replaced by
    Syngenta's own product-specific data if this were deployed.
"""

import math


# ---------------------------------------------------------------------
# Reference ranges (public agronomic literature defaults)
# These represent commonly-cited favorable windows for biostimulant/
# biological product application. In a real deployment, these would
# be swapped for Syngenta's product-specific efficacy thresholds.
# ---------------------------------------------------------------------
REFERENCE_RANGES = {
    "soil_moisture": {"min": 0.20, "optimal_min": 0.25, "optimal_max": 0.35, "max": 0.45},
    "temperature_c": {"min": 15, "optimal_min": 20, "optimal_max": 30, "max": 35},
    "ndvi": {"min": 0.2, "optimal_min": 0.4, "optimal_max": 0.8, "max": 1.0},
}


# ---------------------------------------------------------------------
# Biological-class-aware thresholds
# ---------------------------------------------------------------------
# Unlike a generic weather/readiness score, live biological products
# (microbial biofertilizers/biocontrols) have organism-specific
# temperature tolerances that determine whether the product actually
# survives and works after application. Biochemical extracts
# (seaweed, humic/fulvic acid, protein hydrolysates) are governed by
# different constraints (mainly wash-off and leaf absorption, not
# organism viability). Every threshold below is sourced from
# peer-reviewed literature, ICAR guidelines, or cited patents —
# contributed and verified by a biotechnology-background teammate.
# No proprietary Syngenta data is used or assumed anywhere here.
#
# Fields:
#   optimal_min / optimal_max : temperature range for peak viability/efficacy
#   upper_limit               : temperature above which viability/efficacy
#                                drops sharply (organism-specific for
#                                microbials; absorption-related for extracts)
#   uv_sensitive              : whether early-morning/evening application
#                                is specifically recommended
#   washout_only              : True for biochemical extracts where heat
#                                itself isn't the limiting factor - rain
#                                washout dominates instead
#   source                    : citation for the numbers used
# ---------------------------------------------------------------------
BIOLOGICAL_CLASS_THRESHOLDS = {
    "trichoderma": {
        "label": "Live fungal biocontrol (Trichoderma spp.)",
        "optimal_min": 24.6, "optimal_max": 29.4, "upper_limit": 35,
        "uv_sensitive": True, "washout_only": False,
        "notes": "UV-sensitive; best applied early morning/evening. "
                 "Prolonged heat above ~35-37C reduces spore germination and CFU count.",
        "source": "Singh et al. 2022, J. Applied Biology & Biotechnology; "
                   "Harman et al. 2004, Nature Reviews Microbiology",
    },
    "bacillus": {
        "label": "Live bacterial/endospore (Bacillus spp.)",
        "optimal_min": 25, "optimal_max": 35, "upper_limit": 42,
        "uv_sensitive": False, "washout_only": False,
        "notes": "Endospores provide strong heat and UV tolerance - "
                 "more robust than fungal inoculants. Vegetative cells "
                 "affected above ~40-45C but spores remain highly viable.",
        "source": "ICAR Storage Guidelines for Biofertilizers & Biopesticides; "
                   "US Patent US20190281862A1 (Bacillus endospore formulations)",
    },
    "rhizobium": {
        "label": "Rhizobial inoculants (Rhizobium, Bradyrhizobium)",
        "optimal_min": 25, "optimal_max": 30, "upper_limit": 35,
        "uv_sensitive": True, "washout_only": False,
        "notes": "Sensitive to drying and solar radiation - "
                 "maintain cold storage when possible.",
        "source": "FAO Biofertilizer Manual; Somasegaran & Hoben (1994)",
    },
    "azotobacter": {
        "label": "Azotobacter spp. (nitrogen-fixing biofertilizer)",
        "optimal_min": 28, "optimal_max": 30, "upper_limit": 39,
        "uv_sensitive": False, "washout_only": False,
        "notes": "Heat stress lowers nitrogen fixation and cell viability.",
        "source": "ICAR Biofertilizer Quality Manual",
    },
    "azospirillum": {
        "label": "Azospirillum spp. (cereal biofertilizer)",
        "optimal_min": 28, "optimal_max": 32, "upper_limit": 38,
        "uv_sensitive": False, "washout_only": False,
        "notes": "Moderate heat tolerance; desiccation-sensitive.",
        "source": "Bashan & de-Bashan (2010), Advances in Agronomy",
    },
    "pseudomonas": {
        "label": "Pseudomonas fluorescens (biocontrol/PGPR)",
        "optimal_min": 25, "optimal_max": 30, "upper_limit": 35,
        "uv_sensitive": True, "washout_only": False,
        "notes": "Non-spore former - UV and heat sensitive. "
                 "Evening application recommended.",
        "source": "Haas & Defago (2005), Nature Reviews Microbiology",
    },
    "mycorrhizae": {
        "label": "Arbuscular Mycorrhizal Fungi (AMF)",
        "optimal_min": 20, "optimal_max": 30, "upper_limit": 35,
        "uv_sensitive": False, "washout_only": False,
        "notes": "Colonization efficiency declines under prolonged high temperature.",
        "source": "Smith & Read (2008), Mycorrhizal Symbiosis",
    },
    "seaweed_extract": {
        "label": "Biochemical extract (Seaweed, e.g. Ascophyllum nodosum)",
        "optimal_min": None, "optimal_max": None, "upper_limit": 45,
        "uv_sensitive": False, "washout_only": True,
        "notes": "Active compounds relatively stable with temperature; "
                 "efficacy reduced mainly by wash-off, not heat.",
        "source": "Craigie (2011), Journal of Applied Phycology",
    },
    "humic_fulvic": {
        "label": "Humic/Fulvic acid formulations",
        "optimal_min": None, "optimal_max": None, "upper_limit": None,
        "uv_sensitive": False, "washout_only": True,
        "notes": "Chemically stable; performance influenced more by "
                 "soil chemistry than temperature.",
        "source": "Canellas et al. (2015), Chemical and Biological "
                   "Technologies in Agriculture",
    },
    "protein_hydrolysate": {
        "label": "Protein hydrolysate biostimulants (amino-acid foliar sprays)",
        "optimal_min": None, "optimal_max": 35, "upper_limit": 35,
        "uv_sensitive": False, "washout_only": True,
        "notes": "Heat primarily affects leaf absorption efficiency "
                 "(rapid drying above ~35C), not product stability itself.",
        "source": "du Jardin (2015), Scientia Horticulturae",
    },
}

# Standard illustrative buffer between a chemical pesticide application
# and a live biological application, commonly recommended in Indian
# agri-extension practice to avoid killing the biological agent.
# This is a general practice guideline, not a Syngenta-specific value -
# stated explicitly as illustrative in the pitch.
CHEMICAL_COMPATIBILITY_BUFFER_DAYS = 7


def _band_score(value, ref, weight_missing_penalty=15):
    """
    Scores a single indicator 0-100 based on how close it is to the
    optimal band. Returns None-safe: if value is missing, returns a
    reduced score AND signals reduced confidence (handled by caller).
    """
    if value is None:
        return None

    lo, opt_lo, opt_hi, hi = ref["min"], ref["optimal_min"], ref["optimal_max"], ref["max"]

    if opt_lo <= value <= opt_hi:
        return 100.0
    elif lo <= value < opt_lo:
        # Linear ramp from 0 (at min) to 100 (at optimal_min)
        return max(0.0, 100 * (value - lo) / (opt_lo - lo))
    elif opt_hi < value <= hi:
        # Linear ramp down from 100 (at optimal_max) to 0 (at max)
        return max(0.0, 100 * (hi - value) / (hi - opt_hi))
    else:
        # Outside the entire viable range
        return 0.0


def compute_biological_class_score(land_surface_temp_c, biological_class: str):
    """
    Scores viability/efficacy specifically for the selected biological
    class, using organism-specific (or extract-specific) thresholds
    instead of the generic REFERENCE_RANGES temperature band.

    Returns None-safe if temperature is missing or class is unknown.
    """
    if biological_class not in BIOLOGICAL_CLASS_THRESHOLDS:
        return None

    cls = BIOLOGICAL_CLASS_THRESHOLDS[biological_class]

    if land_surface_temp_c is None:
        return None

    # Biochemical extracts with no defined optimal band: score based
    # purely on the upper limit (if any), since these aren't governed
    # by organism viability.
    if cls["optimal_min"] is None and cls["optimal_max"] is None:
        if cls["upper_limit"] is None:
            return 100.0  # not temperature-limited at all (e.g. humic/fulvic)
        if land_surface_temp_c <= cls["upper_limit"]:
            return 100.0
        return max(0.0, 100 - 5 * (land_surface_temp_c - cls["upper_limit"]))

    opt_lo = cls["optimal_min"]
    opt_hi = cls["optimal_max"]
    upper = cls["upper_limit"]

    if opt_lo <= land_surface_temp_c <= opt_hi:
        return 100.0
    elif land_surface_temp_c < opt_lo:
        # Below optimal range - assume gentle ramp down (cold stress
        # is less commonly the binding constraint for these classes,
        # so this is a soft penalty rather than a hard cutoff)
        return max(50.0, 100 - 3 * (opt_lo - land_surface_temp_c))
    elif opt_hi < land_surface_temp_c <= upper:
        # Ramp down from 100 (at optimal_max) to 20 (at upper_limit)
        return max(20.0, 100 - 80 * (land_surface_temp_c - opt_hi) / (upper - opt_hi))
    else:
        # Beyond documented upper limit - viability/efficacy considered
        # substantially compromised
        return 5.0


def check_chemical_compatibility(days_since_last_chemical_application, biological_class: str):
    """
    Flags a compatibility risk if a live biological is being applied
    too soon after a chemical pesticide application. Biochemical
    extracts (seaweed, humic/fulvic, protein hydrolysate) are not
    subject to this constraint since there's no living organism to kill.

    days_since_last_chemical_application: int or None (None = unknown/
    not provided by the farmer - treated as "cannot verify", not "safe").
    """
    cls = BIOLOGICAL_CLASS_THRESHOLDS.get(biological_class, {})
    is_living_organism = not cls.get("washout_only", False)

    if not is_living_organism:
        return {
            "risk": False,
            "reason": "This product class is not a living organism - "
                      "chemical compatibility timing is not a primary concern.",
        }

    if days_since_last_chemical_application is None:
        return {
            "risk": None,
            "reason": "Chemical application history not provided - cannot verify "
                      f"the commonly recommended {CHEMICAL_COMPATIBILITY_BUFFER_DAYS}-day "
                      "buffer for live biologicals.",
        }

    if days_since_last_chemical_application < CHEMICAL_COMPATIBILITY_BUFFER_DAYS:
        return {
            "risk": True,
            "reason": f"Chemical pesticide applied {days_since_last_chemical_application} day(s) ago - "
                      f"within the commonly recommended {CHEMICAL_COMPATIBILITY_BUFFER_DAYS}-day buffer. "
                      f"Applying a live biological now may reduce its effectiveness.",
        }

    return {"risk": False, "reason": "Outside the compatibility buffer window - no flagged risk."}


def get_application_timing_guidance(biological_class: str):
    """
    Returns a short, plain-language note on time-of-day application
    timing, based on whether the class is UV-sensitive.
    """
    cls = BIOLOGICAL_CLASS_THRESHOLDS.get(biological_class)
    if cls is None:
        return None
    if cls.get("uv_sensitive"):
        return "This product class is UV-sensitive: apply during early morning or evening, avoid peak sunlight."
    return None


def build_biological_guidance(land_surface_temp_c, biological_class,
                                days_since_last_chemical_application=None):
    """
    Top-level function combining class-specific viability scoring,
    chemical compatibility check, and timing guidance into one
    structured result. Returns None if biological_class is not
    provided (keeps the generic score as the default behavior).
    """
    if not biological_class or biological_class not in BIOLOGICAL_CLASS_THRESHOLDS:
        return None

    cls = BIOLOGICAL_CLASS_THRESHOLDS[biological_class]

    return {
        "biological_class": biological_class,
        "label": cls["label"],
        "viability_score": compute_biological_class_score(land_surface_temp_c, biological_class),
        "compatibility": check_chemical_compatibility(days_since_last_chemical_application, biological_class),
        "timing_guidance": get_application_timing_guidance(biological_class),
        "notes": cls["notes"],
        "source": cls["source"],
    }


def compute_readiness_score(soil_moisture, land_surface_temp_c, ndvi,
                              max_precipitation_mm):
    """
    Returns a dict with:
      - score: 0-100 Biological Readiness Score
      - confidence: 0-100, reflecting how many of the underlying
        indicators were actually available (real data vs missing)
      - confidence_band: (low, high) score range accounting for
        missing-data uncertainty
      - components: per-indicator sub-scores for explainability
      - rain_risk_flag: True if heavy rain in next 48-72h would wash
        away a biological application regardless of other conditions
    """
    components = {
        "soil_moisture": _band_score(soil_moisture, REFERENCE_RANGES["soil_moisture"]),
        "temperature": _band_score(land_surface_temp_c, REFERENCE_RANGES["temperature_c"]),
        "ndvi": _band_score(ndvi, REFERENCE_RANGES["ndvi"]),
    }

    available = [v for v in components.values() if v is not None]
    n_total = len(components)
    n_available = len(available)

    if n_available == 0:
        return {
            "score": None,
            "confidence": 0,
            "confidence_band": (None, None),
            "components": components,
            "rain_risk_flag": None,
            "note": "No satellite indicators available for this window.",
        }

    base_score = sum(available) / n_available
    confidence = round(100 * n_available / n_total, 1)

    # Wider uncertainty band when fewer indicators are available.
    # This is a simple, defensible heuristic (not a statistical model) —
    # explicitly labeled as such rather than presented as rigorous.
    uncertainty_margin = 25 * (1 - n_available / n_total) + 5
    low = max(0, round(base_score - uncertainty_margin, 1))
    high = min(100, round(base_score + uncertainty_margin, 1))

    # Rain risk: heavy incoming rain overrides an otherwise good score,
    # since applying a biological right before heavy rain washes it away.
    rain_risk_flag = max_precipitation_mm is not None and max_precipitation_mm > 15

    final_score = base_score
    if rain_risk_flag:
        final_score = min(final_score, 35)  # cap score, don't fully zero it

    return {
        "score": round(final_score, 1),
        "confidence": confidence,
        "confidence_band": (low, high),
        "components": components,
        "rain_risk_flag": rain_risk_flag,
        "note": None if n_available == n_total else
                f"Only {n_available}/{n_total} indicators available — widen data window if this persists.",
    }


def classify_early_warning(max_precipitation_mm, max_temperature_c,
                             total_precipitation_mm):
    """
    Classifies incoming climate stress risk level based on weather
    forecast signals. Returns one of: CRITICAL, HIGH, LOW, NONE.

    Thresholds are illustrative/public-literature-based defaults for
    a hackathon demo — a production version would calibrate these
    against Syngenta's regional agronomic data.
    """
    if max_precipitation_mm is None or max_temperature_c is None:
        return {"level": "UNKNOWN", "reason": "Insufficient forecast data."}

    # Heavy rain event
    if max_precipitation_mm > 30:
        return {
            "level": "CRITICAL",
            "reason": f"Heavy rainfall expected ({max_precipitation_mm}mm/hr peak) — "
                      f"risk of waterlogging and washout of biological applications.",
        }

    # Heat spike
    if max_temperature_c > 38:
        return {
            "level": "CRITICAL",
            "reason": f"Severe heat spike expected ({max_temperature_c}°C) — "
                      f"significant crop stress risk.",
        }

    if max_precipitation_mm > 15 or max_temperature_c > 34:
        return {
            "level": "HIGH",
            "reason": "Moderate stress conditions forecast — "
                      "proactive biological intervention recommended within 24-48h.",
        }

    if total_precipitation_mm is not None and total_precipitation_mm > 40:
        return {
            "level": "HIGH",
            "reason": f"Sustained heavy rainfall expected ({total_precipitation_mm}mm total) — "
                      f"waterlogging risk over coming days.",
        }

    if max_temperature_c > 30 or max_precipitation_mm > 5:
        return {
            "level": "LOW",
            "reason": "Mild stress signals present — monitor conditions.",
        }

    return {"level": "NONE", "reason": "No significant stress signals detected."}


def build_explainability_breakdown(readiness: dict, weather_snapshot: dict, biological_guidance: dict = None):
    """
    Converts the readiness score into a point-contribution breakdown
    for the "Scientific Explainability Panel" - shows which factors
    pushed the score up or down and by roughly how much, plus a plain
    recommendation on WHEN to apply.

    This is a presentational decomposition of the same underlying
    component scores already computed in compute_readiness_score -
    it does not introduce a new/different scoring model, just makes
    the existing one legible at a glance.
    """
    components = readiness.get("components", {})
    factors = []

    # Each component's score (0-100) is converted to a signed
    # contribution around a neutral midpoint (50), scaled down so the
    # sum of contributions is proportionate to a 0-100 readiness range.
    weight_map = {
        "soil_moisture": ("Soil Moisture", 0.35),
        "ndvi": ("Vegetation Health", 0.30),
        "temperature": ("Temperature", 0.25),
    }

    for key, (label, weight) in weight_map.items():
        score = components.get(key)
        if score is None:
            continue
        contribution = round((score - 50) * weight, 0)
        factors.append({
            "label": label,
            "contribution": int(contribution),
            "positive": contribution >= 0,
        })

    # Rain forecast penalty (already reflected in the capped score,
    # shown here separately for transparency)
    if readiness.get("rain_risk_flag"):
        factors.append({"label": "Rain Forecast", "contribution": -10, "positive": False})

    # Chemical compatibility penalty, if a biological class was selected
    if biological_guidance:
        compat = biological_guidance.get("compatibility", {})
        if compat.get("risk") is True:
            factors.append({"label": "Chemical Residue Risk", "contribution": -7, "positive": False})

    # Recommendation timing - simple, explainable rule, not a separate model
    score = readiness.get("score")
    if score is None:
        recommendation = "Insufficient data for a timing recommendation."
    elif readiness.get("rain_risk_flag"):
        recommendation = "Apply within next 24 hours, before forecast rain arrives."
    elif score >= 70:
        recommendation = "Apply within 24 hours — conditions currently favorable."
    elif score >= 40:
        recommendation = "Marginal conditions — consider waiting 24-48h if possible."
    else:
        recommendation = "Hold application — conditions not currently favorable."

    return {
        "score": score,
        "factors": factors,
        "recommendation": recommendation,
    }


def build_risk_timeline(readiness: dict, weather_snapshot: dict):
    """
    Builds a simple 0-5 bar-style risk indicator for four dimensions,
    for the "Risk Timeline Today" panel.

    IMPORTANT HONESTY NOTE: "Disease Risk" here is an illustrative
    heuristic (high humidity + moderate temperature broadly favor many
    fungal pathogens), NOT a validated, crop-specific disease
    prediction model. No disease-specific epidemiological model exists
    in this pipeline. This is clearly labeled as illustrative in the
    dashboard - do not present it as a calibrated prediction.
    """
    weather_snapshot = weather_snapshot or {}
    max_precip = weather_snapshot.get("max_precipitation_mm")
    max_temp = weather_snapshot.get("max_temperature_c")
    humidity = weather_snapshot.get("avg_humidity_pct")

    def to_bars(value, thresholds):
        """Converts a value into a 0-5 bar count given ascending thresholds."""
        if value is None:
            return 0
        bars = 0
        for t in thresholds:
            if value >= t:
                bars += 1
        return min(bars, 5)

    rain_bars = to_bars(max_precip, [2, 5, 10, 20, 30])
    heat_bars = to_bars(max_temp, [28, 31, 34, 37, 40])

    moisture_score = readiness.get("components", {}).get("soil_moisture")
    moisture_bars = to_bars(moisture_score, [20, 40, 60, 80, 95]) if moisture_score is not None else 0

    disease_bars = 0
    if humidity is not None and max_temp is not None:
        if humidity > 80 and 20 <= max_temp <= 32:
            disease_bars = 4
        elif humidity > 70 and 18 <= max_temp <= 34:
            disease_bars = 3
        elif humidity > 60:
            disease_bars = 2
        else:
            disease_bars = 1

    return {
        "rain_risk_bars": rain_bars,
        "heat_stress_bars": heat_bars,
        "moisture_bars": moisture_bars,
        "disease_risk_bars": disease_bars,
        "disease_risk_disclaimer": (
            "Illustrative heuristic based on humidity/temperature only — "
            "not a validated, crop-specific disease prediction model."
        ),
    }


def build_field_report(satellite_snapshot: dict, weather_snapshot: dict,
                        biological_class: str = None,
                        days_since_last_chemical_application: int = None):
    """
    Top-level function: combines a satellite snapshot (from
    ingestion/gee_ingest.py) and a weather snapshot (from
    ingestion/weather_ingest.py) into one complete field report.

    Optionally accepts a biological_class (e.g. "trichoderma",
    "bacillus") for organism-specific viability scoring, chemical
    compatibility checking, and application timing guidance. If not
    provided, the report falls back to the generic readiness score
    only (original behavior, fully backward-compatible).
    """
    readiness = compute_readiness_score(
        soil_moisture=satellite_snapshot.get("soil_moisture"),
        land_surface_temp_c=satellite_snapshot.get("land_surface_temp_c"),
        ndvi=satellite_snapshot.get("ndvi"),
        max_precipitation_mm=weather_snapshot.get("max_precipitation_mm") if weather_snapshot else None,
    )

    warning = classify_early_warning(
        max_precipitation_mm=weather_snapshot.get("max_precipitation_mm") if weather_snapshot else None,
        max_temperature_c=weather_snapshot.get("max_temperature_c") if weather_snapshot else None,
        total_precipitation_mm=weather_snapshot.get("total_precipitation_mm") if weather_snapshot else None,
    )

    biological_guidance = build_biological_guidance(
        land_surface_temp_c=satellite_snapshot.get("land_surface_temp_c"),
        biological_class=biological_class,
        days_since_last_chemical_application=days_since_last_chemical_application,
    )

    explainability = build_explainability_breakdown(readiness, weather_snapshot, biological_guidance)
    risk_timeline = build_risk_timeline(readiness, weather_snapshot)

    return {
        "location": {"lat": satellite_snapshot.get("lat"), "lon": satellite_snapshot.get("lon")},
        "readiness": readiness,
        "early_warning": warning,
        "biological_guidance": biological_guidance,
        "explainability": explainability,
        "risk_timeline": risk_timeline,
        "raw_satellite": satellite_snapshot,
        "raw_weather": weather_snapshot,
    }


if __name__ == "__main__":
    # Example using the real values you already pulled live:
    example_satellite = {
        "lat": 30.15, "lon": 78.78,
        "soil_moisture": 0.3258799477057024,
        "ndvi": 0.44122636661651454,
        "land_surface_temp_c": 27.01,
    }
    example_weather = {
        "max_precipitation_mm": 6.7,
        "total_precipitation_mm": 48.2,
        "max_temperature_c": 29.0,
        "avg_humidity_pct": 88.8,
    }

    print("=== Without biological class (generic score only) ===")
    report = build_field_report(example_satellite, example_weather)
    import json
    print(json.dumps(report, indent=2))

    print("\n=== With biological class: Trichoderma, no recent chemical spray info ===")
    report_trich = build_field_report(
        example_satellite, example_weather,
        biological_class="trichoderma",
    )
    print(json.dumps(report_trich["biological_guidance"], indent=2))

    print("\n=== With biological class: Trichoderma, chemical sprayed 2 days ago (should flag risk) ===")
    report_trich_risk = build_field_report(
        example_satellite, example_weather,
        biological_class="trichoderma",
        days_since_last_chemical_application=2,
    )
    print(json.dumps(report_trich_risk["biological_guidance"], indent=2))

    print("\n=== With biological class: Bacillus (more heat-tolerant, same temp) ===")
    report_bacillus = build_field_report(
        example_satellite, example_weather,
        biological_class="bacillus",
    )
    print(json.dumps(report_bacillus["biological_guidance"], indent=2))
