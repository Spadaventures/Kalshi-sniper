import streamlit as st
import threading, json, websocket, requests
from datetime import datetime

# ───────── Secrets ─────────
OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]
KALSHI_KEY_ID      = st.secrets["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY = st.secrets["KALSHI_PRIVATE_KEY"]

# ───────── Markets & Mapping ─────────
MARKETS = {
    "kxhighlax": "Los Angeles",    # KLAX
    "kxhighny": "New York",        # Central Park
    "kxhighmia": "Miami"           # MIA
}

orderbooks = {}  # market_ticker -> {"yes": [[price, size], ...], "no": [...]}

def subscribe_cmd(cmd_id, channel, tickers):
    return {
        "id": cmd_id,
        "cmd": "subscribe",
        "params": {
            "channels": [channel],
            "market_tickers": tickers
        }
    }

# ───────── Kalshi WS Handlers ─────────
def on_open(ws):
    ws.send(json.dumps(subscribe_cmd(1, "orderbook_delta", list(MARKETS.keys()))))

def on_message(ws, raw):
    msg = json.loads(raw)
    t = msg.get("type")
    if t in ("orderbook_snapshot", "orderbook_delta"):
        mt = msg["msg"]["market_ticker"]
        if t == "orderbook_snapshot" or mt not in orderbooks:
            orderbooks[mt] = {"yes": [], "no": []}
        if t == "orderbook_snapshot":
            orderbooks[mt]["yes"] = msg["msg"].get("yes", [])
            orderbooks[mt]["no"]  = msg["msg"].get("no", [])
        else:
            side  = msg["msg"]["side"]
            price = msg["msg"]["price"]
            delta = msg["msg"]["delta"]
            lvl = {p:c for p,c in orderbooks[mt][side]}
            lvl[price] = lvl.get(price, 0) + delta
            orderbooks[mt][side] = sorted(
                [[p,c] for p,c in lvl.items() if c>0],
                key=lambda x: x[0]
            )

def on_error(ws, err):
    st.error(f"WebSocket error: {err}")

def on_close(ws, code, reason):
    st.warning("Kalshi WS connection closed")

def run_ws():
    ws = websocket.WebSocketApp(
        "wss://api.elections.kalshi.com/trade-api/ws/v2",
        header={"X-Api-Key": KALSHI_KEY_ID},
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

# ───────── Start WS Thread ─────────
if "ws_started" not in st.session_state:
    threading.Thread(target=run_ws, daemon=True).start()
    st.session_state.ws_started = True

# ───────── Streamlit UI ─────────
st.title("🌡️ 3-City Temp Sniper")

for ticker, city in MARKETS.items():
    st.subheader(f"{city} ({ticker})")
    ob = orderbooks.get(ticker)
    if not ob:
        st.write("Loading order book…")
        continue
    yes_ladder = ob["yes"]
    if not yes_ladder:
        st.write("No YES offers yet.")
        continue

    # pick highest price level
    best_price, size = max(yes_ladder, key=lambda x: x[0])
    prob = best_price  # price already 1–99

    st.markdown(f"""
    **Best YES bid:** **{prob:.1f}%**  
    Contracts at that level: {size}

    👉 **Recommendation:** Bet **YES** on “highest temp ≥ strike” at **{prob:.1f}%**
    """)
    st.divider()

st.caption("Live data via Kalshi WebSocket orderbook_delta channel.")