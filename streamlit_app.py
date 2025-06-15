
import streamlit as st
import openai
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime

# ============ CONFIG ============
from openai import OpenAI
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
MODEL_NAME = "gpt-4o"
WEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]

# ============ STREAMLIT UI ============
st.set_page_config(page_title="Kalshi Sniper", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 500px;
            margin: auto;
        }
        .stTextInput > div > div > input, .stTextArea > div > textarea {
            font-size: 16px;
        }
        .stButton > button {
            width: 100%;
            font-size: 18px;
        }
    </style>
""", unsafe_allow_html=True)

st.title("📸 Kalshi Weather Market Sniper")
st.markdown("Upload a **screenshot of a Kalshi weather market**, and I’ll tell you which YES/NO range to bet on.")

uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png", "jpg", "jpeg"])
run_button = st.button("📈 Analyze Market")

# ============ HELPER FUNCTIONS ============
def extract_text_from_image(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(image)

def get_weather_forecast(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=imperial"
        response = requests.get(url).json()

        temps = [entry['main']['temp'] for entry in response['list'][:8]]
        max_temp = max(temps)
        rain_forecast = [entry.get('rain', {}).get('3h', 0.0) for entry in response['list'][:8]]
        total_rain = sum(rain_forecast)
        condition = response['list'][0]['weather'][0]['description']

        today = datetime.now()
        avg_temp = {
            "New York": 76, "Miami": 88, "Denver": 79,
            "Chicago": 75, "Austin": 89, "Los Angeles": 77
        }.get(city, 78)
        temp_deviation = max_temp - avg_temp
        confidence_hint = "High" if max_temp >= 85 or total_rain > 2 else "Medium"

        return f"Forecast high: {max_temp}°F (avg {avg_temp}°F, Δ {temp_deviation:+.1f}), Condition: {condition}, Rain: {total_rain}mm\nConfidence Hint: {confidence_hint}"
    except:
        return "Weather forecast unavailable"

def format_prompt(text, weather_data=None):
    weather_note = f"\n\nWeather Forecast:\n{weather_data}" if weather_data else ""
    return f"""You are a high-accuracy prediction market analyst.

Kalshi Market Question:
{text}{weather_note}

Instructions:
1. Use the weather forecast to estimate today's high temperature.
2. Choose the single **most likely correct YES range**.
3. Justify your choice in 1–2 sentences.
4. Say exactly what to bet on, like this: ✅ BET: "75° to 76°" — Yes
5. Rate confidence: High / Medium / Low.
"""

def analyze_screenshot_text(text):
    weather_info = None
    cities = {
        "nyc": "New York",
        "new york": "New York",
        "la": "Los Angeles",
        "los angeles": "Los Angeles",
        "miami": "Miami",
        "denver": "Denver",
        "chicago": "Chicago",
        "austin": "Austin"
    }
    for key, value in cities.items():
        if key in text.lower():
            weather_info = get_weather_forecast(value)
            break

    prompt = format_prompt(text, weather_info)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a high-accuracy prediction market analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=600
    )
    return response.choices[0].message.content.strip()

# ============ MAIN ============
if run_button and uploaded_file:
    image_text = extract_text_from_image(uploaded_file.read())
    with st.spinner("Analyzing..."):
        result = analyze_screenshot_text(image_text)
        st.markdown(f"### 📊 Result:

{result}")