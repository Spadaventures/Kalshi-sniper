import streamlit as st
from PIL import Image
import io
import pytesseract
import requests
import textwrap
from openai import OpenAI

# ============ CONFIG ============
st.set_page_config(page_title="Weather Sniper (Manual Only)", layout="centered")

OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)
MODEL  = "gpt-4o"

# ============ HELPERS ============
def extract_text(img_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(img_bytes))
    return pytesseract.image_to_string(img)

def get_weather_forecast(city: str):
    temps = []
    # OpenWeather
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "imperial"},
            timeout=5
        ).json()
        block = r.get("list", [])[:8]
        if block:
            temps.append(max(x["main"]["temp"] for x in block))
    except:
        pass

    # WeatherAPI.com
    try:
        r = requests.get(
            "http://api.weatherapi.com/v1/forecast.json",
            params={"key": WEATHERAPI_KEY, "q": city, "days": 1},
            timeout=5
        ).json()
        temps.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except:
        pass

    # Tomorrow.io
    try:
        r = requests.get(
            "https://api.tomorrow.io/v4/weather/forecast",
            params={
                "location": city,
                "apikey": TOMORROWIO_API_KEY,
                "timesteps": "1d",
                "units": "imperial"
            },
            timeout=5
        ).json()
        temps.append(r["timelines"]["daily"][0]["values"]["temperatureMax"])
    except:
        pass

    if not temps:
        return None

    avg  = round(sum(temps) / len(temps), 1)
    desc = f"Sources: {', '.join(f'{t}°F' for t in temps)} → Avg {avg}°F"
    return desc

def ask_gpt(question: str, weather_info: str):
    prompt = textwrap.dedent(f"""
        You are a high-accuracy prediction market analyst.

        Market Question:
        {question}

        Weather Forecast:
        {weather_info}

        1) Identify the YES/NO prices.
        2) Decide which outcome is under-priced.
        3) Justify with the forecast.
        4) Give a probability percentage.

        Reply as:
        - 🔮 Prediction: [Yes/No]
        - 📈 Probability: [xx%]
        - 🧠 Reasoning: [why]
    """).strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are cautious but effective."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.3,
        max_tokens=200
    )
    return resp.choices[0].message.content.strip()

# ============ UI ============
st.title("📸 Manual Kalshi Weather Analyzer")
st.write("Upload a screenshot of a Kalshi weather question (YES/NO prices). I'll OCR it, fetch three forecasts, and get GPT's pick.")

uploaded = st.file_uploader("Upload PNG/JPG", type=["png","jpg","jpeg"])
if st.button("Analyze") and uploaded:
    with st.spinner("OCR in progress…"):
        text = extract_text(uploaded.read())
    st.subheader("📝 Extracted Text")
    st.write(text)

    # detect city
    city = ""
    for c in ["NYC","New York","Miami","Denver","Chicago","Austin","LA","Los Angeles"]:
        if c.lower() in text.lower():
            city = c
            break

    if not city:
        st.error("Couldn't detect any city keyword. Make sure it mentions one of: NYC, Miami, Denver, etc.")
    else:
        with st.spinner(f"Fetching forecast for {city}…"):
            winfo = get_weather_forecast(city)
        if not winfo:
            st.error("All weather APIs failed.")
        else:
            st.subheader(f"🌡️ Forecast for {city}")
            st.write(winfo)

            with st.spinner("Getting GPT prediction…"):
                result = ask_gpt(text, winfo)
            st.subheader("📊 GPT’s Prediction")
            st.markdown(result)