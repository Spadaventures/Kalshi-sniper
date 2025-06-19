# streamlit_app.py

import re, json, time
import requests
import numpy as np
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# 0) PAGE CONFIG
st.set_page_config("🌡️ Daily Temp Sniper", layout="centered")
st.title("🌡️ Daily Temp Sniper (LA, NYC, Miami)")
st.markdown("Auto-refresh every 15 s: live YES % for each temperature range, plus a recommendation + confidence.")

# 1) MARKETS & COORDS
MARKET_URLS = {
    "Los Angeles (LAX)": "https://kalshi.com/markets/kxhighlax/highest-temperature-in-los-angeles#kxhighlax-25jun19",
    "New York (Central Park)": "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc#kxhighny-25jun19",
    "Miami (MIA)": "https://kalshi.com/markets/kxhighmia/highest-temperature-in-miami#kxhighmia-25jun19",
}
COORDS = {
    "Los Angeles (LAX)":        (33.9425,  -118.4081),
    "New York (Central Park)":  (40.7812,   -73.9665),
    "Miami (MIA)":              (25.7959,   -80.2870),
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115 Safari/537.36"
    )
}

# 2) STATE
if "results" not in st.session_state:
    st.session_state.results = {
        city: {
            "buckets": [],   # [(label, yes%)]
            "best":    None, # (label, yes%)
            "conf":    50.0, # confidence %
            "ts":      ""
        }
        for city in MARKET_URLS
    }

# 3) POLL + PARSE OUTCOMES
def poll_markets():
    for city, url in MARKET_URLS.items():
        try:
            html = requests.get(url, headers=HEADERS, timeout=10).text
            # grab Next.js JSON
            m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html) \
                or re.search(r'window\.__NEXT_DATA__\s*=\s*({[\s\S]+?});', html)
            if not m:
                continue
            nd = json.loads(m.group(1))
            outcomes = nd["props"]["pageProps"]["market"]["outcomes"]
            buckets = []
            for o in outcomes:
                label = o.get("title") or o.get("slug")
                yes    = float(o.get("yesPrice",0.0)) * 100
                buckets.append((label, yes))
            # determine best
            best = max(buckets, key=lambda x: x[1])
            # compute confidence via ensemble API
            lat, lon = COORDS[city]
            resp = requests.get(
                "https://ensemble-api.open-meteo.com/v1/ensemble",
                params={
                    "latitude":lat, "longitude":lon,
                    "models":"gfs_ensemble_seamless,ecmwf_ifs_025",
                    "daily":"temperature_2m_max",
                    "forecast_days":1,
                    "timezone":"auto"
                }, timeout=5
            ).json()
            temps = resp.get("daily",{}).get("temperature_2m_max", [])
            if temps:
                avg = np.mean(temps)
                spread = max(temps)-min(temps)
                raw = 50 + (avg-75)*3 - spread*2
                conf = float(np.clip(raw, 10, 99))
            else:
                conf = 50.0

            # save
            st.session_state.results[city] = {
                "buckets": buckets,
                "best":    best,
                "conf":    conf,
                "ts":      time.strftime("%H:%M:%S")
            }
        except Exception:
            # swallow parse/fetch errors
            pass

# 4) AUTO-REFRESH + POLL
st_autorefresh(interval=15_000, limit=None, key="poller")
poll_markets()

# 5) DISPLAY TABLES + RECOMMENDATION
for city, info in st.session_state.results.items():
    st.subheader(f"{city}  (updated {info['ts'] or '—'})")

    # show all range buckets
    st.table([{"Range": r, "YES %": f"{y:.1f}%"} for r,y in info["buckets"]])

    # recommendation
    if info["best"]:
        label, yes = info["best"]
        conf = info["conf"]
        if yes > conf:
            st.markdown(f"🔮 **Back “{label}”** @ **{yes:.1f}%**  •  📈 **Confidence: {conf:.1f}%**")
        else:
            st.markdown(f"⚠️ No edge — best “{label}” @ {yes:.1f}% vs Conf {conf:.1f}%")
    else:
        st.info("Waiting for data…")