import json, threading, textwrap
import numpy as np, requests, streamlit as st, websocket

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# Your three exact Kalshi questions
QUESTIONS = {
    "LA":    "Highest temperature in Los Angeles Airport tomorrow?",
    "NYC":   "Highest temperature in Central Park, NYC tomorrow?",
    "MIAMI": "Highest temperature in Miami Int’l Airport tomorrow?",
}

# Coords for ensemble forecast (Open-Meteo)
COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

# Public Kalshi WS endpoint
WS_URL = "wss://stream.kalshi.com/v1/feed"

# Storage for discovered markets & live prices
if "markets" not in st.session_state:
    st.session_state["markets"] = {code: [] for code in QUESTIONS}
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}   # market_id -> yes%

# ── WEBSOCKET CALLBACKS ─────────────────────────────────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)

    # 1) initial market definitions
    if "markets" in msg:
        for m in msg["markets"]:
            q = m.get("question")
            # match our three questions
            for code, text in QUESTIONS.items():
                if q == text:
                    st.session_state["markets"][code].append({
                        "id":      m["id"],
                        "outcome": m["outcome"]
                    })
                    # subscribe to price for that outcome
                    ws.send(json.dumps({
                        "action":    "subscribe",
                        "channel":   "prices",
                        "market_id": m["id"]
                    }))

    # 2) price update
    if msg.get("channel") == "prices" and "yes" in msg:
        mid = msg["market_id"]
        st.session_state["live_yes"][mid] = float(msg["yes"])

def on_open(ws):
    # kick off market discovery
    ws.send(json.dumps({"action":"subscribe","channel":"markets"}))

def run_ws():
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
    ws.run_forever()

threading.Thread(target=run_ws, daemon=True).start()

# ── FORECAST CONFIDENCE ────────────────────────────────────────────────────────
def fetch_confidence(code):
    lat, lon = COORDS[code]
    # try open-meteo ensemble
    try:
        resp = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
              "latitude":lat, "longitude":lon,
              "models":"gfs_ensemble_seamless,ecmwf_ifs_025",
              "daily":"temperature_2m_max","forecast_days":1,"timezone":"auto"
            },timeout=5
        ).json()
        temps = resp["daily"]["temperature_2m_max"]
    except Exception:
        # fallback to OpenWeather 8×3h forecast
        ow = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}"
            f"&appid={st.secrets['WEATHER_API_KEY']}&units=imperial",
            timeout=5
        ).json()
        temps = [e["main"]["temp_max"] for e in ow.get("list",[])[:8]]
    if not temps:
        return 50.0
    avg    = np.mean(temps)
    spread = max(temps) - min(temps)
    raw    = 50 + (avg-75)*3 - spread*2
    return float(np.clip(raw, 10, 99))

# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

for code in QUESTIONS:
    st.subheader(code)
    markets = st.session_state["markets"][code]
    if not markets:
        st.info("Discovering markets…")
        continue

    # build list of (outcome, yes%)
    rows = []
    best = (None, -1.0)  # (outcome, yes%)
    for m in markets:
        yes = st.session_state["live_yes"].get(m["id"], 0.0)
        rows.append((m["outcome"], yes))
        if yes > best[1]:
            best = (m["outcome"], yes)

    # compute our confidence
    conf = fetch_confidence(code)

    # display table
    st.table({
      "Range":        [r[0] for r in rows],
      "Live YES %":   [f"{r[1]:.1f}%" for r in rows]
    })

    # recommendation
    st.markdown(f"**→ Back:** `{best[0]}`  |  **Live YES%:** {best[1]:.1f}%  |  **Conf:** {conf:.1f}%")