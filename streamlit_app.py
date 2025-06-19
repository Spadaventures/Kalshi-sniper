import re, json, time
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh

# ── 0) CONFIG ──────────────────────────────────────────────────────────────────
st.set_page_config("🌡️ Daily Temp Sniper (Polling)", layout="centered")
st.title("🌡️ Daily Temp Sniper (LA, NYC, Miami)")
st.markdown("Automatically polls the market pages every 15 seconds for live YES %.")

# ── 1) YOUR MARKET PAGES ───────────────────────────────────────────────────────
MARKETS = {
    "Los Angeles (LAX)": "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "New York (Central Park)": "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "Miami (MIA)": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# ── 2) USER–AGENT FOR FULL SSR HTML ─────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0.0.0 Safari/537.36"
    )
}

# ── 3) SESSION STATE FOR LATEST PRICES ─────────────────────────────────────────
if "latest" not in st.session_state:
    st.session_state.latest = { city: {"yes": None, "updated": None} for city in MARKETS }

# ── 4) POLL FUNCTION ───────────────────────────────────────────────────────────
def poll_once():
    for city, url in MARKETS.items():
        try:
            # fetch full HTML
            html = requests.get(url, headers=HEADERS, timeout=10).text
            # extract the Next.js JSON blob
            m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html) \
                or re.search(r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?});', html)
            if not m:
                continue
            data = json.loads(m.group(1))
            # drill into market.outcomes
            outcomes = data["props"]["pageProps"]["market"]["outcomes"]
            # pick the highest-yes outcome
            best = max(outcomes, key=lambda o: o.get("yesPrice", 0))
            yes_pct = best.get("yesPrice", 0) * 100
            # store
            st.session_state.latest[city] = {
                "yes": yes_pct,
                "updated": time.strftime("%H:%M:%S")
            }
        except Exception:
            # ignore timeouts / parse errors
            pass

# ── 5) AUTO-REFRESH EVERY 15 SECONDS ────────────────────────────────────────────
count = st_autorefresh(interval=15_000, limit=None, key="poller")
poll_once()

# ── 6) DISPLAY ────────────────────────────────────────────────────────────────
rows = []
for city, info in st.session_state.latest.items():
    yes = info["yes"]
    rows.append({
        "City":      city,
        "YES %":     f"{yes:.1f}%" if yes is not None else "—",
        "Last Seen": info["updated"] or "—"
    })

st.table(rows)