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
import folium
from streamlit_folium import st_folium

# Streamlit Cloud secrets (st.secrets) are NOT automatically available
# as os.environ variables to the rest of the codebase. Since all our
# other modules (gee_ingest, gemini_advisory, telegram_delivery) read
# from os.environ / .env for local-dev consistency, we explicitly copy
# every secret into os.environ here, once, at startup. This makes the
# same code work identically whether run locally (.env file) or on
# Streamlit Cloud (secrets manager) - no auth-path-specific code needed
# elsewhere.
for _key in [
    "GEE_PROJECT_ID", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "GEE_SERVICE_ACCOUNT_EMAIL", "GEE_SERVICE_ACCOUNT_KEY",
]:
    try:
        if _key in st.secrets:
            os.environ[_key] = str(st.secrets[_key])
    except Exception:
        pass  # no secrets.toml present (e.g. local run using .env instead) - fine

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ingestion"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scoring"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "advisory"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "delivery"))

from gee_ingest import get_field_snapshot, get_ndvi_thumbnail_url, init_earth_engine, get_field_geometry
from weather_ingest import get_weather_snapshot
from readiness_engine import build_field_report
from gemini_advisory import generate_advisory
from telegram_delivery import send_field_alert, format_alert_message
from geocoding import search_location


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


FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "field_feedback.json")


def load_feedback():
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_feedback(entry):
    feedback = load_feedback()
    feedback.append(entry)
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(feedback, f, indent=2)


# ---------------------------------------------------------------
# Sidebar - field configuration
# ---------------------------------------------------------------
st.sidebar.title("🌾 BioSetu")
st.sidebar.caption("Sky-to-Soil Bridge — HACK CORE 2026")

if "lat_input" not in st.session_state:
    st.session_state.lat_input = 30.15
if "lon_input" not in st.session_state:
    st.session_state.lon_input = 78.78
if "search_results" not in st.session_state:
    st.session_state.search_results = []

st.sidebar.subheader("📍 Find a Location")
search_query = st.sidebar.text_input("Search by place name", placeholder="e.g. Pauri Garhwal")
if st.sidebar.button("Search"):
    with st.spinner("Searching..."):
        st.session_state.search_results = search_location(search_query)
    if not st.session_state.search_results:
        st.sidebar.warning("No matches found — try a different spelling or a nearby larger town.")

if st.session_state.search_results:
    labels = [r["label"] for r in st.session_state.search_results]
    chosen_label = st.sidebar.selectbox("Select a match", labels)
    if st.sidebar.button("Use this location"):
        chosen = next(r for r in st.session_state.search_results if r["label"] == chosen_label)
        # Update the ACTUAL widget keys directly - Streamlit ignores a
        # number_input's `value=` argument on reruns once that widget's
        # key already has stored state, so this must set st.session_state
        # under the exact same keys the widgets below use ("lat_input" /
        # "lon_input"), not a separate shadow variable.
        st.session_state.lat_input = chosen["lat"]
        st.session_state.lon_input = chosen["lon"]
        st.session_state.search_results = []
        st.rerun()

st.sidebar.caption("Or enter coordinates manually:")
lat = st.sidebar.number_input("Latitude", format="%.4f", key="lat_input")
lon = st.sidebar.number_input("Longitude", format="%.4f", key="lon_input")

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
            st.warning(
                "Weather forecast temporarily unavailable (Open-Meteo did not respond "
                "in time after 3 attempts). Readiness score will use satellite data only; "
                "early warning will show as UNKNOWN until forecast data is available."
            )
            weather_snapshot = None

    if satellite_snapshot is not None:
        report = build_field_report(
            satellite_snapshot, weather_snapshot,
            biological_class=biological_class,
            days_since_last_chemical_application=days_since_chemical,
        )
        st.session_state.report = report

        with st.spinner("Rendering satellite map overlay..."):
            try:
                init_earth_engine(project_id)
                geometry = get_field_geometry(lat, lon)
                st.session_state.ndvi_thumb_url = get_ndvi_thumbnail_url(geometry)
            except Exception:
                st.session_state.ndvi_thumb_url = None

        with st.spinner("Generating farmer advisory..."):
            advisory = generate_advisory(report, language=language)
            st.session_state.advisory = advisory

        save_to_history(report)

        telegram_status = None
        if send_telegram:
            with st.spinner("Sending Telegram alert..."):
                result = send_field_alert(report, advisory)
                telegram_status = result
                if result["success"]:
                    st.success("Telegram alert sent.")
                else:
                    st.warning(f"Telegram delivery failed: {result['error']}")
        st.session_state.telegram_status = telegram_status


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

    # -----------------------------------------------------------
    # Confidence & Data Quality panel
    # -----------------------------------------------------------
    st.subheader("🔎 Confidence & Data Quality")
    dq = report["raw_satellite"].get("data_quality", {})
    dq_col1, dq_col2, dq_col3, dq_col4 = st.columns(4)

    with dq_col1:
        st.metric("Prediction Confidence", f"{readiness['confidence']}%")

    with dq_col2:
        cloud_pct = dq.get("cloud_pct")
        if cloud_pct is not None:
            st.metric("Cloud Contamination", f"{round(cloud_pct, 1)}%")
        else:
            st.metric("Cloud Contamination", "N/A")

    with dq_col3:
        last_pass = dq.get("last_satellite_pass_date")
        if last_pass:
            days_ago = (datetime.date.today() - datetime.date.fromisoformat(last_pass)).days
            st.metric("Last Satellite Pass", f"{days_ago}d ago" if days_ago > 0 else "Today")
        else:
            st.metric("Last Satellite Pass", "N/A")

    with dq_col4:
        weather_ok = report.get("raw_weather") is not None
        st.metric("Weather Forecast", "✔ Available" if weather_ok else "✖ Unavailable")

    if dq.get("ndvi_window_days_used") and dq.get("ndvi_window_days_used") > 14:
        st.caption(
            f"⚠️ Vegetation data is from a {dq['ndvi_window_days_used']}-day lookback window "
            f"(recent cloud cover prevented a fresher image) — treat NDVI as a lagging indicator this cycle."
        )

    st.divider()

    # -----------------------------------------------------------
    # Interactive satellite map
    # -----------------------------------------------------------
    st.subheader("🗺️ Field Location Map")
    map_col1, map_col2 = st.columns([2, 1])

    with map_col1:
        field_map = folium.Map(location=[lat, lon], zoom_start=12, tiles="OpenStreetMap")
        folium.Marker(
            [lat, lon],
            popup=f"Readiness: {readiness['score']}/100<br>Warning: {warning['level']}",
            icon=folium.Icon(color="green" if warning["level"] == "NONE" else "orange", icon="leaf"),
        ).add_to(field_map)

        ndvi_thumb_url = st.session_state.get("ndvi_thumb_url")
        if ndvi_thumb_url:
            try:
                buffer_deg = 0.015  # roughly matches the 1.5km thumbnail region
                folium.raster_layers.ImageOverlay(
                    image=ndvi_thumb_url,
                    bounds=[[lat - buffer_deg, lon - buffer_deg], [lat + buffer_deg, lon + buffer_deg]],
                    opacity=0.6,
                    name="NDVI",
                ).add_to(field_map)
                folium.LayerControl().add_to(field_map)
            except Exception:
                pass

        st_folium(field_map, width=None, height=380, key="field_map")

    with map_col2:
        st.caption(
            "Green marker = no active stress warning. Orange = an early warning "
            "is active. NDVI overlay (if visible) shows a real Sentinel-2-derived "
            "vegetation map for this field, not an illustration."
        )
        if ndvi_thumb_url:
            st.caption("🟩 Dark green = healthy vegetation · 🟥 Red = sparse/stressed vegetation")

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

    # -----------------------------------------------------------
    # Scientific Explainability Panel
    # -----------------------------------------------------------
    explain = report.get("explainability")
    if explain:
        st.subheader("🔬 Scientific Explainability Panel")
        st.write(f"**Readiness Score: {explain['score']}/100**")
        st.caption("Why?")

        for factor in explain["factors"]:
            icon = "✅" if factor["positive"] else "⚠️"
            sign = "+" if factor["contribution"] >= 0 else ""
            st.write(f"{icon} {factor['label']}: **{sign}{factor['contribution']}**")

        st.info(f"**Recommendation:** {explain['recommendation']}")
        st.caption(
            "This breakdown decomposes the same readiness score shown above into "
            "per-factor contributions — it is not a separate or different model."
        )

        st.divider()

    # -----------------------------------------------------------
    # Risk Timeline Today
    # -----------------------------------------------------------
    risk_timeline = report.get("risk_timeline")
    if risk_timeline:
        st.subheader("📊 Risk Timeline — Today")

        def render_bar(label, bars, max_bars=5):
            filled = "🟩" * bars + "⬜" * (max_bars - bars)
            st.write(f"**{label}**  {filled}")

        rt_col1, rt_col2 = st.columns(2)
        with rt_col1:
            render_bar("Rain Risk", risk_timeline["rain_risk_bars"])
            render_bar("Moisture", risk_timeline["moisture_bars"])
        with rt_col2:
            render_bar("Heat Stress", risk_timeline["heat_stress_bars"])
            render_bar("Disease Risk", risk_timeline["disease_risk_bars"])

        st.caption(f"⚠️ Disease Risk: {risk_timeline['disease_risk_disclaimer']}")

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

        st.subheader("📱 Telegram Alert Preview")
        st.caption(
            "This is exactly what gets sent to the farmer's Telegram bot when an alert "
            "fires — shown here directly since the actual delivery goes to a private "
            "chat that isn't visible during remote/online screening."
        )

        telegram_message = format_alert_message(report, advisory)
        # Render as a Telegram-style chat bubble so it's visually self-evident
        # this is a delivered alert, not just raw text.
        bubble_html = f"""
        <div style="max-width: 480px; background-color: #efeae2; border-radius: 12px;
                    padding: 16px; font-family: -apple-system, Roboto, sans-serif;">
            <div style="display: flex; align-items: center; margin-bottom: 10px;">
                <div style="width: 32px; height: 32px; border-radius: 50%;
                            background: linear-gradient(135deg, #4facfe, #00f2fe);
                            display: flex; align-items: center; justify-content: center;
                            color: white; font-weight: bold; margin-right: 8px;">B</div>
                <div>
                    <div style="font-weight: 600; font-size: 14px; color: #1a1a1a;">BioSetu Alerts</div>
                    <div style="font-size: 11px; color: #667781;">bot</div>
                </div>
            </div>
            <div style="background-color: white; border-radius: 8px; padding: 10px 12px;
                        font-size: 13.5px; color: #1a1a1a; line-height: 1.5;
                        white-space: pre-wrap; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">
                {telegram_message.replace(chr(10), '<br>')}
            </div>
        </div>
        """
        st.markdown(bubble_html, unsafe_allow_html=True)

        telegram_status = st.session_state.get("telegram_status")
        if telegram_status is not None:
            if telegram_status.get("success"):
                st.success("✅ This exact message was delivered live to the BioSetu Telegram bot during this session.")
            else:
                st.warning(f"⚠️ Live delivery was attempted but failed: {telegram_status.get('error')}")
        else:
            st.caption(
                "Check 'Also send to Telegram' in the sidebar and re-fetch to trigger "
                "a real, live delivery to the bot in addition to this preview."
            )

    st.divider()

    # -----------------------------------------------------------
    # Field Outcome Feedback (PS-05 "Season Journal" concept)
    # -----------------------------------------------------------
    st.subheader("🌱 Field Outcome Feedback")
    st.caption(
        "This closes the feedback loop described in PS-05/PS-06/PS-07 — "
        "capturing what actually happened in the field so future "
        "recommendations can be validated against real outcomes. "
        "Stored locally for this hackathon demo; a production version "
        "would aggregate this across many farmers into a shared dataset."
    )

    applied = st.radio(
        "Did you apply the recommended biological product?",
        ["Not yet answered", "Yes", "No"],
        index=0,
        key="feedback_applied",
    )

    if applied == "Yes":
        fb_col1, fb_col2 = st.columns(2)
        with fb_col1:
            date_applied = st.date_input("Date Applied", value=datetime.date.today())
            crop_condition = st.selectbox("Crop Condition", ["Healthy", "Average", "Poor"])
        with fb_col2:
            uploaded_image = st.file_uploader("Upload Field Image (Optional)", type=["jpg", "jpeg", "png"])
            helpfulness = st.slider("Recommendation Helpfulness (1-5)", min_value=1, max_value=5, value=3)

        remarks = st.text_area("Remarks", placeholder="Anything worth noting about this application...")

        if st.button("Submit Feedback"):
            feedback_entry = {
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "location": {"lat": lat, "lon": lon},
                "readiness_score_at_recommendation": readiness.get("score"),
                "biological_class": biological_class,
                "applied": True,
                "date_applied": str(date_applied),
                "crop_condition": crop_condition,
                "helpfulness_rating": helpfulness,
                "remarks": remarks,
                "image_uploaded": uploaded_image is not None,
                "image_filename": uploaded_image.name if uploaded_image else None,
            }
            save_feedback(feedback_entry)
            st.success("Thank you — this feedback has been recorded and will inform future scoring calibration.")

    elif applied == "No":
        no_reason = st.text_area("Why not? (Optional)", placeholder="e.g. weather changed, product unavailable...")
        if st.button("Submit Feedback"):
            feedback_entry = {
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "location": {"lat": lat, "lon": lon},
                "readiness_score_at_recommendation": readiness.get("score"),
                "biological_class": biological_class,
                "applied": False,
                "reason_not_applied": no_reason,
            }
            save_feedback(feedback_entry)
            st.success("Thank you — this feedback has been recorded.")

    feedback_history = load_feedback()
    if feedback_history:
        with st.expander(f"📋 View all recorded feedback ({len(feedback_history)} entries)"):
            st.dataframe(feedback_history, use_container_width=True)

    st.divider()

    with st.expander("Raw field report (JSON)"):
        st.json(report)

    history = load_history()
    if history:
        st.subheader("Report History (this session's location queries)")
        st.dataframe(history, use_container_width=True)
