import streamlit as st
from PIL import Image
import io
import pytesseract
import requests
import json
import csv
import pandas as pd
from datetime import datetime
import threading
import websocket
import openai
import time
import jwt

# ============ PAGE CONFIG ============
st.set_page_config(page_title="Kalshi Sniper", layout="wide")

# ============ SECRETS & CLIENT SETUP ============
openai.api_key       = st.secrets["OPENAI_API_KEY"]
client               = openai.OpenAI()

MODEL_NAME           = "gpt-4o"
OPENWEATHER_API_KEY  = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY       = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY   = st.secrets["TOMORROWIO_API_KEY"]

KALSHI_KEY_ID        = st.secrets["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY   = st.secrets["KALSHI_PRIVATE_KEY"]

# ============ JWT HELPER ============
def get_kalshi_bearer_token() -> str:
    now = int(time.time())
    payload = {
        "iss": KALSHI_KEY_ID,
        "iat": now,
        "exp": now + 600   # valid 10 minutes
    }
    return jwt.encode(payload, KALSHI_PRIVATE_KEY, algorithm="RS256")

# ============ REAL-TIME KALSHI WEBSOCKET ============
st.sidebar.header("🔄 Live Weather Markets")
latest = st.sidebar.empty()
WS_URL = "wss://trade-api.kalshi.com/ws/markets"

def on_msg(ws, msg):
    try:
        data = json.loads(msg)
        for m in data.get("markets", []):
            if any(w in m["ticker"].lower() for w in ("temperature","rain")):
                latest.markdown(f"**{m['ticker']}** — Yes: {m.get('yes_price')} | No: {m.get('no_price')}")
    except:
        pass

def on_err(ws, e):
    latest.error(f"WS Error: {e}")

def on_close(ws, _):
    latest.warning("WebSocket closed")

def start_ws():
    if not KALSHI_KEY_ID or not KALSHI_PRIVATE_KEY:
        latest.info("🔒 Add your Kalshi secrets to enable live feed.")
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

# ============ TOP DAILY WEATHER PICKS ============
@st.cache_data(ttl=300)
def fetch_daily_weather_markets():
    if not KALSHI_KEY_ID or not KALSHI_PRIVATE_KEY:
        return pd.DataFrame()
    bearer = get_kalshi_bearer_token()
    headers = {
        "Authorization": f"Bearer {bearer}",
        "X-Api-Key":     KALSHI_KEY_ID
    }
    resp = requests.get(
        "https://trading-api.kalshi.com/trade-api/v2/markets",
        headers=headers
    ).json()
    rows = []
    for m in resp.get("markets", []):
        if (
            m.get("resolution") == "DAILY"
            and any(w in m["ticker"].lower() for w in ("temperature","rain"))
        ):
            yes_pct = float(m.get("yes_price",0)) * 100
            rows.append({
                "question": m["question"],
                "ticker":   m["ticker"],
                "yes_pct":  yes_pct,
                "expires":  m.get("expiration_time")
            })
    return pd.DataFrame(rows).sort_values("yes_pct", ascending=False)

# ============ HISTORICAL DATA ============
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
    forecasts = []
    # OpenWeather
    try:
        r = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?q={city}"
            f"&appid={OPENWEATHER_API_KEY}&units=imperial"
        ).json()
        temps = [e["main"]["temp"] for e in r["list"][:8]]
        forecasts.append(max(temps))
    except Exception as e:
        if debug: st.warning(f"OpenWeather error: {e}")
    # WeatherAPI.com
    try:
        r = requests.get(
            f"http://api.weatherapi.com/v1/forecast.json?key={WEATHERAPI_KEY}"
            f"&q={city}&days=1"
        ).json()
        forecasts.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except Exception as e:
        if debug: st.warning(f"WeatherAPI error: {e}")
    # Tomorrow.io
    try:
        r = requests.get(
            f"https://api.tomorrow.io/v4/weather/forecast?location={city}"
            f"&apikey={TOMORROWIO_API_KEY}&timesteps=1d&units=imperial"
        ).json()
        forecasts.append(r["timelines"]["daily"][0]["values"]["temperatureMax"])
    except Exception as e:
        if debug: st.warning(f"Tomorrow.io error: {e}")

    if not forecasts:
        hist = get_historical_temp(city) or 75
        if debug: st.info(f"All APIs failed; using hist avg {hist}°F")
        return f"All APIs failed; hist avg {hist}°F", 30

    mx      = round(sum(forecasts)/len(forecasts),1)
    sp      = max(forecasts) - min(forecasts)
    avg_hist= get_historical_temp(city) or 75
    dev     = mx - avg_hist
    raw     = 50 + dev*3 - sp*2
    raw     = max(10, min(100, raw))
    hrs     = calc_hours_until_event()
    pct     = raw * max(0.5, 1 - hrs/24)
    cond    = (r["list"][0]["weather"][0]["description"] if "list" in locals() else "unknown")
    info    = (
        f"High: {mx}°F (hist {avg_hist:.1f}°F, Δ{dev:+.1f}), "
        f"{cond}, spread {sp:.1f}° → {pct:.1f}%"
    )
    return info, pct

def ask_gpt_prediction(question: str, weather_info: str) -> str:
    prompt = (
        "You are a high-accuracy prediction market analyst.\n\n"
        f"Market:\n{question}\n\n"
        f"Weather:\n{weather_info}\n\n"
        "1) Identify YES/NO prices.\n"
        "2) Which outcome is underpriced?\n"
        "3) Justify with evidence.\n"
        "4) Give probability.\n\n"
        "Reply:\n"
        "- Prediction: [your pick]\n"
        "- Probability: [xx%]\n"
        "- Reasoning: [why]\n"
    )
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role":"system","content":"You are cautious but effective."},
            {"role":"user","content":prompt}
        ],
        temperature=0.3
    )
    return resp.choices[0].message.content.strip()

# ============ MANUAL UPLOAD ============
def ocr_and_analyze(uploaded, debug):
    text = pytesseract.image_to_string(Image.open(io.BytesIO(uploaded.read())))
    city = extract_city(text)
    weather_info, conf = ("", 0)
    if city:
        weather_info, conf = get_weather_forecast(city, debug)
    prediction = ask_gpt_prediction(text, weather_info)
    return text, weather_info, conf, prediction

# ============ UI TABS ============
tab1, tab2 = st.tabs(["📊 Auto Scan", "📸 Manual Upload"])

with tab1:
    st.header("Top High-Confidence Daily Weather Bets")
    threshold  = st.slider("Model confidence ≥%", 10, 100, 60)
    debug_flag = st.sidebar.checkbox("🔍 Debug (Auto)", value=False)
    df         = fetch_daily_weather_markets()
    if df.empty:
        st.info("Add your Kalshi secrets to `.streamlit/secrets.toml` to enable Auto-Scan.")
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
    uploaded     = st.file_uploader("PNG/JPG Screenshot", type=["png","jpg","jpeg"])
    if st.button("Analyze Screenshot") and uploaded:
        txt, winfo, conf, pred = ocr_and_analyze(uploaded, debug_flag_u)
        st.subheader("🔍 OCR Text");        st.write(txt)
        st.subheader("🌡️ Weather Model");   st.write(winfo)
        st.subheader("📈 Model Confidence"); st.write(f"{conf:.1f}%")
        st.subheader("🤖 GPT Prediction");   st.write(pred)