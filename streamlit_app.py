# streamlit_app.py

import streamlit as st
import textwrap
import time
import threading
import websocket
import requests
import json
import csv
import pandas as pd
from datetime import datetime
from PIL import Image
import io
import pytesseract
import openai
from openai import OpenAI

# ============ PAGE CONFIG ============
st.set_page_config(page_title="Kalshi Sniper", layout="wide", initial_sidebar_state="expanded")

# ============ SECRETS & CLIENT SETUP ============
# OpenAI
openai.api_key = st.secrets["OPENAI_API_KEY"]
client = OpenAI(api_key=openai.api_key)
MODEL_NAME = "gpt-4o"

# Weather APIs
OPENWEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY      = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY  = st.secrets["TOMORROWIO_API_KEY"]

# Kalshi JWT credentials
_KID_raw = st.secrets["KALSHI_KEY_ID"]
_KEY_raw = st.secrets["KALSHI_PRIVATE_KEY"]
KALSHI_KEY_ID      = _KID_raw.strip()
KALSHI_PRIVATE_KEY = textwrap.dedent(_KEY_raw).strip()

# ============ JWT HELPER ============
def get_kalshi_bearer_token() -> str:
    now = int(time.time())
    payload = {"iss": KALSHI_KEY_ID, "iat": now, "exp": now + 600}
    return jwt.encode(payload, KALSHI_PRIVATE_KEY, algorithm="RS256")

# ============ LIVE WEBSOCKET FEED ============
st.sidebar.header("🔄 Live Weather Markets")
latest = st.sidebar.empty()
WS_URL = "wss://trade-api.kalshi.com/ws/markets"

def on_msg(ws, msg):
    data = json.loads(msg)
    for m in data.get("markets", []):
        if any(w in m["ticker"].lower() for w in ("temperature","rain")):
            latest.markdown(f"**{m['ticker']}** — Yes: {m.get('yes_price')} | No: {m.get('no_price')}")

def on_err(ws, e):
    latest.error(f"WS Error: {e}")

def on_close(ws, _):
    latest.warning("WebSocket closed")

def start_ws():
    if not (KALSHI_KEY_ID and KALSHI_PRIVATE_KEY):
        latest.info("🔒 Add Kalshi secrets in `.streamlit/secrets.toml` to enable live feed.")
        return
    bearer = get_kalshi_bearer_token()
    headers = [
        f"Authorization: Bearer {bearer}",
        f"X-Api-Key: {KALSHI_KEY_ID}"
    ]
    ws = websocket.WebSocketApp(
        WS_URL,
        header=headers,
        on_message=on_msg,
        on_error=on_err,
        on_close=on_close
    )
    ws.run_forever()

threading.Thread(target=start_ws, daemon=True).start()

# ============ FETCH DAILY WEATHER MARKETS ============
@st.cache_data(ttl=300)
def fetch_daily_weather_markets():
    if not (KALSHI_KEY_ID and KALSHI_PRIVATE_KEY):
        return pd.DataFrame()
    bearer = get_kalshi_bearer_token()
    headers = {"Authorization": f"Bearer {bearer}", "X-Api-Key": KALSHI_KEY_ID}
    resp = requests.get("https://trading-api.kalshi.com/trade-api/v2/markets", headers=headers).json()
    rows = []
    for m in resp.get("markets", []):
        if m.get("resolution") == "DAILY" and any(w in m["ticker"].lower() for w in ("temperature","rain")):
            yes_pct = float(m.get("yes_price", 0.0)) * 100
            rows.append({
                "question": m["question"],
                "ticker":   m["ticker"],
                "yes_pct":  yes_pct,
                "expires":  m.get("expiration_time")
            })
    return pd.DataFrame(rows).sort_values("yes_pct", ascending=False)

# ============ HISTORICAL TEMPS ============
@st.cache_data
def load_historical_temps():
    try:
        with open("historical_temps.csv", newline="") as f:
            return list(csv.DictReader(f))
    except:
        return []

historical_data = load_historical_temps()

def get_historical_temp(city: str):
    temps = [float(r["temp"]) for r in historical_data if r["city"].lower() == city.lower()]
    return sum(temps)/len(temps) if temps else None

# ============ HELPERS ============
def extract_city(text: str) -> str:
    for c in ["NYC","New York","Miami","Denver","Chicago","Austin","LA","Los Angeles"]:
        if c.lower() in text.lower():
            return c
    return ""

def calc_hours_until_event() -> float:
    now = datetime.now()
    eod = datetime.combine(now.date(), datetime.max.time())
    return (eod - now).total_seconds() / 3600

def get_weather_forecast(city: str, debug: bool=False):
    temps, errs = [], []
    # OpenWeather
    try:
        r = requests.get(f"https://api.openweathermap.org/data/2.5/forecast",
                         params={"q": city, "appid": OPENWEATHER_API_KEY, "units": "imperial"}).json()
        temps.append(max(e["main"]["temp"] for e in r["list"][:8]))
    except Exception as e:
        if debug: errs.append(f"OWM: {e}")
    # WeatherAPI.com
    try:
        r = requests.get("http://api.weatherapi.com/v1/forecast.json",
                         params={"key": WEATHERAPI_KEY, "q": city, "days": 1}).json()
        temps.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except Exception as e:
        if debug: errs.append(f"WAPI: {e}")
    # Tomorrow.io
    try:
        r = requests.get("https://api.tomorrow.io/v4/weather/forecast",
                         params={"location": city, "apikey": TOMORROWIO_API_KEY,
                                 "timesteps": "1d", "units": "imperial"}).json()
        temps.append(r["timelines"]["daily"][0]["values"]["temperatureMax"])
    except Exception as e:
        if debug: errs.append(f"TOMOR: {e}")

    if not temps:
        hist = get_historical_temp(city) or 75
        return f"All APIs failed; hist avg {hist}°F ({'; '.join(errs)})", 30

    mx = round(sum(temps)/len(temps),1)
    sp = max(temps) - min(temps)
    avg_hist = get_historical_temp(city) or 75
    dev = mx - avg_hist
    raw = min(100, max(10, 50 + dev*3 - sp*2))
    pct = raw * max(0.5, 1 - calc_hours_until_event()/24)
    cond = r["list"][0]["weather"][0]["description"] if "list" in locals() else "unknown"
    info = f"High: {mx}°F (hist {avg_hist:.1f}°F, Δ{dev:+.1f}), {cond}, spread {sp:.1f}° → {pct:.1f}%"
    return info, pct

def ask_gpt_prediction(question: str, weather_info: str) -> str:
    prompt = textwrap.dedent(f"""
        You are a high-accuracy prediction market analyst.

        Market Question:
        {question}

        Weather Forecast Summary:
        {weather_info}

        1) Identify YES/NO prices.
        2) Which outcome is underpriced?
        3) Justify with evidence.
        4) Give a probability percentage.

        Reply as:
        - 🔮 Prediction: [Yes/No]
        - 📈 Probability: [xx%]
        - 🧠 Reasoning: [why]
    """).strip()

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are cautious but effective."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.3,
        max_tokens=300
    )
    return response.choices[0].message.content.strip()

# ============ OCR + ANALYSIS ============
def ocr_and_analyze(uploaded, debug):
    img = Image.open(io.BytesIO(uploaded.read()))
    text = pytesseract.image_to_string(img)
    city = extract_city(text)
    if not city:
        return text, "", 0, "⚠️ Could not detect a city keyword."
    weather_info, conf = get_weather_forecast(city, debug)
    pred = ask_gpt_prediction(text, weather_info)
    return text, weather_info, conf, pred

# ============ UI ============
tab1, tab2 = st.tabs(["📊 Auto Scan", "📸 Manual Upload"])

with tab1:
    st.header("Top High-Confidence Daily Weather Bets")
    threshold = st.slider("Model confidence ≥%", 10, 100, 60)
    debug_flag = st.sidebar.checkbox("🔍 Debug (Auto)", value=False)
    df = fetch_daily_weather_markets()
    if df.empty:
        st.info("🔒 Add Kalshi secrets to `.streamlit/secrets.toml` to enable Auto-Scan.")
    else:
        results = []
        for _, row in df.iterrows():
            city = extract_city(row["ticker"]) or extract_city(row["question"])
            info, pct = get_weather_forecast(city, debug_flag)
            if pct >= threshold:
                pred = ask_gpt_prediction(row["question"], info)
                results.append({
                    "Market":       row["question"],
                    "Yes % (mkt)":  f"{row['yes_pct']:.1f}%",
                    "Conf % (mdl)": f"{pct:.1f}%",
                    "Prediction":   pred
                })
        st.dataframe(pd.DataFrame(results), use_container_width=True)

with tab2:
    st.header("Upload a Kalshi Screenshot")
    debug_flag_u = st.sidebar.checkbox("🔍 Debug (Upload)", value=False, key="upl")
    uploaded = st.file_uploader("PNG/JPG Screenshot", type=["png","jpg","jpeg"])
    if st.button("Analyze Screenshot") and uploaded:
        txt, winfo, conf, pred = ocr_and_analyze(uploaded, debug_flag_u)
        st.subheader("🔍 OCR Text");        st.write(txt)
        st.subheader("🌡️ Weather Model");   st.write(winfo)
        st.subheader("📈 Model Confidence"); st.write(f"{conf:.1f}%")
        st.subheader("🤖 GPT Prediction");   st.write(pred)