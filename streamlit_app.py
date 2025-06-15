
import streamlit as st
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime
from openai import OpenAI

# ============ CONFIG ============
MODEL_NAME = "gpt-4o"
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
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

st.title("📸 Kalshi Screenshot Analyzer (iOS Optimized)")
st.markdown("Upload a **screenshot of a Kalshi question with its YES/NO prices**. I’ll extract it and tell you the most likely outcome.")

uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png", "jpg", "jpeg"])
run_button = st.button("📈 Run AI Analysis")

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
        confidence_hint = "High" if max_temp >= 85 or total_rain > 2 else "Medium"
        today = datetime.now()
        avg_temp = {
            "NYC": 76, "Miami": 88, "Denver": 79,
            "Chicago": 75, "Austin": 89, "LA": 77,
            "New York": 76, "Los Angeles": 77
        }.get(city, 78)
        temp_deviation = max_temp - avg_temp
        return f"Forecast high: {max_temp}°F (avg {avg_temp}°F, Δ {temp_deviation:+.1f}), Condition: {condition}, Rain: {total_rain}mm\nEst. Confidence: {confidence_hint}"
    except:
        return "Weather forecast unavailable"

def format_prompt(text, weather_data=None):
    weather_note = f"\n\nWeather forecast info:\n{weather_data}" if weather_data else ""
    return f"""You are a high-accuracy AI prediction market analyst.

Extracted Kalshi Market Text:
{text}{weather_note}

1. Identify the market question and the YES/NO prices.
2. Estimate which outcome is underpriced.
3. Justify the decision with evidence (like weather forecast or seasonal norms).
4. Rate confidence: High / Medium / Low.
"""


def analyze_screenshot_text(text):
    weather_info = None
    if "rain" in text.lower() or "temperature" in text.lower():
        for city in ["NYC", "New York", "Miami", "Denver", "Chicago", "Austin", "LA", "Los Angeles"]:
            if city.lower() in text.lower():
                weather_info = get_weather_forecast(city)
                break

    prompt = format_prompt(text, weather_info)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a cautious but effective prediction market analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=600
    )
    return response.choices[0].message.content.strip()

# ============ ANALYSIS ============
if run_button and uploaded_file:
    image_text = extract_text_from_image(uploaded_file.read())
    with st.spinner("Analyzing screenshot..."):
        result = analyze_screenshot_text(image_text)
        st.markdown(f"### 🧠 Result:\n\n{result}\n\n---")