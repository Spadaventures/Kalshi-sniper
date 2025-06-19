# streamlit_app.py

import re, json, threading
import numpy as np, requests, streamlit as st, websocket

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# The three “parent” market URLs (exactly as on Kalshi)
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

# Public Kalshi WS URL
WS_URL = "wss://stream.kalshi.com/v1/feed"

# In-memory storage
if "outcomes" not in st.session_state:
    st.session_state["outcomes"] = {}      # city -> list of slugs
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}      # slug -> yes%

# ── 1) SCRAPE each parent page for its 3 outcome-slugs ──────────────────────────
def discover(city, url):
    slug = url.split("/markets/")[1].split("#")[0]
    html = requests.get(url, timeout=5).text
    cand = set(re.findall(r'href="/markets/([^"/]+)"', html))
    outs = sorted(s for s in cand if s.startswith(slug + "-"))
    # init live_yes
    for s in outs:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return outs

for city, url in PARENTS.items():
    if city not in st.session_state["outcomes"]:
        st.session_state["outcomes"][city] = discover(city, url)

# ── 2) WEBSOCKET to pull live YES% per-outcome ─────────────────────────────────
def on_msg(ws, msg):
    j = json.loads(msg)
    if j.get("channel") == "prices" and "market" in j and "yes" in j:
        st.session_state["live_yes"][j["market"]] = float(j["yes"])

def on_open(ws):
    # subscribe to each discovered slug
    for slugs in st.session_state["outcomes"].values():
        for s in slugs:
            ws.send(json.dumps({"action":"subscribe","channel":"prices","market":s}))

def ws_thread():
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_msg)
    ws.run_forever()

threading.Thread(target=ws_thread, daemon=True).start()

# ── 3) ENSEMBLE CONFIDENCE (Open-Meteo, no key needed) ─────────────────────────
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
    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg - 75)*3 - spread*2
    return float(np.clip(raw,10,99))

# ── 4) DASHBOARD ───────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for city, slugs in st.session_state["outcomes"].items():
    st.subheader(city)
    yes_list = [st.session_state["live_yes"][s] for s in slugs]
    # show table
    st.table({
      "Range (slug)": slugs,
      "Live YES %":  [f"{v:.1f}%" for v in yes_list]
    })
    # pick best
    idx      = max(range(len(yes_list)), key=lambda i: yes_list[i])
    best_s   = slugs[idx]
    best_yes = yes_list[idx]
    conf     = get_conf(city)
    if best_yes > conf:
        st.markdown(f"👉 **Back `{best_s}`** @ **{best_yes:.1f}%**  (Conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_s}` @ {best_yes:.1f}% vs Conf {conf:.1f}%")