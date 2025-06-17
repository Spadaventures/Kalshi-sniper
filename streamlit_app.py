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
    return f"Sources: {', '.join(f'{t}°F' for t in temps)} → Avg {avg}°F"

def ask_gpt(question: str, weather_info: str) -> str:
    prompt = textwrap.dedent(f"""
        You are a prediction‐market analyst.  
        Use simple, friendly language and give me exactly:

        1) The **Range** to pick (e.g. "75° to 76°")  
        2) The **Side** ("Yes" or "No")  
        3) A **Probability** (e.g. "68%")  
        4) A one‐sentence **Reasoning**.

        Format your reply **exactly** like this (with no extra text):

        Range: [your range]  
        Side: [Yes or No]  
        Probability: [xx%]  
        Reasoning: [one sentence]

        Market Question:  
        {question}

        Weather Forecast:  
        {weather_info}
    """).strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role":"system","content":"You are concise and clear."},
            {"role":"user",  "content":prompt}
        ],
        temperature=0.3,
        max_tokens=200
    )
    return resp.choices[0].message.content.strip()

def parse_reply(reply: str):
    out = {"Range":"", "Side":"", "Probability":"", "Reasoning":""}
    for line in reply.splitlines():
        for key in out:
            if line.lower().startswith(key.lower() + ":"):
                out[key] = line.split(":",1)[1].strip()
    return out

# ============ UI ============
st.title("📸 Weather Range Picker")

st.write(
    "Upload a screenshot of a Kalshi weather market (with **all** the YES/NO price ranges).  \n"
    "I’ll OCR it, fetch three forecasts, then tell you exactly **which range** to pick, **Yes or No**, and **how likely** it is."
)

uploaded = st.file_uploader("Upload PNG/JPG", type=["png","jpg","jpeg"])

if st.button("Analyze") and uploaded:
    with st.spinner("Extracting text…"):
        text = extract_text(uploaded.read())
    st.subheader("📝 Extracted Question Text")
    st.write(text)

    # detect city keyword
    city = ""
    for c in ["NYC","New York","Miami","Denver","Chicago","Austin","LA","Los Angeles"]:
        if c.lower() in text.lower():
            city = c
            break

    if not city:
        st.error("⚠️ Couldn't find any city keyword—make sure it mentions NYC, Miami, Denver, etc.")
    else:
        with st.spinner(f"Fetching 3‐source forecast for {city}…"):
            forecast = get_weather_forecast(city)
        if not forecast:
            st.error("⚠️ All weather APIs failed.")
        else:
            st.subheader(f"🌡️ Forecast for {city}")
            st.write(forecast)

            with st.spinner("Running GPT…"):
                raw = ask_gpt(text, forecast)
            parsed = parse_reply(raw)

            st.subheader("🔮 Pick this range")
            st.markdown(f"**{parsed['Range']}**")

            st.subheader("👍 Side to bet")
            st.markdown(f"**{parsed['Side']}**")

            st.subheader("📈 Probability")
            st.markdown(f"**{parsed['Probability']}**")

            st.subheader("🧠 Why")
            st.write(parsed['Reasoning'])