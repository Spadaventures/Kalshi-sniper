import io, textwrap
import numpy as np
import requests
import streamlit as st
import pytesseract
from PIL import Image
from netCDF4 import Dataset
from openai import OpenAI

# ============ CONFIG & SECRETS ============
st.set_page_config(page_title="Temp-Only Sniper", layout="centered")
OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)
MODEL  = "gpt-4o"

# ============ HRRR NOWCAST ============
import datetime
CITY_COORDS = {
    "LA":        (34.05, -118.25),
    "New York": (40.71,  -74.01),
    "Miami":     (25.77,  -80.19),
}

def get_hrrr_nowcast(city: str) -> float:
    lat, lon = CITY_COORDS[city]
    now      = datetime.datetime.utcnow()
    ds_date  = now.strftime("%Y%m%d")
    hr_cycle = f"{now.hour:02d}00"
    url = (
      f"https://thredds.ncep.noaa.gov/thredds/dodsC/"
      f"hrrr/hrrr_sfc/hrrr_sfc_{ds_date}/"
      f"hrrr.t{hr_cycle}.sfc.grib2"
    )
    try:
        ds   = Dataset(url)
        refl = ds.variables["REFL_L8"]   # [time, lat, lon]
        lats = ds.variables["lat"][:]
        lons = ds.variables["lon"][:]
        i = np.abs(lats - lat).argmin()
        j = np.abs(lons - lon).argmin()
        radar = refl[1,:,:]  # 1-hour forecast
        win = radar[
            max(0,i-2):min(i+3,radar.shape[0]),
            max(0,j-2):min(j+3,radar.shape[1])
        ]
        pct = float(np.mean(win > 30.0))  # >30 dBZ
        ds.close()
        return pct
    except:
        return 0.0

# ============ WEATHER & NOWCAST ============
def extract_text(img_bytes: bytes) -> str:
    return pytesseract.image_to_string(Image.open(io.BytesIO(img_bytes)))

def get_weather_ensemble(city: str):
    temps = []
    # OpenWeather
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "imperial"},
            timeout=5
        ).json()
        block = r.get("list", [])[:8]
        temps.append(max(e["main"]["temp"] for e in block))
    except: pass
    # WeatherAPI.com
    try:
        r = requests.get(
            "http://api.weatherapi.com/v1/forecast.json",
            params={"key": WEATHERAPI_KEY, "q": city, "days": 1},
            timeout=5
        ).json()
        temps.append(r["forecast"]["forecastday"][0]["day"]["maxtemp_f"])
    except: pass
    if not temps:
        return None, 0.0
    avg    = round(sum(temps)/len(temps), 1)
    spread = max(temps) - min(temps)
    raw    = max(10, min(100, 50 + (avg - 75)*3 - spread*2))
    return (avg, spread, temps), raw

def get_precip_nowcast(city: str) -> float:
    try:
        r = requests.get(
            "https://api.tomorrow.io/v4/timelines",
            params={
                "location": city,
                "apikey": TOMORROWIO_API_KEY,
                "fields": ["precipitationIntensity"],
                "timesteps": ["1m"],
                "units": "imperial"
            },
            timeout=5
        ).json()
        iv = r["data"]["timelines"][0]["intervals"]
        cnt = sum(1 for x in iv if x["values"]["precipitationIntensity"] > 0.02)
        return cnt / len(iv)
    except:
        return 0.0

# ============ GPT PROMPT ============
def ask_gpt(question: str, confidence: float) -> str:
    prompt = textwrap.dedent(f"""
        You are a prediction-market analyst.
        Final blended confidence: {confidence:.1f}%.

        Market Question:
        {question}

        Please reply **exactly** as:
        Range: [e.g. 75°–76°]
        Side: [Yes or No]
        Probability: [xx%]
        Reasoning: [one sentence]
    """).strip()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role":"system","content":"Be concise and clear."},
            {"role":"user","content":prompt}
        ],
        temperature=0.3,
        max_tokens=150
    )
    return resp.choices[0].message.content.strip()

def parse_reply(txt: str):
    out = {"Range":"","Side":"","Probability":"","Reasoning":""}
    for L in txt.splitlines():
        for k in out:
            if L.lower().startswith(k.lower()+":"):
                out[k] = L.split(":",1)[1].strip()
    return out

# ============ STREAMLIT UI ============
st.title("🌡️ Temp-Only Kalshi Sniper")

st.markdown("""
Upload a **screenshot** of a “Highest temperature in X” Kalshi market  
— only **LA, New York, Miami** are supported.
""")

uploaded = st.file_uploader("PNG/JPG screenshot", type=["png","jpg","jpeg"])
if st.button("Analyze") and uploaded:
    text = extract_text(uploaded.read())
    st.subheader("📝 Extracted Text")
    st.write(text)

    txt_l = text.lower()
    if "highest temperature" not in txt_l:
        st.error("❌ This bot only handles “Highest temperature” markets.")
    else:
        city = next((c for c in ["LA","New York","Miami"] if c.lower() in txt_l), "")
        if not city:
            st.error("❌ Only LA, New York or Miami are supported.")
        else:
            (avg, spread, temps), raw = get_weather_ensemble(city)
            nowc = get_precip_nowcast(city)
            hrrr = get_hrrr_nowcast(city)

            st.write(f"🌡️ Temps: {temps} → avg {avg}°F, spread {spread:.1f}°")
            st.write(f"⛈️ Nowcast rain %: {nowc*100:.1f}%")
            st.write(f"🌪️ HRRR storm %:  {hrrr*100:.1f}%")

            # Blend: 60% raw, 15% nowcast, 15% HRRR
            final_conf = raw*0.6 + nowc*100*0.15 + hrrr*100*0.15
            st.write(f"🎯 Blended confidence: {final_conf:.1f}%")

            reply = ask_gpt(text, final_conf)
            out   = parse_reply(reply)

            st.subheader("🔮 Range")
            st.write(out["Range"])
            st.subheader("👍 Side")
            st.write(out["Side"])
            st.subheader("📈 Probability")
            st.write(out["Probability"])
            st.subheader("🧠 Reasoning")
            st.write(out["Reasoning"])