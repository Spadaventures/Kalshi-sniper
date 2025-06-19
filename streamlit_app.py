import re, json, threading
import numpy as np, requests, streamlit as st, websocket

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# Parent-market URLs (exactly as you pasted)
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# Coords for ensemble confidence
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

WS_URL = "wss://stream.kalshi.com/v1/feed"

# In‐memory stores
if "outcome_slugs" not in st.session_state:
    st.session_state["outcome_slugs"] = {}
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}

# ── DISCOVER OUTCOME SLUGS ──────────────────────────────────────────────────────
def discover_outcomes(url):
    """
    Fetch the parent URL HTML and regex out all <a href="/markets/SLUG"> links,
    then filter for those starting with the parent-slug + '-'.
    """
    parent_slug = url.split("/markets/")[1].split("#")[0]
    html = requests.get(url, timeout=5).text
    candidates = set(re.findall(r'href="/markets/([^"/]+)"', html))
    outcomes  = sorted(
        s for s in candidates
        if s.startswith(parent_slug + "-")
    )
    # init live_yes storage
    for s in outcomes:
        st.session_state["live_yes"].setdefault(s, 0.0)
    return outcomes

# perform discovery once
for code, url in PARENT_URLS.items():
    if code not in st.session_state["outcome_slugs"]:
        st.session_state["outcome_slugs"][code] = discover_outcomes(url)


# ── WEBSOCKET HANDLER ──────────────────────────────────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)
    if msg.get("channel") == "prices" and "market" in msg and "yes" in msg:
        st.session_state["live_yes"][msg["market"]] = float(msg["yes"])

def on_open(ws):
    # subscribe to every discovered slug
    for slugs in st.session_state["outcome_slugs"].values():
        for slug in slugs:
            ws.send(json.dumps({
                "action":    "subscribe",
                "channel":   "prices",
                "market":    slug
            }))

def run_ws():
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
    ws.run_forever()

threading.Thread(target=run_ws, daemon=True).start()


# ── ENSEMBLE CONFIDENCE ────────────────────────────────────────────────────────
def fetch_confidence(code):
    lat, lon = COORDS[code]
    try:
        resp = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude":lat, "longitude":lon,
                "models":"gfs_ensemble_seamless,ecmwf_ifs_025",
                "daily":"temperature_2m_max","forecast_days":1,"timezone":"auto"
            }, timeout=5
        ).json()
        temps = resp["daily"]["temperature_2m_max"]
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


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for code, slugs in st.session_state["outcome_slugs"].items():
    st.subheader(code)

    # build table of outcome vs live YES%
    yes_vals = [st.session_state["live_yes"].get(s, 0.0) for s in slugs]
    st.table({
        "Range":      slugs,
        "Live YES %": [f"{v:.1f}%" for v in yes_vals]
    })

    # pick the one with max YES
    idx, best = int(np.argmax(yes_vals)), max(yes_vals)
    best_slug  = slugs[idx]

    conf = fetch_confidence(code)
    if best > conf:
        st.markdown(f"👉 **Back `{best_slug}`** at **{best:.1f}%** (conf {conf:.1f}%)")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best:.1f}% vs conf {conf:.1f}%")