import json, threading, textwrap
import numpy as np, requests, streamlit as st, websocket

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")

# Your three exact question strings
TARGET_QUESTIONS = {
    "LA":    "Highest temperature in Los Angeles Airport tomorrow?",
    "NYC":   "Highest temperature in Central Park, NYC tomorrow?",
    "MIAMI": "Highest temperature in Miami Int’l Airport tomorrow?",
}

# Open-Meteo ensemble coords
CITY_COORDS = {
    "LA":    (33.9425,  -118.4081),
    "NYC":   (40.7812,   -73.9665),
    "MIAMI": (25.7959,   -80.2870),
}

# Streaming URL for Kalshi’s public feed
WS_URL = "wss://stream.kalshi.com/v1/feed"  # ← Kalshi’s official events & price feed

# state
if "market_ids" not in st.session_state:
    st.session_state["market_ids"] = {}       # question -> id
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {}         # id -> yes%

# ── WEBSOCKET HANDLER ──────────────────────────────────────────────────────────
def on_message(ws, message):
    msg = json.loads(message)
    # --- 1) initial “Event” message with market definitions
    if "markets" in msg:
        for m in msg["markets"]:
            q = m.get("question")
            if q and q in TARGET_QUESTIONS.values():
                st.session_state["market_ids"][q] = m["id"]
                # now subscribe to its price updates:
                ws.send(json.dumps({
                    "action":    "subscribe",
                    "market_id": m["id"],
                    "channel":   "orderbook"   # or “prices” if supported
                }))
    # --- 2) orderbook / price update
    elif msg.get("channel") in ("orderbook","prices"):
        mid = msg.get("market_id")
        yes = msg.get("yes")
        if mid and yes is not None:
            st.session_state["live_yes"][mid] = float(yes)

def on_open(ws):
    # Kick off by subscribing to the master “all markets” feed
    ws.send(json.dumps({"action":"subscribe","channel":"markets"}))

def run_ws():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message
    )
    ws.run_forever()

# start in background
threading.Thread(target=run_ws, daemon=True).start()


# ── FORECAST SIGNAL ────────────────────────────────────────────────────────────
def fetch_ensemble_max(lat, lon):
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "models":        "gfs_ensemble_seamless,ecmwf_ifs_025",
        "daily":         "temperature_2m_max",
        "forecast_days": 1,
        "timezone":      "auto",
    }
    js    = requests.get(url, params=params, timeout=5).json()
    temps = js["daily"]["temperature_2m_max"]
    return round(float(np.mean(temps)),1), round(float(max(temps)-min(temps)),1)


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

# 1️⃣ Show live YES% & pick the top-priced bucket
cols = st.columns(3)
for (code, question), col in zip(TARGET_QUESTIONS.items(), cols):
    mid = st.session_state["market_ids"].get(question)
    yes = st.session_state["live_yes"].get(mid, 0.0) if mid else 0.0
    label = f"{code} → {yes:.1f}% YES" if mid else f"{code} → discovering…"
    col.metric(label, "")

# 2️⃣ Show GFS+ECMWF ensemble forecasts
st.subheader("Ensemble Forecasts")
cols = st.columns(3)
signals = {}
for code, question in TARGET_QUESTIONS.items():
    lat, lon = CITY_COORDS[code]
    avg, spread = fetch_ensemble_max(lat, lon)
    signals[code] = (avg, spread)
    cols[list(TARGET_QUESTIONS).index(code)].write(f"Avg max: {avg}°F | Spread: ±{spread}°F")

# 3️⃣ Simple “edge” recommendation
st.subheader("Edge Recommendation")
for code, question in TARGET_QUESTIONS.items():
    mid = st.session_state["market_ids"].get(question)
    yes = st.session_state["live_yes"].get(mid, 0.0) if mid else 0.0
    avg, spread = signals[code]
    conf = np.clip(50 + (avg-75)*3 - spread*2, 10, 99)
    side = "YES" if yes > conf else "NO"
    st.write(f"**{code}**: go **{side}** (live: {yes:.1f}% vs conf: {conf:.1f}%)")