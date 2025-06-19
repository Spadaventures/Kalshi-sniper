# streamlit_app.py
import streamlit as st
import threading, time, json, logging
from datetime import datetime
import websocket, requests

st.set_page_config(page_title="🌡️ Live 3-City Temp Sniper", layout="centered")
st.title("🌡️ Live 3-City Temp Sniper")
st.markdown("Streaming `YES%` for daily high-temp markets in LA, NYC, Miami.")

# CONFIG
SLUGS    = {
    "Los Angeles": "kxhighlax-25jun19",
    "New York"   : "kxhighny-25jun19",
    "Miami"      : "kxhighmia-25jun19"
}
WS_URL   = "wss://stream.kalshi.com/v1/feed"
REST_URL = "https://trading-api.kalshi.com/trade-api/v2/markets"

# In-memory store
store = { city: {"yes": None, "method": None, "ts": None} for city in SLUGS }

# Logging
logging.basicConfig(level=logging.WARNING)

def log_and_store(city, yes_pct, method):
    store[city].update({
        "yes": yes_pct,
        "method": method,
        "ts": datetime.utcnow().strftime("%H:%M:%S")
    })

# WebSocket Callbacks
def on_open(ws):
    for slug in SLUGS.values():
        ws.send(json.dumps({"action":"subscribe","channel":"prices","market":slug}))

def on_message(ws, raw):
    msg = json.loads(raw)
    if msg.get("channel")=="prices" and msg.get("market") in SLUGS.values():
        # reverse‐lookup city name
        city = next(k for k,v in SLUGS.items() if v==msg["market"])
        yes_pct = float(msg.get("yes",0))
        log_and_store(city, yes_pct, "WS")

def on_error(ws, err): pass
def on_close(ws, *args): pass

# Poll fallback
def poll_loop():
    while True:
        for city,slug in SLUGS.items():
            try:
                r = requests.get(f"{REST_URL}/{slug}")
                j = r.json()
                yes_pct = float(j["prices"]["yes"])
                log_and_store(city, yes_pct, "POLL")
            except Exception:
                pass
        time.sleep(30)

# Start background threads once
if "started" not in st.session_state:
    st.session_state.started = True
    # WS
    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    threading.Thread(target=ws.run_forever, daemon=True).start()
    # Poll
    threading.Thread(target=poll_loop, daemon=True).start()

# UI table
df = []
for city, data in store.items():
    df.append({
        "City": city,
        "YES %": f"{data['yes']:.1f}%" if data["yes"] is not None else "…",
        "Source": data["method"] or "…",
        "Updated": data["ts"] or "…"
    })
st.table(df)