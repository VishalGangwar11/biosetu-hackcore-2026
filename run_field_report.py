"""
BioSetu - End-to-End Live Runner
------------------------------------
Connects Layer 1 (satellite + weather ingestion) to Layer 2/3
(readiness scoring + early warning) into a single live pipeline.

Usage:
    python run_field_report.py

Edit LAT, LON, and PROJECT_ID below for your target field.
"""

import json
import sys
import os

# Allow importing from sibling folders (ingestion/, scoring/, advisory/)
sys.path.append(os.path.join(os.path.dirname(__file__), "ingestion"))
sys.path.append(os.path.join(os.path.dirname(__file__), "scoring"))
sys.path.append(os.path.join(os.path.dirname(__file__), "advisory"))
sys.path.append(os.path.join(os.path.dirname(__file__), "delivery"))

from gee_ingest import get_field_snapshot
from weather_ingest import get_weather_snapshot
from readiness_engine import build_field_report
from gemini_advisory import generate_advisory
from telegram_delivery import send_field_alert


# -----------------------------------------------------------------
# CONFIGURE YOUR FIELD LOCATION HERE
# -----------------------------------------------------------------
LAT = 30.15
LON = 78.78
PROJECT_ID = "htip-bah2026"  # your GEE project ID
LANGUAGE = "Hindi"


def run():
    print(f"Fetching live satellite data for ({LAT}, {LON})...")
    satellite_snapshot = get_field_snapshot(lat=LAT, lon=LON, project_id=PROJECT_ID)
    print("Satellite snapshot:", satellite_snapshot)

    print("\nFetching live weather forecast...")
    weather_snapshot = get_weather_snapshot(lat=LAT, lon=LON)
    print("Weather snapshot:", weather_snapshot)

    print("\nBuilding field report...")
    report = build_field_report(satellite_snapshot, weather_snapshot)

    print("\nGenerating farmer advisory message...")
    advisory = generate_advisory(report, language=LANGUAGE)
    report["advisory"] = advisory

    print("\n" + "=" * 60)
    print("FULL FIELD REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print(f"FARMER MESSAGE ({LANGUAGE}):")
    print("=" * 60)
    print(advisory["message"])
    print(f"\n[generated via: {advisory['source']}]")

    print("\nSending alert to Telegram...")
    delivery_result = send_field_alert(report, advisory)
    if delivery_result["success"]:
        print("Telegram delivery: SUCCESS")
    else:
        print(f"Telegram delivery: FAILED ({delivery_result['error']})")

    report["delivery"] = delivery_result
    return report


if __name__ == "__main__":
    run()
