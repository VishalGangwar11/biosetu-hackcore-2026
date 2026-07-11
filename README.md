# BioSetu — Sky-to-Soil Bridge

**HACK CORE 2026 (Syngenta Biologicals x ANNAM.AI, IIT Ropar)**
Integrated solution covering PS-01 (Agroclimatic Readiness Mapper) +
PS-02 (Climate Stress Early Warning), with an honest, clearly-labeled
PS-03-style advisory layer.

## What it does

Combines real satellite data (soil moisture, NDVI, land surface
temperature via Google Earth Engine) with real weather forecasts
(Open-Meteo) to generate a **Biological Readiness Score** for a given
field, plus an **Early Warning classifier** for incoming climate
stress events. Results are translated into plain-language,
multilingual farmer alerts via Gemini and delivered through a
Telegram bot (reused/adapted architecture).

## Why this approach

Most hackathon entries in this space either mock the data layer or
build a black-box score. BioSetu uses **live satellite/weather data**
end-to-end and an **explainable, threshold-based scoring model** with
confidence bounds, so every score can be justified against real
agronomic reference ranges rather than an opaque ML output.

## Architecture

```
ingestion/gee_ingest.py       → soil moisture, NDVI, LST (Earth Engine)
ingestion/weather_ingest.py   → rainfall, temperature, humidity forecast
scoring/                      → Biological Readiness Score + confidence bands
scoring/                      → Early Warning classifier (CRITICAL/HIGH/LOW)
advisory/                     → Gemini-based plain-language, multilingual output
delivery/                     → Telegram bot alert delivery
dashboard/                    → Live field map + score + alert history
```

## Honesty note on the recommendation layer

We do not have access to Syngenta's proprietary product-efficacy
dataset. The advisory layer is built on public agronomic literature
and is explicitly architected to ingest proprietary efficacy data
through the same pipeline once available — this is stated clearly in
the pitch rather than simulated.

## Setup

```bash
pip install -r requirements.txt
earthengine authenticate   # one-time, opens browser
```

Set environment variables (create a `.env` file, never commit it):
```
GEE_PROJECT_ID=your-project-id
GEMINI_API_KEY=your-key
TELEGRAM_BOT_TOKEN=your-token
TELEGRAM_CHAT_ID=your-chat-id
```

## Team

- Vishal Gangwar — Project Lead, AI Systems, Pipeline Architecture
- Mohit Singh Bohra — Data Engineering, Model Integration
