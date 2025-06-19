import re, json, threading
import numpy as np
import streamlit as st
import cloudscraper                # pip install cloudscraper
import websocket                   # pip install websocket-client

# ────── 0) PAGE CONFIG ───────────────────────────────────────────
st.set_page_config(
    page_title="🌡️ Live 3-City Temp Sniper",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("🌡️ Live 3-City Temp Sniper")

# ────── 1) MARKET URLS ────────────────────────────────────────────
PARENT_URLS = {
    "LA":    "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "NYC":   "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "MIAMI": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}

# ────── 2) WS FEED & STATE ─────────────────────────────────────────
WS_URL = "wss://stream.kalshi.com/v1/feed"
if "outcomes" not in st.session_state:
    st.session_state.outcomes = {}    # city → [slug,…]
if "live_yes" not in st.session_state:
    st.session_state.live_yes = {}    # slug → latest yes%

# ────── 3) SLUG DISCOVERY with cloudscraper ────────────────────────
scraper = cloudscraper.create_scraper(
    browser={"custom": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/115 Safari/537.36"}
)

def discover_slugs(city, url):
    """Fetch the page, extract __NEXT_DATA__ JSON, back out outcomes[].slug."""
    try:
        # force www + desktop UA
        url2 = url.replace("://kalshi.com", "://www.kalshi.com")
        html = scraper.get(url2, timeout=20).text
    except Exception as e:
        st.error(f"❌ Unable to fetch {url2}: {e}")
        return []

    # three regex fallbacks in order:
    patterns = [
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>',
        r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?});',
        r'<script>window\.__NEXT_DATA__\s*=\s*({[\s\S]+?});?</script>'
    ]
    nd_json = None
    for p in patterns:
        m = re.search(p, html)
        if m:
            nd_json = m.group(1)
            break

    if not nd_json:
        st.error(f"❌ Could not find NEXT_DATA JSON on page for {city}.")
        return []

    try:
        nd = json.loads(nd_json)
        market = nd["props"]["pageProps"]["market"]
        slugs  = [o["slug"] for o in market.get("outcomes", []) if "slug" in o]
    except Exception as e:
        st.error(f"❌ JSON parse error for {city}: {e}")
        return []

    # init live_yes
    for s in slugs:
        st.session_state.live_yes.setdefault(s, 0.0)
    return slugs

# run it once
for city, url in PARENT_URLS.items():
    if city not in st.session_state.outcomes:
        st.session_state.outcomes[city] = discover_slugs(city, url)

# ────── 4) WEBSOCKET SUBSCRIBE ──────────────────────────────────────
def _on_message(ws, raw):
    msg = json.loads(raw)
    if msg.get("channel")=="prices" and "market" in msg and "yes" in msg:
        st.session_state.live_yes[msg["market"]] = float(msg["yes"])

def _on_open(ws):
    for slugs in st.session_state.outcomes.values():
        for slug in slugs:
            ws.send(json.dumps({
                "action":"subscribe","channel":"prices","market":slug
            }))

def _start_ws():
    ws = websocket.WebSocketApp(WS_URL,
        on_open=_on_open,
        on_message=_on_message
    )
    ws.run_forever()

threading.Thread(target=_start_ws, daemon=True).start()

# ────── 5) DASHBOARD RENDER ────────────────────────────────────────
for city, slugs in st.session_state.outcomes.items():
    st.subheader(city)
    if not slugs:
        st.info("⚙️ Fetching outcome buckets…")
        continue

    yes_vals = [st.session_state.live_yes.get(s,0.0) for s in slugs]
    table = {
        "Bucket Slug": slugs,
        "Live YES %":  [f"{v:.1f}%" for v in yes_vals],
    }
    st.table(table)

    # pick max yes%
    best_i   = max(range(len(yes_vals)), key=lambda i: yes_vals[i])
    best_slug= slugs[best_i]
    best_yes = yes_vals[best_i]

    # simple 50% threshold edge
    if best_yes > 50:
        st.markdown(f"👉 **Back `{best_slug}`** @ **{best_yes:.1f}%**")
    else:
        st.markdown(f"❌ No edge: best `{best_slug}` @ {best_yes:.1f}%")