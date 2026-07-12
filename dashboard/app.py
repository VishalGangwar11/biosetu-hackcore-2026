"""
BioSetu - Layer 6: Live Dashboard (Streamlit)
----------------------------------------------
A single-file, live dashboard that calls the real pipeline
(ingestion -> scoring -> advisory) on demand and displays results.

No mock data anywhere. Every number shown is either pulled live
from Earth Engine / Open-Meteo, or computed directly from that
live data by the scoring engine.

Requires: pip install streamlit
Run with:
    streamlit run dashboard/app.py
(NOT `python dashboard/app.py` - Streamlit apps must be launched
via the `streamlit run` command.)
"""

import sys
import os
import json
import datetime

import streamlit as st

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ingestion"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scoring"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "advisory"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "delivery"))

from gee_ingest import get_field_snapshot
from weather_ingest import get_weather_snapshot
from readiness_engine import build_field_report
from gemini_advisory import generate_advisory
from telegram_delivery import send_field_alert


st.set_page_config(page_title="BioSetu - Field Readiness Dashboard", page_icon="🌾", layout="wide")

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "report_history.json")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_to_history(report):
    history = load_history()
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "lat": report["location"]["lat"],
        "lon": report["location"]["lon"],
        "score": report["readiness"]["score"],
        "warning_level": report["early_warning"]["level"],
    }
    history.append(entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


# ---------------------------------------------------------------
# Sidebar - field configuration
# ---------------------------------------------------------------
st.sidebar.title("🌾 BioSetu")
st.sidebar.caption("Sky-to-Soil Bridge — HACK CORE 2026")

lat = st.sidebar.number_input("Latitude", value=30.15, format="%.4f")
lon = st.sidebar.number_input("Longitude", value=78.78, format="%.4f")
project_id = st.sidebar.text_input("GEE Project ID", value=os.environ.get("GEE_PROJECT_ID", ""))
language = st.sidebar.selectbox("Advisory language", ["Hindi", "English", "Marathi", "Tamil", "Telugu"])

st.sidebar.divider()
st.sidebar.subheader("Biological Product Details")
bio_class_options = {
    "None (generic score only)": None,
    "Trichoderma (fungal biocontrol)": "trichoderma",
    "Bacillus (bacterial/endospore)": "bacillus",
    "Rhizobium / Bradyrhizobium": "rhizobium",
    "Azotobacter": "azotobacter",
    "Azospirillum": "azospirillum",
    "Pseudomonas fluorescens": "pseudomonas",
    "Mycorrhizae (AMF)": "mycorrhizae",
    "Seaweed extract": "seaweed_extract",
    "Humic/Fulvic acid": "humic_fulvic",
    "Protein hydrolysate": "protein_hydrolysate",
}
bio_class_label = st.sidebar.selectbox("Biological product type", list(bio_class_options.keys()))
biological_class = bio_class_options[bio_class_label]

days_since_chemical = None
if biological_class is not None:
    chemical_known = st.sidebar.checkbox("I know when a chemical pesticide was last applied here")
    if chemical_known:
        days_since_chemical = st.sidebar.number_input(
            "Days since last chemical pesticide application", min_value=0, value=10, step=1
        )

send_telegram = st.sidebar.checkbox("Also send to Telegram", value=False)

run_button = st.sidebar.button("🔄 Fetch Live Field Report", type="primary")

st.sidebar.divider()
st.sidebar.caption(
    "All data shown is pulled live from Google Earth Engine "
    "(soil moisture, NDVI, land surface temperature) and Open-Meteo "
    "(weather forecast). No mock or simulated values are used here."
)


# ---------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------
st.title("Biological Application Readiness Dashboard")
st.caption(
    "PS-01 (Agroclimatic Readiness Mapper) + PS-02 (Climate Stress Early Warning) — "
    "integrated solution, live data end-to-end."
)

if "report" not in st.session_state:
    st.session_state.report = None
    st.session_state.advisory = None

if run_button:
    with st.spinner("Fetching live satellite data..."):
        try:
            satellite_snapshot = get_field_snapshot(lat=lat, lon=lon, project_id=project_id)
        except Exception as e:
            st.error(f"Earth Engine fetch failed: {e}")
            satellite_snapshot = None

    with st.spinner("Fetching live weather forecast..."):
        try:
            weather_snapshot = get_weather_snapshot(lat=lat, lon=lon)
        except Exception as e:
            st.error(f"Weather fetch failed: {e}")
            weather_snapshot = None

    if satellite_snapshot is not None:
        report = build_field_report(
            satellite_snapshot, weather_snapshot,
            biological_class=biological_class,
            days_since_last_chemical_application=days_since_chemical,
        )
        st.session_state.report = report

        with st.spinner("Generating farmer advisory..."):
            advisory = generate_advisory(report, language=language)
            st.session_state.advisory = advisory

        save_to_history(report)

        if send_telegram:
            with st.spinner("Sending Telegram alert..."):
                result = send_field_alert(report, advisory)
                if result["success"]:
                    st.success("Telegram alert sent.")
                else:
                    st.warning(f"Telegram delivery failed: {result['error']}")


report = st.session_state.report
advisory = st.session_state.advisory

if report is None:
    st.info("Click **Fetch Live Field Report** in the sidebar to pull real satellite and weather data.")
else:
    readiness = report["readiness"]
    warning = report["early_warning"]

    col1, col2, col3 = st.columns(3)

    with col1:
        score = readiness["score"]
        st.metric("Biological Readiness Score", f"{score}/100" if score is not None else "N/A")
        if readiness["confidence_band"][0] is not None:
            st.caption(
                f"Confidence band: {readiness['confidence_band'][0]}-{readiness['confidence_band'][1]} "
                f"(data confidence: {readiness['confidence']}%)"
            )

    with col2:
        level_colors = {
            "CRITICAL": "🔴", "HIGH": "🟠", "LOW": "🟡", "NONE": "🟢", "UNKNOWN": "⚪"
        }
        st.metric("Early Warning Level", f"{level_colors.get(warning['level'], '⚪')} {warning['level']}")
        st.caption(warning["reason"])

    with col3:
        st.metric("Rain Risk (application washout)", "Yes" if readiness.get("rain_risk_flag") else "No")

    st.divider()

    bio_guidance = report.get("biological_guidance")
    if bio_guidance:
        st.subheader(f"🧬 Biological Product Guidance: {bio_guidance['label']}")

        bg_col1, bg_col2, bg_col3 = st.columns(3)
        with bg_col1:
            st.metric("Product Viability Score", f"{bio_guidance['viability_score']}/100"
                       if bio_guidance['viability_score'] is not None else "N/A")

        with bg_col2:
            compat = bio_guidance["compatibility"]
            if compat["risk"] is True:
                st.error("⚠️ Chemical compatibility risk")
            elif compat["risk"] is False:
                st.success("✅ No compatibility risk")
            else:
                st.warning("❔ Compatibility unknown")
            st.caption(compat["reason"])

        with bg_col3:
            if bio_guidance["timing_guidance"]:
                st.info(bio_guidance["timing_guidance"])
            else:
                st.caption("No special timing requirement for this product class.")

        st.caption(f"**Notes:** {bio_guidance['notes']}")
        st.caption(f"**Source:** {bio_guidance['source']}")

        st.divider()

    st.subheader("Indicator Breakdown")
    comp_col1, comp_col2, comp_col3 = st.columns(3)
    components = readiness["components"]
    raw = report["raw_satellite"]

    with comp_col1:
        st.write("**Soil Moisture**")
        st.write(f"Raw: {raw.get('soil_moisture')}")
        st.progress(min(1.0, (components.get("soil_moisture") or 0) / 100))

    with comp_col2:
        st.write("**NDVI (vegetation health)**")
        st.write(f"Raw: {raw.get('ndvi')}")
        st.progress(min(1.0, (components.get("ndvi") or 0) / 100))

    with comp_col3:
        st.write("**Land Surface Temp**")
        st.write(f"Raw: {raw.get('land_surface_temp_c')}C")
        st.progress(min(1.0, (components.get("temperature") or 0) / 100))

    st.divider()

    if advisory:
        st.subheader(f"Farmer Advisory ({advisory['language']})")
        st.info(advisory["message"])
        st.caption(f"Generated via: {advisory['source']}")

    st.divider()

    with st.expander("Raw field report (JSON)"):
        st.json(report)

    history = load_history()
    if history:
        st.subheader("Report History (this session's location queries)")
        st.dataframe(history, use_container_width=True)
