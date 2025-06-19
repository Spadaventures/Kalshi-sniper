import re
import json
import threading

import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ── 0) PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🌡️ Live 3-City Temp Sniper",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 1) YOUR THREE KALSHI MARKET URLS ────────────────────────────────────────────
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# ── 2) COORDINATES FOR CONFIDENCE MODEL ─────────────────────────────────────────
COORDS = {
    "LA":    (33.9425,  -118.4081),  # LAX
    "NYC":   (40.7812,   -73.9665),  # Central Park
    "MIAMI": (25.7959,   -80.2870),  # MIA
}

WS_URL = "wss://stream.kalshi.com/v1/feed"

# ── 3) SESSION STATE SETUP ─────────────────────────────────────────────────────
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}   # city -> list of slugs
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}   # slug -> latest YES percentage

# ── 4) DISCOVERY FUNCTION (WITH DESKTOP UA FIX) ────────────────────────────────
def discover_slugs(url):
    """Fetch full SSR HTML (desktop UA), extract the Next.js JSON, return outcome slugs."""
    desktop_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }
    html = requests.get(url, headers=desktop_headers, timeout=5).text

    # First try the <script id="__NEXT_DATA__"> block
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html)
    if not m:
        # Fallback to window.__NEXT_DATA__ = {...};
        m = re.search(r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?})\s*;', html)

    if not m:
        st.error("❌ Could not find NEXT_DATA JSON on page (got mobile HTML).")
        return []

    try:
        nd = json.loads(m.group(1))
        market = nd["props"]["pageProps"]["market"]
        slugs  = [o["slug"] for o in market.get("outcomes", []) if "slug" in o]
    except Exception as e:
        st.error(f"❌ JSON parse error: {e}")
        return []

    # Initialize live_yes entries
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

# Run discovery once per city
for city, url in PARENT_URLS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover_slugs(url)

# ── 5) WEBSOCKET HANDLERS ───────────────────────────────────────────────────────
def _on_message(ws, raw_msg):
    msg = json.loads(raw_msg)
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

def _start_ws():
    ws = websocket.WebSocketApp(WS_URL, on_open=_on_open, on_message=_on_message)
    ws.run_forever()

threading.Thread(target=_start_ws, daemon=True).start()

# ── 6) ENSEMBLE CONFIDENCE (no API key) ─────────────────────────────────────────
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

# ── 7) UI DASHBOARD ─────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)

    if not slugs:
        st.info("⚙️ Fetching outcome buckets…")
        continue

    yes_vals = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    # show table of buckets + live YES%
    st.table({
        "Bucket Slug": slugs,
        "Live YES %":  [f"{v:.1f}%" for v in yes_vals]
    })

    # pick best bucket safely
    best_i    = max(range(len(yes_vals)), key=lambda i: yes_vals[i])
    best_slug = slugs[best_i]
    best_yes  = yes_vals[best_i]
    conf      = get_confidence(city)

    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`** @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")