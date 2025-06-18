import json
import threading
import textwrap

import numpy as np
import requests
import streamlit as st
from openai import OpenAI
import websocket  # pip install websocket-client

# ── APP CONFIG ─────────────────────────────────────────────────────────────────
st.set_page_config("Live 3-City Temp Sniper", layout="wide")
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
MODEL  = "gpt-4o"

# Exact Kalshi market names for the three “Highest temperature…” questions
CITY_MARKETS = {
    "LA":    "Highest temperature in Los Angeles Airport tomorrow?",
    "NYC":   "Highest temperature in Central Park, NYC tomorrow?",
    "MIAMI": "Highest temperature in Miami Int’l Airport tomorrow?",
}

# Geographic coordinates for each market (for Open-Meteo ensemble)
CITY_COORDS = {
    CITY_MARKETS["LA"]:    (33.9425,  -118.4081),
    CITY_MARKETS["NYC"]:   (40.7812,   -73.9665),
    CITY_MARKETS["MIAMI"]: (25.7959,   -80.2870),
}

# Initialize live‐YES% storage
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {m: None for m in CITY_MARKETS.values()}


# ── WEBSOCKET CLIENT (no REST-API keys needed) ─────────────────────────────────
def on_ws_message(ws, message):
    """Handle incoming JSON messages: {'market': ..., 'yes': ...}."""
    try:
        data = json.loads(message)
        m = data.get("market")
        y = data.get("yes")
        if m in st.session_state["live_yes"]:
            st.session_state["live_yes"][m] = float(y)
            # auto-alert if our last_conf beats the live price
            conf = st.session_state.get("last_conf", 0.0)
            if conf and conf > y:
                st.toast(f"🚨 Edge on {m}: conf {conf:.1f}% > market {y:.1f}%")
    except Exception:
        pass

def on_ws_open(ws):
    """Subscribe to the three weather markets as soon as WS opens."""
    for market in st.session_state["live_yes"].keys():
        ws.send(json.dumps({"action": "subscribe", "market": market}))

def start_ws():
    ws = websocket.WebSocketApp(
        "wss://your-kalshi-websocket-endpoint",  # ← replace with Kalshi's real WS URL
        on_open=on_ws_open,
        on_message=on_ws_message,
    )
    ws.run_forever()

# run WebSocket in background
threading.Thread(target=start_ws, daemon=True).start()


# ── ENSEMBLE FORECAST FETCHER ───────────────────────────────────────────────────
def fetch_ensemble_max(lat, lon):
    """
    Pulls today’s max-temperature ensemble from GFS & ECMWF via Open-Meteo.
    Returns (avg_max_F, spread_F).
    """
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "models":        "gfs_ensemble_seamless,ecmwf_ifs_025",
        "daily":         "temperature_2m_max",
        "forecast_days": 1,
        "timezone":      "auto",
    }
    js = requests.get(url, params=params, timeout=5).json()
    temps = js["daily"]["temperature_2m_max"]  # one entry per ensemble member
    avg    = round(float(np.mean(temps)), 1)
    spread = round(float(max(temps) - min(temps)), 1)
    return avg, spread


# ── GPT PICKER ─────────────────────────────────────────────────────────────────
def ask_gpt(market, summary, conf, yes_pct):
    """Ask GPT which side to take based on our confidence vs live price."""
    st.session_state["last_conf"] = conf
    prompt = textwrap.dedent(f"""
        Market: {market}
        Signals: {summary}
        Blended confidence: {conf:.1f}%.
        Live market YES%: {yes_pct:.1f}%.
        Should I go YES? 
        Output exactly: Side / Probability.
    """).strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Be concise — just Side and Probability."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=20,
    )
    return resp.choices[0].message.content.strip()


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
st.title("🌡️ Live 3-City Temp Sniper")

# 1) Live YES% metrics
cols = st.columns(3)
for (code, market), col in zip(CITY_MARKETS.items(), cols):
    yes = st.session_state["live_yes"][market] or 0.0
    col.metric(f"{code} Live YES%", f"{yes:.1f}%")

# 2) Automatic ensemble forecasts
st.subheader("GFS+ECMWF Ensemble Forecasts")
signals = {}
cols    = st.columns(3)
for (code, market), col in zip(CITY_MARKETS.items(), cols):
    lat, lon       = CITY_COORDS[market]
    avg, spread    = fetch_ensemble_max(lat, lon)
    signals[market] = {"avg": avg, "spread": spread}
    col.write(f"Avg max: {avg}°F  |  Spread: ±{spread}°F")

# 3) Automated GPT picks
st.subheader("Automated Picks")
for code, market in CITY_MARKETS.items():
    sig    = signals[market]
    raw    = 50 + (sig["avg"] - 75) * 3 - sig["spread"] * 2
    conf   = float(np.clip(raw, 10, 99))
    yes_pct= st.session_state["live_yes"][market] or 0.0
    summary= f"Ensemble avg {sig['avg']}°±{sig['spread']}"
    pick   = ask_gpt(market, summary, conf, yes_pct)
    st.markdown(f"**{code}** → {pick}  _(Conf: {conf:.1f}%)_")