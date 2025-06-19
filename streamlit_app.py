# streamlit_app.py

import re
import json
import threading

import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# The three parent pages you gave me
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# Coordinates for ensemble confidence
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

WS_URL = "wss://stream.kalshi.com/v1/feed"

# In-memory stores
if "outcome_slugs" not in st.session_state:
    st.session_state["outcome_slugs"] = {}
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}

# ── 1) Discover each page’s 3 outcome-slugs ─────────────────────────────────────
def discover_outcomes(url):
    parent = url.split("/markets/")[1].split("#")[0]
    html   = requests.get(url, timeout=5).text
    candidates = set(re.findall(r'href="/markets/([^"/]+)"', html))
    # pick only those starting with the parent slug + '-'
    slugs = sorted(s for s in candidates if s.startswith(parent + "-"))
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

for code, url in PARENT_URLS.items():
    if code not in st.session_state["outcome_slugs"]:
        st.session_state["outcome_slugs"][code] = discover_outcomes(url)

# ── 2) WebSocket → live YES% for each outcome slug ──────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        st.session_state["live_yes"][msg["market"]] = float(msg["yes"])

def on_open(ws):
    for slugs in st.session_state["outcome_slugs"].values():
        for slug in slugs:
            ws.send(json.dumps({
                "action":  "subscribe",
                "channel": "prices",
                "market":  slug
            }))

def run_ws():
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
    ws.run_forever()

threading.Thread(target=run_ws, daemon=True).start()

# ── 3) Compute a physics-based confidence score ──────────────────────────────────
def fetch_confidence(code):
    lat, lon = COORDS[code]
    try:
        r = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude":lat, "longitude":lon,
                "models":"gfs_ensemble_seamless,ecmwf_ifs_025",
                "daily":"temperature_2m_max",
                "forecast_days":1,
                "timezone":"auto"
            }, timeout=5
        ).json()
        temps = r["daily"]["temperature_2m_max"]
    except Exception:
        ow = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}"
            f"&appid={st.secrets['WEATHER_API_KEY']}&units=imperial",
            timeout=5
        ).json().get("list",[])
        temps = [b["main"]["temp_max"] for b in ow[:8] if "main" in b]

    if not temps:
        return 50.0
    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg - 75)*3 - spread*2
    return float(np.clip(raw, 10, 99))

# ── 4) Dashboard ────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for code, slugs in st.session_state["outcome_slugs"].items():
    st.subheader(code)

    if not slugs:
        st.info("No outcomes found on this page.")
        continue

    # Gather live YES% for each slug
    yes_vals = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    # Display table
    st.table({
        "Range (slug)": slugs,
        "Live YES %":   [f"{v:.1f}%" for v in yes_vals]
    })

    # Pick the index of the max YES%
    best_idx = max(range(len(yes_vals)), key=lambda i: yes_vals[i])
    best_slug = slugs[best_idx]
    best_yes  = yes_vals[best_idx]

    # Your confidence signal
    conf = fetch_confidence(code)

    # Recommendation
    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`** at **{best_yes:.1f}%** (conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs conf {conf:.1f}%")