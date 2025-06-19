import re
import json
import threading

import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# The three “parent” market URLs you provided
PARENTS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# Geographic coords for tomorrow’s max-temp ensemble
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

# Public Kalshi WebSocket endpoint
WS_URL = "wss://stream.kalshi.com/v1/feed"

# In-memory stores
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}      # city -> list of outcome slugs
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}      # slug -> live YES%

# ── 1) Discover each page’s 3 outcome-slugs ────────────────────────────────────
def discover(city, url):
    parent_slug = url.split("/markets/")[1].split("#")[0]
    html = requests.get(url, timeout=5).text
    candidates = set(re.findall(r'href="/markets/([^"/]+)"', html))
    slugs = sorted(s for s in candidates if s.startswith(parent_slug + "-"))
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

for city, url in PARENTS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover(city, url)

# ── 2) WebSocket → live YES% for each outcome slug ──────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        st.session_state["live_yes"][msg["market"]] = float(msg["yes"])

def on_open(ws):
    for slugs in st.session_state["outcomes"].values():
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
def get_conf(city):
    lat, lon = COORDS[city]
    try:
        r = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude":      lat,
                "longitude":     lon,
                "models":        "gfs_ensemble_seamless,ecmwf_ifs_025",
                "daily":         "temperature_2m_max",
                "forecast_days": 1,
                "timezone":      "auto"
            },
            timeout=5
        ).json()
        temps = r["daily"]["temperature_2m_max"]
    except Exception:
        return 50.0

    if not temps:
        return 50.0

    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg - 75) * 3 - spread * 2
    return float(np.clip(raw, 10, 99))

# ── 4) DASHBOARD ───────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)

    # Gather live YES% for each slug
    yes_list = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    # If discovery hasn't run yet or no slugs found, show info
    if not slugs:
        st.info("🔍 Scanning for outcome buckets…")
        continue

    # Display table of ranges + live percentages
    st.table({
        "Outcome Slug": slugs,
        "Live YES %":   [f"{v:.1f}%" for v in yes_list]
    })

    # Compute best index safely
    best_idx = max(range(len(yes_list)), key=lambda i: yes_list[i])
    best_slug = slugs[best_idx]
    best_yes  = yes_list[best_idx]

    # Compute confidence
    conf = get_conf(city)

    # Render recommendation
    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`** @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")