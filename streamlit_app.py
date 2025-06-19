# streamlit_app.py

import re, json, threading
import numpy as np, requests, streamlit as st, websocket

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("🌡️ Live 3-City Temp Sniper", layout="wide")

PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}
WS_URL = "wss://stream.kalshi.com/v1/feed"

# In-memory
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}    # city → [slug,…]
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}    # slug → yes%

# ── 1) DISCOVER via __NEXT_DATA__ or window.__NEXT_DATA__ ──────────────────────
def discover_slugs(url):
    """Fetch page, find the embedded NEXT_DATA JSON, extract outcome slugs."""
    html = requests.get(url, timeout=5).text

    # Try <script id="__NEXT_DATA__">…</script>
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html)
    if not m:
        # Fallback to window.__NEXT_DATA__ = {...};
        m = re.search(r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?})\s*;', html)
    if not m:
        st.error("❌ Could not find NEXT_DATA JSON on page.")
        return []

    try:
        data = json.loads(m.group(1))
        market = data["props"]["pageProps"]["market"]
        slugs  = [o["slug"] for o in market.get("outcomes", []) if "slug" in o]
    except Exception as e:
        st.error(f"❌ JSON parse error: {e}")
        return []

    # init live_yes
    for s in slugs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return slugs

# Run once
for city, url in PARENT_URLS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover_slugs(url)

# ── 2) WEBSOCKET for live YES% ─────────────────────────────────────────────────
def on_message(ws, raw):
    msg = json.loads(raw)
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

def start_ws():
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
    ws.run_forever()

threading.Thread(target=start_ws, daemon=True).start()

# ── 3) ENSEMBLE CONFIDENCE (no key) ────────────────────────────────────────────
def get_conf(city):
    lat, lon = COORDS[city]
    try:
        r = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude":lat, "longitude":lon,
                "models":"gfs_ensemble_seamless,ecmwf_ifs_025",
                "daily":"temperature_2m_max","forecast_days":1,"timezone":"auto"
            }, timeout=5
        ).json()
        temps = r["daily"]["temperature_2m_max"]
    except:
        return 50.0
    if not temps:
        return 50.0
    avg, spread = np.mean(temps), max(temps)-min(temps)
    raw = 50 + (avg-75)*3 - spread*2
    return float(np.clip(raw, 10, 99))

# ── 4) DASHBOARD ───────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)

    if not slugs:
        st.info("⚙️ Fetching outcome buckets…")
        continue

    yes_list = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]

    st.table({
        "Bucket Slug": slugs,
        "Live YES %":  [f"{v:.1f}%" for v in yes_list]
    })

    # safe max()
    best_i = max(range(len(yes_list)), key=lambda i: yes_list[i])
    best_slug, best_yes = slugs[best_i], yes_list[best_i]
    conf = get_conf(city)

    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_slug}`** @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")