import time
import jwt                     # PyJWT
import requests
import streamlit as st

# ───────── Streamlit page config ─────────
st.set_page_config(
    page_title="🌡️ 3-City Temp Sniper",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ───────── Secrets ─────────
OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]      # if you ever use it
KALSHI_KEY_ID      = st.secrets["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY = st.secrets["KALSHI_PRIVATE_KEY"]

# ───────── Markets ─────────
MARKETS = {
    "kxhighlax": "Los Angeles (KLAX)",
    "kxhighny":  "New York (Central Park)",
    "kxhighmia": "Miami (KMIA)",
}

# ───────── Helpers ─────────
def make_kalshi_jwt() -> str:
    """Generate a 60-second RS256 JWT for Kalshi REST calls."""
    now = int(time.time())
    payload = {"sub": KALSHI_KEY_ID, "iat": now, "exp": now + 60}
    return jwt.encode(payload, KALSHI_PRIVATE_KEY, algorithm="RS256")

@st.cache_data(ttl=30)
def fetch_yes_bids(market_ticker: str):
    """Fetch a one-off order-book snapshot and return the YES side levels."""
    token = make_kalshi_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Api-Key": KALSHI_KEY_ID
    }
    url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"
    resp = requests.get(url, headers=headers, timeout=5)
    resp.raise_for_status()
    # Kalshi returns {"msg": {...}}
    return resp.json().get("msg", {}).get("yes", [])

# ───────── UI ─────────
st.title("🌡️ 3-City Temp Sniper")
st.markdown("Live “best YES bid” for each highest-temp market, refreshed every 30 s.")

for ticker, desc in MARKETS.items():
    st.subheader(desc)
    try:
        yes_levels = fetch_yes_bids(ticker)
    except Exception as e:
        st.error(f"❌ Failed to fetch {ticker}: {e}")
        continue

    if not yes_levels:
        st.info("— no YES bids currently available —")
        continue

    # pick the highest bid price
    best_price, best_size = max(yes_levels, key=lambda lvl: lvl[0])
    st.markdown(f"""
**Best YES bid:** **{best_price:.1f}%**  
Contracts at that level: **{best_size}**  
👉 **Recommendation**: Bet YES on “highest temp ≥ strike” at **{best_price:.1f}%**
""")
    st.divider()

st.caption("Data via Kalshi REST snapshot (cached 30 s).")