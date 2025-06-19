import streamlit as st
import threading, time, json, requests
from websocket import WebSocketApp
import jwt  # PyJWT

# ───────── Secrets ─────────
OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]
KALSHI_KEY_ID      = st.secrets["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY = st.secrets["KALSHI_PRIVATE_KEY"]

# ───────── Markets ─────────
MARKETS = {
    "kxhighlax": "Los Angeles", 
    "kxhighny": "New York",   
    "kxhighmia": "Miami"      
}
orderbooks = {}  # ticker -> {"yes": [...], "no": [...]}

def make_jwt():
    now = int(time.time())
    payload = {"sub": KALSHI_KEY_ID, "iat": now, "exp": now + 60}
    # returns a str in PyJWT≥2.x
    return jwt.encode(payload, KALSHI_PRIVATE_KEY, algorithm="RS256")

def subscribe_cmd(cmd_id, channel, tickers):
    return {
        "id": cmd_id,
        "cmd": "subscribe",
        "params": {"channels":[channel], "market_tickers": tickers}
    }

def on_open(ws):
    ws.send(json.dumps(subscribe_cmd(1, "orderbook_delta", list(MARKETS.keys()))))

def on_message(ws, raw):
    msg = json.loads(raw)
    t   = msg.get("type")
    if t in ("orderbook_snapshot","orderbook_delta"):
        mt = msg["msg"]["market_ticker"]
        if t=="orderbook_snapshot" or mt not in orderbooks:
            orderbooks[mt] = {"yes":[], "no":[]}
        if t=="orderbook_snapshot":
            orderbooks[mt]["yes"] = msg["msg"].get("yes",[])
            orderbooks[mt]["no"]  = msg["msg"].get("no",[])
        else:
            side, price, delta = msg["msg"]["side"], msg["msg"]["price"], msg["msg"]["delta"]
            lvl = {p:c for p,c in orderbooks[mt][side]}
            lvl[price] = lvl.get(price,0) + delta
            # rebuild sorted
            orderbooks[mt][side] = sorted([[p,c] for p,c in lvl.items() if c>0], key=lambda x:x[0])

def on_error(ws, err):
    st.error(f"WS error: {err}")

def on_close(ws, code, reason):
    st.warning("WS closed")

def run_ws():
    token = make_jwt()
    headers = [
        f"Authorization: Bearer {token}",
        f"X-Api-Key: {KALSHI_KEY_ID}"
    ]
    ws = WebSocketApp(
        "wss://api.elections.kalshi.com/trade-api/ws/v2",
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

# ───────── Start WebSocket thread ─────────
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
    yes_offers = ob["yes"]
    if not yes_offers:
        st.write("No YES offers yet.")
        continue
    # pick the highest % price
    best_price, size = max(yes_offers, key=lambda x: x[0])
    st.markdown(f"""
**Best YES bid:** **{best_price:.1f}%**  
Contracts: {size}  
👉 **Recommendation:** Bet YES on “highest temp ≥ strike” at **{best_price:.1f}%**
""")
    st.divider()

st.caption("Live via Kalshi WS orderbook_delta")