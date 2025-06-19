import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

# ─── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🌡️ 3-City Temp Sniper",
    layout="centered",
)

st.title("🌡️ 3-City Temp Sniper")
st.markdown("Live **Bet Recommendation** for daily highest-temp markets (auto-refresh every time you hit Refresh).")

# ─── Load your three tickers from secrets ────────────────────────────────────────
TICKERS = st.secrets["KALSHI_TICKERS"]  # e.g. ["kxhighlax","kxhighny","kxhighmia"]
NAME_MAP = {
    "kxhighlax": "Los Angeles (KLAX)",
    "kxhighny":  "New York (Central Park)",
    "kxhighmia": "Miami (KMIA)",
}

def fetch_yes_percentages(ticker: str) -> dict[str, float]:
    """
    Scrape Kalshi public market page to extract each outcome's best YES-bid %
    Returns a dict mapping "74° to 75°" → 33.7, etc.
    """
    url = f"https://kalshi.com/markets/{ticker}"
    resp = requests.get(url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        raise RuntimeError("Could not find Next.js data blob on page")

    data = json.loads(script.string)
    outcomes = data["props"]["pageProps"]["market"]["outcomes"]
    yes_map: dict[str, float] = {}

    for o in outcomes:
        label = o.get("name")             # e.g. "78° or above"
        best_bid = o.get("bestBid")       # a float between 0 and 1
        if label and isinstance(best_bid, (float, int)):
            yes_map[label] = best_bid * 100

    return yes_map

def pick_best(yes_map: dict[str, float]) -> tuple[str, float]:
    """
    From outcome→pct, returns (best_outcome, best_pct).
    If empty, returns (None, 0.0).
    """
    if not yes_map:
        return None, 0.0
    best_label, best_pct = max(yes_map.items(), key=lambda kv: kv[1])
    return best_label, best_pct

# ─── Main display loop ─────────────────────────────────────────────────────────
for ticker in TICKERS:
    display_name = NAME_MAP.get(ticker, ticker)
    st.header(display_name)

    try:
        yes_map = fetch_yes_percentages(ticker)
        best_label, best_pct = pick_best(yes_map)

        if best_label:
            st.markdown(f"- 🔮 **Bet on** `{best_label}`")
            st.markdown(f"- 📈 **Confidence**: **{best_pct:.1f}%**")
        else:
            st.info("No YES bids available right now")

    except Exception as e:
        st.error(f"Error fetching {ticker}: {e}")