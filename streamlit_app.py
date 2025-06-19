# streamlit_app.py

import json
import threading

import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# Your three public Kalshi market slugs (no secret keys needed)
MARKET_IDS = {
    "LA":    "kxhighlax",
    "NYC":   "kxhighny",
    "MIAMI": "kxhighmia",
}

# Fixed outcome ranges for each market (in the same order Kalshi shows them)
OUTCOME_RANGES = {
    "LA":    ["74° to 75°", "76° to 77°", "78° or above"],
    "NYC":   ["79° to 80°", "81° to 82°", "83° or above"],
    "MIAMI": ["84° to 85°", "86° to 87°", "88° or above"],
}

# Coordinates for tomorrow’s max-temp ensemble
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

# Kalshi’s public WebSocket endpoint
WS_URL = "wss://stream.kalshi.com/v1/feed"

# In-memory store for live YES% per market slug
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {slug: 0.0 for slug in MARKET_IDS.values()}


# ── WEBSOCKET CLIENT ────────────────────────────────────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)
    # price updates come over "prices" channel
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        slug = msg["market"]
        st.session_state["live_yes"][slug] = float(msg["yes"])

def on_open(ws):
    # subscribe to each of our three market slugs
    for slug in MARKET_IDS.values():
        ws.send(json.dumps({
            "action":  "subscribe",
            "channel": "prices",
            "market":  slug
        }))

def run_ws():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
    )
    ws.run_forever()

threading.Thread(target=run_ws, daemon=True).start()


# ── ENSEMBLE CONFIDENCE ────────────────────────────────────────────────────────
def fetch_confidence(code):
    lat, lon = COORDS[code]
    # try Open-Meteo ensemble
    try:
        resp = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude":      lat,
                "longitude":     lon,
                "models":        "gfs_ensemble_seamless,ecmwf_ifs_025",
                "daily":         "temperature_2m_max",
                "forecast_days": 1,
                "timezone":      "auto",
            },
            timeout=5
        ).json()
        temps = resp["daily"]["temperature_2m_max"]
    except Exception:
        # fallback to OpenWeather (8 × 3h blocks)
        ow = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}"
            f"&appid={st.secrets['WEATHER_API_KEY']}&units=imperial",
            timeout=5
        ).json().get("list", [])
        temps = [b["main"]["temp_max"] for b in ow[:8] if "main" in b]

    if not temps:
        return 50.0
    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg - 75) * 3 - spread * 2
    return float(np.clip(raw, 10, 99))


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for code, slug in MARKET_IDS.items():
    st.subheader(code)

    # live market-wide YES%
    yes = st.session_state["live_yes"].get(slug, 0.0)

    # confidence
    conf = fetch_confidence(code)

    # outcome table
    st.table({
        "Range":        OUTCOME_RANGES[code],
        "Live YES %":   [f"{yes:.1f}%"] * len(OUTCOME_RANGES[code])
    })

    # recommend the highest bucket if market-wide YES% beats our conf
    top = OUTCOME_RANGES[code][-1]
    if yes > conf:
        st.markdown(f"👉 **Back `{top}`** at **{yes:.1f}%** (conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: market {yes:.1f}% vs conf {conf:.1f}%")