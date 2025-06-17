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
    avg = round(sum(temps) / len(temps), 1)
    return f"Sources: {', '.join(f'{t}°F' for t in temps)} → Average {avg}°F"

def ask_gpt(question: str, weather_info: str):
    prompt = textwrap.dedent(f"""
        You are a prediction‐market analyst.  
        Use simple, friendly language and short bullets.

        Market Question:
        {question}

        Weather Forecast:
        {weather_info}

        1. Identify the YES/NO prices.
        2. Choose which side (Yes or No) is under-priced.
        3. Explain in one sentence why.
        4. Give a percentage chance.

        Reply exactly as:
        Prediction: [Yes or No]  
        Probability: [number%]  
        Reasoning: [one sentence]
    """).strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are concise and clear."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.3,
        max_tokens=150
    )
    return resp.choices[0].message.content.strip()

def parse_gpt_reply(reply: str):
    data = {"Prediction": "", "Probability": "", "Reasoning": ""}
    for line in reply.splitlines():
        for key in data:
            if line.lower().startswith(key.lower() + ":"):
                data[key] = line.split(":", 1)[1].strip()
    return data

# ============ UI ============
st.title("📸 Manual Kalshi Weather Analyzer")
st.write("Upload a screenshot of a Kalshi weather question (YES/NO prices). I'll OCR it, fetch forecasts, and get GPT’s pick.")

uploaded = st.file_uploader("Upload PNG/JPG", type=["png", "jpg", "jpeg"])
if st.button("Analyze") and uploaded:
    with st.spinner("Extracting text…"):
        text = extract_text(uploaded.read())
    st.subheader("📝 Extracted Question Text")
    st.write(text)

    # Detect city
    city = ""
    for c in ["NYC", "New York", "Miami", "Denver", "Chicago", "Austin", "LA", "Los Angeles"]:
        if c.lower() in text.lower():
            city = c
            break

    if not city:
        st.error("⚠️ Couldn't find a city. Make sure it mentions one of: NYC, Miami, Denver, etc.")
    else:
        with st.spinner(f"Fetching 3-source forecast for {city}…"):
            winfo = get_weather_forecast(city)
        if not winfo:
            st.error("⚠️ All weather APIs failed.")
        else:
            st.subheader(f"🌡️ Forecast for {city}")
            st.write(winfo)

            with st.spinner("Getting GPT prediction…"):
                raw = ask_gpt(text, winfo)
            parsed = parse_gpt_reply(raw)

            st.subheader("🔮 Prediction")
            st.markdown(f"**{parsed['Prediction']}**")

            st.subheader("📈 Estimated Probability")
            st.markdown(f"**{parsed['Probability']}**")

            st.subheader("🧠 Reasoning")
            st.write(parsed["Reasoning"])