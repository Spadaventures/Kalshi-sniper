import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

st.set_page_config(
    page_title="🌡️ 3-City Temp Sniper",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .block-container { max-width: 480px; margin: auto; padding: 1rem; }
  .stHeader { text-align: center; }
  .city { font-size: 1.2rem; margin-bottom: 0.25rem; }
  .pred { font-weight: bold; font-size: 1rem; }
  .conf { color: #2E86C1; }
</style>
""", unsafe_allow_html=True)

st.title("🌡️ 3-City Temp Sniper")
st.markdown("Live **best YES bid** for each highest-temp market, refreshed on load.")

TICKERS = st.secrets["KALSHI_TICKERS"]
BASE_URL = "https://kalshi.com/markets/{ticker}/"

@st.cache_data(ttl=30)
def fetch_yes_percentages(ticker: str):
    """Scrape Kalshi public page for the three ranges' YES %. Returns dict {range: yes_pct}."""
    url = BASE_URL.format(ticker=ticker)
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    html = r.text

    # find the three label/value pairs under "Make your prediction"
    # We'll use a regex to capture e.g. '76° to 77°  22% Yes'
    pattern = re.compile(r'(\d{1,2}°(?: to \d{1,2}°| or above))\D+?(\d{1,3})% Yes', re.IGNORECASE)
    matches = pattern.findall(html)

    # build dict
    out = {}
    for rng, pct in matches:
        out[rng] = float(pct)
    return out

def pick_best(preds: dict):
    """Given {range: pct}, return (best_range, best_pct)."""
    if not preds:
        return None, 0.0
    best = max(preds.items(), key=lambda kv: kv[1])
    return best  # (range, pct)

# Layout
for ticker in TICKERS:
    # map ticker → display name
    name = {
        "kxhighlax": "Los Angeles (KLAX)",
        "kxhighny": "New York (Central Park)",
        "kxhighmia": "Miami (KMIA)"
    }.get(ticker, ticker)

    st.markdown(f"#### {name}")
    try:
        yes_map = fetch_yes_percentages(ticker)
        best_range, best_pct = pick_best(yes_map)
        if best_range:
            st.markdown(f"- 🔮 **Bet on** `{best_range}`")
            st.markdown(f"- 📈 **Confidence**: <span class='conf'>{best_pct:.1f}%</span>", unsafe_allow_html=True)
        else:
            st.info("No YES bids currently available")
    except Exception as e:
        st.error(f"Error loading market: {e}")

st.markdown("---")
st.markdown("• Data cached 30 s • Source: Kalshi public pages")