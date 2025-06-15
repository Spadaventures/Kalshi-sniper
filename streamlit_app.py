import streamlit as st
import openai
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime
from openai import OpenAI

# ============ CONFIG ============
MODEL_NAME = "gpt-4o"

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
st.markdown("Upload a **screenshot of a Kalshi question with its YES/NO prices**. I’ll extract it and tell you what to bet on.")

uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png", "jpg", "jpeg"])
run_button = st.button("📈 Run AI Analysis")

# ============ HELPER FUNCTIONS ============
def extract_text_from_image(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(image)

def get_weather_forecast(city):
    try:
        api_key = st.secrets["OPENWEATHER_API_KEY"]
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=imperial"
        response = requests.get(url).json()

        temps = [entry['main']['temp'] for entry in response['list'][:8]]
        max_temp = max(temps)
        rain_forecast = [entry.get('rain', {}).get('3h', 0.0) for entry in response['list'][:8]]
        total_rain = sum(rain_forecast)
        condition = response['list'][0]['weather'][0]['description']

        today = datetime.now()
        avg_temp = {
            "NYC": 76, "Miami": 88, "Denver": 79,
            "Chicago": 75, "Austin": 89, "LA": 77,
            "New York": 76, "Los Angeles": 77
        }.get(city, 78)

        temp_deviation = max_temp - avg_temp
        confidence_hint = "High" if abs(temp_deviation) >= 5 or total_rain > 2 else "Medium"

        return {
            "forecast_high": max_temp,
            "average_high": avg_temp,
            "deviation": temp_deviation,
            "condition": condition,
            "rain": total_rain,
            "confidence": confidence_hint
        }
    except:
        return None

def format_prompt(text, weather_data=None):
    weather_summary = ""
    if weather_data:
        weather_summary = (
            f"Forecast high: {weather_data['forecast_high']}°F (avg {weather_data['average_high']}°F, Δ {weather_data['deviation']:+.1f})\n"
            f"Condition: {weather_data['condition']}, Rain: {weather_data['rain']}mm\n"
            f"Est. Confidence from forecast: {weather_data['confidence']}"
        )

    return f"""You are a high-accuracy prediction market AI.

Extracted Kalshi Market Text:
{text}

{weather_summary}

Instructions:
- Identify YES/NO prices.
- Use weather forecast and seasonal norms to determine which outcome is underpriced.
- Recommend which option to bet on.
- Justify your reasoning clearly.
- Rate your confidence as High / Medium / Low.
"""

def analyze_screenshot_text(text):
    weather_info = None
    city_found = None
    for city in ["NYC", "New York", "Miami", "Denver", "Chicago", "Austin", "LA", "Los Angeles"]:
        if city.lower() in text.lower():
            city_found = city
            break

    if city_found:
        weather_info = get_weather_forecast(city_found)

    prompt = format_prompt(text, weather_info)
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a cautious but effective prediction market analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=700
    )
    return response.choices[0].message.content.strip()

# ============ ANALYSIS ============
if run_button and uploaded_file:
    image_text = extract_text_from_image(uploaded_file.read())
    with st.spinner("Analyzing screenshot..."):
        result = analyze_screenshot_text(image_text)
        st.markdown(f"""### 📊 Result:\n\n{result}\n\n---""")