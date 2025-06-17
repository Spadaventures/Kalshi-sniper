import streamlit as st
import openai
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime
from openai import OpenAI
import json
import csv

# ===== Streamlit Page Config =====
st.set_page_config(page_title="Kalshi Sniper", layout="wide")

# ===== Load API Keys =====
openai.api_key = st.secrets["OPENAI_API_KEY"]
MODEL_NAME = "gpt-4o"
WEATHERAPI_KEY = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]
OPENWEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
KALSHI_API_KEY = st.secrets["KALSHI_API_KEY"]
KALSHI_KEY_ID = st.secrets["KALSHI_KEY_ID"]

# ===== UI =====
st.title("📸 Kalshi Screenshot Analyzer (iOS Optimized)")
st.markdown("Upload a **screenshot of a Kalshi question with its YES/NO prices**. I’ll extract it and tell you the most likely outcome.")
uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png", "jpg", "jpeg"])
run_button = st.button("📈 Run AI Analysis")

# ===== OCR =====
def extract_text_from_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image)
    except Exception as e:
        return f"Error reading image: {e}"

@st.cache_data
def load_historical_temps():
    try:
        with open("historical_temps.csv", newline='') as csvfile:
            return list(csv.DictReader(csvfile))
    except:
        return []

historical_data = load_historical_temps()

def get_historical_temp(city):
    try:
        temps = [float(row["temp"]) for row in historical_data if row["city"].lower() == city.lower()]
        return sum(temps) / len(temps) if temps else None
    except:
        return None

def calculate_hours_until_event():
    now = datetime.now()
    end_of_day = datetime.combine(now.date(), datetime.max.time())
    return (end_of_day - now).total_seconds() / 3600

def fetch_kalshi_order_book():
    try:
        headers = {
            "Authorization": f"Bearer {KALSHI_API_KEY}",
            "X-Api-Key": KALSHI_KEY_ID
        }
        response = requests.get("https://trading-api.kalshi.com/trade-api/v2/markets", headers=headers)
        data = response.json()
        weather_markets = [m for m in data.get("markets", []) if "temperature" in m["ticker"].lower() or "rain" in m["ticker"].lower()]
        return json.dumps(weather_markets, indent=2)
    except Exception as e:
        return f"Kalshi order book fetch failed: {str(e)}"

def get_weather_forecast(city):
    try:
        owm_url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=imperial"
        owm_response = requests.get(owm_url).json()
        owm_temps = [entry['main']['temp'] for entry in owm_response['list'][:8]]
        owm_max = max(owm_temps)

        wapi_url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHERAPI_KEY}&q={city}&days=1"
        wapi_response = requests.get(wapi_url).json()
        wapi_max = wapi_response['forecast']['forecastday'][0]['day']['maxtemp_f']

        t_url = f"https://api.tomorrow.io/v4/weather/forecast?location={city}&apikey={TOMORROWIO_API_KEY}&timesteps=1d&units=imperial"
        t_response = requests.get(t_url).json()
        t_max = t_response['timelines']['daily'][0]['values']['temperatureMax']

        forecasts = [owm_max, wapi_max, t_max]
        max_temp = round(sum(forecasts) / len(forecasts), 1)
        spread = max(forecasts) - min(forecasts)

        condition = owm_response['list'][0]['weather'][0]['description']
        avg_temp = get_historical_temp(city) or 78
        temp_deviation = max_temp - avg_temp

        raw_prob = 50 + temp_deviation * 3 - spread * 2
        raw_prob = min(100, max(10, raw_prob))

        hours_to_event = calculate_hours_until_event()
        adjustment = min(1.0, max(0.5, 1 - (hours_to_event / 24)))
        adjusted_prob = raw_prob * adjustment

        return f"Forecast high: {max_temp}°F (hist avg {avg_temp:.1f}°F, Δ {temp_deviation:+.1f}), Condition: {condition}, API spread: {spread:.1f}°\nEst. Success Rate: {adjusted_prob:.1f}%", adjusted_prob

    except Exception as e:
        return f"🌩️ Weather API error: {str(e)}", 0

def extract_city(text):
    city_keywords = ["NYC", "New York", "Miami", "Denver", "Chicago", "Austin", "LA", "Los Angeles"]
    for city in city_keywords:
        if city.lower() in text.lower():
            return city
    return ""

def format_prompt(text, weather_data=None, order_book_data=None):
    weather_note = f"\n\nWeather forecast info:\n{weather_data}" if weather_data else ""
    order_book_note = f"\n\nKalshi market order book:\n{order_book_data}" if order_book_data else ""
    return f"""You are a high-accuracy AI prediction market analyst.

Extracted Kalshi Market Text:
{text}{weather_note}{order_book_note}

1. Identify the market question and the YES/NO prices.
2. Estimate which outcome is underpriced.
3. Justify the decision with evidence (like weather forecast or seasonal norms).
4. Give an estimated percentage chance the prediction will be correct.
5. Respond in the format:
- 🔮 **Prediction**: [Clear YES/NO range choice]
- 📈 **Estimated Probability**: [xx%]
- 🧠 **Reasoning**: [Why this outcome is likely]"""

def analyze_screenshot_text(text):
    city = extract_city(text)
    weather_info = None
    confidence_pct = 0
    order_book_data = fetch_kalshi_order_book()

    if city:
        weather_info, confidence_pct = get_weather_forecast(city)

    if confidence_pct < 40:
        st.info(f"❌ Skipping. Estimated chance of success is too low: {confidence_pct:.1f}%\nMarket: {text[:100]}")
        return f"❌ Skipping. Estimated chance of success is too low: {confidence_pct:.1f}%"

    prompt = format_prompt(text, weather_info, order_book_data)
    client = OpenAI(api_key=openai.api_key)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a cautious but effective prediction market analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=600
    )
    result = response.choices[0].message.content.strip()

    if confidence_pct >= 80:
        st.toast("🚨 High-probability opportunity detected!", icon="⚡")

    return result

# ===== Main Action =====
if run_button and uploaded_file:
    image_text = extract_text_from_image(uploaded_file.read())
    with st.spinner("Analyzing screenshot..."):
        result = analyze_screenshot_text(image_text)
        st.markdown(f"### 📊 Result:\n\n{result}\n\n---")
