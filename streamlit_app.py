import streamlit as st
from PIL import Image
import io
import pytesseract
import requests
import json
import csv
from datetime import datetime
import threading
import websocket
import openai
from openai import OpenAI

# ============ PAGE CONFIG (MUST BE FIRST) ============
st.set_page_config(page_title="Kalshi Sniper", layout="wide")

# ============ SECRETS & CLIENT SETUP ============
openai.api_key = st.secrets["OPENAI_API_KEY"]
client = OpenAI()

MODEL_NAME = "gpt-4o"
OPENWEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY      = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY  = st.secrets["TOMORROWIO_API_KEY"]

# ============ REAL-TIME KALSHI WEBSOCKET ============
st.sidebar.markdown("## 🔄 Live Weather Markets")
latest_market = st.sidebar.empty()

KALSHI_WS_URL = "wss://trade-api.kalshi.com/ws/markets"
def on_message(ws, message):
    try:
        data = json.loads(message)
        for m in data.get("markets", []):
            if "temperature" in m["ticker"].lower() or "rain" in m["ticker"].lower():
                latest_market.markdown(
                    f"**{m['ticker']}** — Yes: {m.get('yes_price')} | No: {m.get('no_price')}"
                )
    except:
        pass

def on_error(ws, error):
    latest_market.error(f"WS Error: {error}")

def on_close(ws, _):
    latest_market.warning("WebSocket closed")

def start_ws():
    ws = websocket.WebSocketApp(
        KALSHI_WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

threading.Thread(target=start_ws, daemon=True).start()

# ============ UI LAYOUT ============
st.title("📸 Kalshi Screenshot Analyzer (iOS Optimized)")
st.markdown(
    "Upload a screenshot of a Kalshi weather market with its YES/NO prices, "
    "and I'll tell you the most probable outcome."
)

DEBUG = st.sidebar.checkbox("🔍 Show API Debug Info", value=False)

uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png","jpg","jpeg"])
run_button   = st.button("📈 Run AI Analysis")

# ============ HELPERS & DATA LOADING ============
@st.cache_data
def load_historical_temps():
    try:
        with open("historical_temps.csv", newline="") as f:
            return list(csv.DictReader(f))
    except:
        return []

historical_data = load_historical_temps()

def get_historical_temp(city: str):
    temps = [float(r["temp"]) for r in historical_data if r["city"].lower()==city.lower()]
    return sum(temps)/len(temps) if temps else None

def extract_text_from_image(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img)

def calculate_hours_until_event() -> float:
    now = datetime.now()
    eod = datetime.combine(now.date(), datetime.max.time())
    return (eod - now).total_seconds() / 3600

# ============ WEATHER FORECAST WITH FALLBACK ============
def get_weather_forecast(city: str):
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
        if DEBUG: st.warning(f"OpenWeather error: {e}")
    # WeatherAPI.com
    try:
        r = requests.get(
            f"http://api.weatherapi.com/v1/forecast.json?key={WEATHERAPI_KEY}"
            f"&q={city}&days=1"
        ).json()
        forecasts.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except Exception as e:
        if DEBUG: st.warning(f"WeatherAPI error: {e}")
    # Tomorrow.io
    try:
        r = requests.get(
            f"https://api.tomorrow.io/v4/weather/forecast?location={city}"
            f"&apikey={TOMORROWIO_API_KEY}&timesteps=1d&units=imperial"
        ).json()
        forecasts.append(r["timelines"]["daily"][0]["values"]["temperatureMax"])
    except Exception as e:
        if DEBUG: st.warning(f"Tomorrow.io error: {e}")

    if not forecasts:
        hist = get_historical_temp(city) or 75
        if DEBUG: st.info(f"All APIs failed; using historical avg {hist}")
        return f"All weather APIs failed. Using historical avg {hist}°F", 30

    max_temp = round(sum(forecasts)/len(forecasts), 1)
    spread   = max(forecasts) - min(forecasts)
    # weather description from first API if available
    cond = (r["list"][0]["weather"][0]["description"]
            if "list" in locals() else "unknown")
    avg_hist = get_historical_temp(city) or 75
    deviation = max_temp - avg_hist

    raw = 50 + deviation*3 - spread*2
    raw = max(10, min(100, raw))
    # decay factor as event approaches
    hours = calculate_hours_until_event()
    factor = max(0.5, 1 - hours/24)
    pct = raw * factor

    text = (
        f"Forecast high: {max_temp}°F (hist avg {avg_hist:.1f}°F, Δ{deviation:+.1f}), "
        f"Condition: {cond}, spread: {spread:.1f}°\n"
        f"Est. Success Rate: {pct:.1f}%"
    )
    return text, pct

# ============ TEXT ANALYSIS & GPT PROMPT ============
def extract_city(text: str) -> str:
    for c in ("NYC","New York","Miami","Denver","Chicago","Austin","LA","Los Angeles"):
        if c.lower() in text.lower():
            return c
    return ""

def format_prompt(market_text, weather_info=""):
    return (
        "You are a high accuracy prediction market analyst.\n\n"
        f"Market:\n{market_text}\n\n"
        f"Weather:\n{weather_info}\n\n"
        "1. Identify YES/NO prices.\n"
        "2. Which outcome is underpriced?\n"
        "3. Justify with evidence.\n"
        "4. Give probability.\n\n"
        "Respond:\n"
        "- Prediction: [your pick]\n"
        "- Probability: [xx%]\n"
        "- Reasoning: [why]\n"
    )

def analyze_screenshot_text(text: str):
    city = extract_city(text)
    winfo = ""
    pct = 0
    if city:
        winfo, pct = get_weather_forecast(city)
    if pct < 40:
        st.info(f"Skipping low probability ({pct:.1f}%) for market:\n{text}")
        return f"Skipping; too low ({pct:.1f}%)"
    prompt = format_prompt(text, winfo)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role":"system","content":"You are cautious but effective."},
            {"role":"user",  "content":prompt}
        ],
        temperature=0.3
    )
    return resp.choices[0].message.content.strip()

# ============ MAIN ============ 
if run_button and uploaded_file:
    raw = extract_text_from_image(uploaded_file.read())
    with st.spinner("Analyzing…"):
        out = analyze_screenshot_text(raw)
    st.markdown(f"### Result\n\n{out}")