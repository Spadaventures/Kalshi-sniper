import re
import json
import threading
import numpy as np
import requests
import streamlit as st
import websocket  # pip install websocket-client

# ─────── 0) PAGE CONFIG ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🌡️ Live 3-City Temp Sniper",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────── 1) YOUR THREE MARKET PAGES ────────────────────────────────────────────
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# ─────── 2) COORDS FOR CONFIDENCE MODEL ────────────────────────────────────────
COORDS = {
    "LA":    (33.9425,  -118.4081),  # LAX
    "NYC":   (40.7812,   -73.9665),  # Central Park
    "MIAMI": (25.7959,   -80.2870),  # MIA
}

WS_URL = "wss://stream.kalshi.com/v1/feed"

# ─────── 3) SESSION STATE INIT ────────────────────────────────────────────────
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}   # city -> [slug,...]
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}   # slug -> latest yes%

# ─────── 4) DISCOVER SLUGS (desktop-UA + www + fallbacks) ──────────────────────
def discover_slugs(orig_url):
    # ensure "www." prefix
    url = orig_url.replace("://kalshi.com", "://www.kalshi.com")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        html = requests.get(url, headers=headers, timeout=10).text
    except Exception as e:
        st.error(f"❌ Unable to fetch {url}: {e}")
        return []

    # 1) <script id="__NEXT_DATA__">…</script>
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html)
    if not m:
        # 2) window.__NEXT_DATA__ = { … };
        m = re.search(r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?});', html)
    if not m:
        st.error("❌ Could not find NEXT_DATA JSON on page (still got mobile HTML).")
        return []

    try:
        nd = json.loads(m.group(1))
        market = nd["props"]["pageProps"]["market"]
        slugs  = [o["slug"] for o in market.get("outcomes", []) if "slug" in o]
    except Exception as e:
        st.error(f"❌ JSON parse error: {e}")
        return []

    # initialize live_yes
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

# run discovery once per city
for city, url in PARENT_URLS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover_slugs(url)

# ─────── 5) WEBSOCKET PUSH HANDLERS ────────────────────────────────────────────
def _on_message(ws, raw):
    msg = json.loads(raw)
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        st.session_state["live_yes"][ msg["market"] ] = float(msg["yes"])

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

# ─────── 6) ENSEMBLE CONFIDENCE (no API key) ──────────────────────────────────
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
        if not temps:
            return 50.0
    except:
        return 50.0

    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg - 75) * 3 - spread * 2
    return float(np.clip(raw, 10, 99))

# ─────── 7) RENDER DASHBOARD ───────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)

    if not slugs:
        st.info("⚙️ Fetching outcome buckets…")
        continue

    yes_vals = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    # show each bucket + live YES%
    st.table({
        "Bucket Slug": slugs,
        "Live YES %":  [f"{v:.1f}%" for v in yes_vals],
    })

    # pick highest-YES% bucket
    best_i    = max(range(len(yes_vals)), key=lambda i: yes_vals[i])
    best_slug = slugs[best_i]
    best_yes  = yes_vals[best_i]
    conf      = get_confidence(city)

    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`** @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")