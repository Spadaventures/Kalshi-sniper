# streamlit_app.py

import json
import threading
import re

import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ── 0) CONFIG ───────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# Your three parent-market URLs:
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# Coordinates for tomorrow’s max-temp ensemble
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

WS_URL = "wss://stream.kalshi.com/v1/feed"

# State
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}   # city → [slug,…]
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}   # slug → float

# ── 1) DISCOVER OUTCOME SLUGS VIA __NEXT_DATA__ ─────────────────────────────────
def discover_slugs(url):
    """Fetch the HTML, parse Next.js JSON, extract all outcome slugs."""
    html = requests.get(url, timeout=5).text

    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
        html,
        flags=re.DOTALL
    )
    if not m:
        return []

    data = json.loads(m.group(1))
    # drill into pageProps → market → outcomes
    market = data.get("props", {}) \
                 .get("pageProps", {}) \
                 .get("market", {})
    outcomes = market.get("outcomes", [])
    slugs = [o["slug"] for o in outcomes if "slug" in o]
    # init live_yes
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

# run discovery once per city
for city, url in PARENT_URLS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover_slugs(url)

# ── 2) WEBSOCKET FOR LIVE YES% ───────────────────────────────────────────────────
def _on_message(ws, raw):
    msg = json.loads(raw)
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        st.session_state["live_yes"][msg["market"]] = float(msg["yes"])

def _on_open(ws):
    for slugs in st.session_state["outcomes"].values():
        for slug in slugs:
            ws.send(json.dumps({
                "action":  "subscribe",
                "channel": "prices",
                "market":  slug
            }))

def _ws_runner():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=_on_open,
        on_message=_on_message
    )
    ws.run_forever()

threading.Thread(target=_ws_runner, daemon=True).start()

# ── 3) ENSEMBLE CONFIDENCE (Open-Meteo) ──────────────────────────────────────────
def get_confidence(city):
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
                "timezone":      "auto",
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

# ── 4) DASHBOARD ────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)

    # if discovery failed
    if not slugs:
        st.info("⚙️ Still fetching that city’s outcome buckets…")
        continue

    # gather live YES%
    yes_list = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    # display the table
    st.table({
        "Outcome Slug": slugs,
        "Live YES %":   [f"{v:.1f}%" for v in yes_list]
    })

    # pick best bucket
    best_i    = max(range(len(yes_list)), key=lambda i: yes_list[i])
    best_slug = slugs[best_i]
    best_yes  = yes_list[best_i]

    # compute confidence
    conf = get_confidence(city)

    # recommendation
    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`**  @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")