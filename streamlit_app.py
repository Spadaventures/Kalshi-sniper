import streamlit as st
from PIL import Image
import io
import pytesseract
import requests
import openai
from datetime import datetime
import textwrap

# ============ CONFIG ============
openai.api_key = st.secrets["OPENAI_API_KEY"]   # make sure you have this in .streamlit/secrets.toml
MODEL_NAME = "gpt-4o"

OWM_KEY    = st.secrets["WEATHER_API_KEY"]
WAPI_KEY   = st.secrets["WEATHERAPI_KEY"]
TOMOR_KEY  = st.secrets["TOMORROWIO_API_KEY"]

# ============ PAGE SETUP ============
st.set_page_config(page_title="Weather Sniper (Manual Only)", layout="centered")
st.title("📸 Manual Kalshi Weather Analyzer")

st.markdown("""
Upload a screenshot of any **Kalshi weather question** (YES/NO prices).
This will OCR the question, fetch 3 weather forecasts, & then ask GPT for a pick.
""")

# ============ HELPERS ============
def extract_text_from_image(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img)

def get_weather_forecast(city: str):
    """Fetch max-temp forecasts from OpenWeather, WeatherAPI & Tomorrow.io."""
    temps = []
    errs = []
    # OpenWeather
    try:
        r = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": OWM_KEY, "units": "imperial"},
            timeout=5
        ).json()
        block = r["list"][:8]
        temps.append(max(item["main"]["temp"] for item in block))
    except Exception as e:
        errs.append(f"OWM: {e}")
    # WeatherAPI.com
    try:
        r = requests.get(
            "http://api.weatherapi.com/v1/forecast.json",
            params={"key": WAPI_KEY, "q": city, "days": 1},
            timeout=5
        ).json()
        temps.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except Exception as e:
        errs.append(f"WAPI: {e}")
    # Tomorrow.io
    try:
        r = requests.get(
            "https://api.tomorrow.io/v4/weather/forecast",
            params={"location": city, "apikey": TOMOR_KEY, "timesteps": "1d", "units": "imperial"},
            timeout=5
        ).json()
        temps.append(r["timelines"]["daily"][0]["values"]["temperatureMax"])
    except Exception as e:
        errs.append(f"TOMOR: {e}")

    if not temps:
        return None, " | ".join(errs)

    avg = round(sum(temps)/len(temps),1)
    spread = max(temps) - min(temps)
    info = f"Sources: {', '.join(f'{t}°F' for t in temps)} → Avg {avg}°F (±{spread/2:.1f})"
    return info, avg

def ask_gpt_prediction(question: str, weather_info: str) -> str:
    prompt = textwrap.dedent(f"""
        You are a high-accuracy prediction market analyst.

        Market Question:
        {question}

        Weather Forecast Summary:
        {weather_info}

        1) Identify the YES/NO prices in the question.
        2) Decide which outcome (Yes or No) is under-priced.
        3) Justify your choice using the forecast.
        4) Give a probability percentage.

        Reply as:
        - 🔮 Prediction: [Yes/No]
        - 📈 Probability: [xx%]
        - 🧠 Reasoning: [your brief reasoning]
    """).strip()

    resp = openai.ChatCompletion.create(
        model=MODEL_NAME,
        messages=[
            {"role":"system","content":"You are cautious but effective."},
            {"role":"user","content":prompt}
        ],
        temperature=0.3
    )
    return resp.choices[0].message.content.strip()

# ============ UI ============
uploaded = st.file_uploader("Upload Kalshi screenshot", type=["png","jpg","jpeg"])
if st.button("Analyze"):
    if not uploaded:
        st.warning("Please upload an image first.")
    else:
        with st.spinner("OCRing image…"):
            text = extract_text_from_image(uploaded.read())
        st.subheader("🔍 Extracted Text")
        st.write(text)

        # detect city
        city = ""
        for c in ["NYC","New York","Miami","Denver","Chicago","Austin","LA","Los Angeles"]:
            if c.lower() in text.lower():
                city = c
                break

        if not city:
            st.error("Couldn’t detect a city keyword in the text. Make sure it mentions one of: NYC, Miami, Denver, etc.")
        else:
            with st.spinner(f"Fetching forecast for {city}…"):
                winfo, avg = get_weather_forecast(city)
            if avg is None:
                st.error("Weather APIs all failed:\n" + winfo)
            else:
                st.subheader(f"🌡️ Forecast for {city}")
                st.write(winfo)

                with st.spinner("Asking GPT for a pick…"):
                    result = ask_gpt_prediction(text, winfo)
                st.subheader("📊 GPT’s Prediction")
                st.markdown(result)