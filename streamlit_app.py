import streamlit as st
import openai
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime
from openai import OpenAI
import csv
import json

# ================= CONFIGURATION =================
openai.api_key = st.secrets["OPENAI_API_KEY"]
MODEL_NAME = "gpt-4o"
WEATHERAPI_KEY = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]
OPENWEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
KALSHI_API_KEY = st.secrets["KALSHI_API_KEY"]
KALSHI_KEY_ID = st.secrets["KALSHI_KEY_ID"]

# ================= UI SETUP =================
st.set_page_config(page_title="Kalshi Sniper", layout="centered")
st.title("📸 Kalshi Screenshot Analyzer (Weather Markets Only)")
st.markdown("Upload a **screenshot of a Kalshi YES/NO weather market**, and the bot will analyze and tell you the best bet based on weather APIs, Kalshi order book, and historical data.")

uploaded_file = st.file_uploader("Upload Screenshot", type=["png", "jpg", "jpeg"])
run_button = st.button("📈 Run AI Analysis")

# ================= UTILITY FUNCTIONS =================
@st.cache_data
def load_historical_temps():
    try:
        with open("historical_temps.csv", newline='') as csvfile:
            return list(csv.DictReader(csvfile))
    except:
        return []

def get_historical_temp(city):
    data = load_historical_temps()
    temps = [float(row["temp"]) for row in data if row["city"].lower() == city.lower()]
    return round(sum(temps) / len(temps), 1) if temps else 78

def extract_text_from_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image)
    except Exception as e:
        return f"Error extracting text: {e}"

def extract_city(text):
    cities = ["Los Angeles", "LA", "Denver", "Miami", "NYC", "New York", "Chicago", "Phoenix", "Austin"]
    for city in cities:
        if city.lower() in text.lower():
            return city
    return "Los Angeles"  # default fallback

def calculate_hours_until_end_of_day():
    now = datetime.now()
    return (datetime.combine(now.date(), datetime.max.time()) - now).total_seconds() / 3600

def fetch_kalshi_order_book():
    try:
        headers = {
            "Authorization": f"Bearer {KALSHI_API_KEY}",
            "X-Api-Key": KALSHI_KEY_ID
        }
        r = requests.get("https://trading-api.kalshi.com/trade-api/v2/markets", headers=headers)
        data = r.json()
        weather = [m for m in data.get("markets", []) if "temperature" in m["ticker"].lower()]
        return json.dumps(weather, indent=2)
    except Exception as e:
        return f"[Order Book Error] {e}"

def get_weather_forecast(city):
    try:
        owm = requests.get(f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=imperial").json()
        owm_max = max([entry["main"]["temp"] for entry in owm["list"][:8]])

        wapi = requests.get(f"http://api.weatherapi.com/v1/forecast.json?key={WEATHERAPI_KEY}&q={city}&days=1").json()
        wapi_max = wapi["forecast"]["forecastday"][0]["day"]["maxtemp_f"]

        tmr = requests.get(f"https://api.tomorrow.io/v4/weather/forecast?location={city}&apikey={TOMORROWIO_API_KEY}&timesteps=1d&units=imperial").json()
        tmr_max = tmr["timelines"]["daily"][0]["values"]["temperatureMax"]

        maxes = [owm_max, wapi_max, tmr_max]
        max_temp = round(sum(maxes) / len(maxes), 1)
        spread = max(maxes) - min(maxes)
        avg_temp = get_historical_temp(city)
        deviation = max_temp - avg_temp

        base_chance = 50 + deviation * 3 - spread * 2
        hours_left = calculate_hours_until_end_of_day()
        adjust = 1 - (hours_left / 24)
        final_chance = max(10, min(100, base_chance * adjust))

        return f"Forecast high: {max_temp}°F (avg {avg_temp}°F), spread: {spread:.1f}°", final_chance
    except Exception as e:
        return f"🌩️ Weather API error: {e}", 0

def format_prompt(text, forecast_info=None, order_book=None):
    return f"""
You are a market analyst AI that uses weather data to analyze Kalshi temperature markets.

Extracted Market:
{text}

Weather forecast info:
{forecast_info}

Order Book Data:
{order_book}

INSTRUCTIONS:
1. Identify the market range choices (e.g. 76° or below, 77°+).
2. Choose the most underpriced option.
3. Justify with evidence.
4. Return:
- 🔮 Prediction: [e.g. 77°+]
- 📈 Estimated Probability: [xx%]
- 🧠 Reasoning: [short reason why]
"""

def analyze(text):
    city = extract_city(text)
    forecast_info, confidence = get_weather_forecast(city)
    order_book = fetch_kalshi_order_book()

    if confidence < 40:
        return f"❌ Skipping. Estimated chance of success is too low: {confidence:.1f}%\nMarket: {text[:120]}"

    prompt = format_prompt(text, forecast_info, order_book)
    client = OpenAI(api_key=openai.api_key)
    res = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You're a careful, high-accuracy market analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=600
    )
    out = res.choices[0].message.content.strip()
    if confidence > 80:
        st.toast("🚨 High-Confidence Bet Opportunity!", icon="⚡")
    return out

# ================= RUN =================
if run_button and uploaded_file:
    st.info("🧠 Extracting text and analyzing...")
    text = extract_text_from_image(uploaded_file.read())
    with st.spinner("Running full analysis..."):
        result = analyze(text)
        st.markdown(f"### 📊 Result\n\n{result}")