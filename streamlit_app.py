import io, textwrap, datetime
import numpy as np
import requests
import streamlit as st
import pytesseract
from PIL import Image
from netCDF4 import Dataset
from metpy.io import parse_metar_to_dataframe
from openai import OpenAI

# ============ CONFIG & SECRETS ============
st.set_page_config(page_title="Temp-Only Sniper v2", layout="centered")

OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]

client    = OpenAI(api_key=OPENAI_API_KEY)
MODEL     = "gpt-4o"

# City → (lat, lon, ICAO)
CITY_COORDS = {
    "LA":        (34.05, -118.25, "KLAX"),
    "New York": (40.71,  -74.01, "KJFK"),
    "Miami":     (25.77,  -80.19, "KMIA"),
}

# ============ OCR & WEATHER ============

def extract_text(img_bytes: bytes) -> str:
    return pytesseract.image_to_string(Image.open(io.BytesIO(img_bytes)))

def get_weather_ensemble(city: str):
    temps = []
    # OpenWeather 5-day forecast (next 8 entries ≈ 24h)
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "imperial"},
            timeout=5
        ).json()
        block = r.get("list", [])[:8]
        temps.append(max(e["main"]["temp"] for e in block))
    except: pass

    # WeatherAPI.com 1-day forecast
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

def get_hrrr_nowcast(city: str) -> float:
    lat, lon, _ = CITY_COORDS[city]
    now       = datetime.datetime.utcnow()
    date_str  = now.strftime("%Y%m%d")
    cycle_str = f"{now.hour:02d}00"
    url = (
      f"https://thredds.ncep.noaa.gov/thredds/dodsC/"
      f"hrrr/hrrr_sfc/hrrr_sfc_{date_str}/"
      f"hrrr.t{cycle_str}.sfc.grib2"
    )
    try:
        ds   = Dataset(url)
        refl = ds.variables["REFL_L8"]  # [time,lat,lon]
        lats = ds.variables["lat"][:]
        lons = ds.variables["lon"][:]
        i = np.abs(lats - lat).argmin()
        j = np.abs(lons - lon).argmin()
        radar_slice = refl[1, :, :]
        win = radar_slice[
            max(0, i-2):min(i+3, radar_slice.shape[0]),
            max(0, j-2):min(j+3, radar_slice.shape[1])
        ]
        pct = float(np.mean(win > 30.0))  # >30 dBZ
        ds.close()
        return pct
    except:
        return 0.0

def get_metar(city: str):
    _, _, icao = CITY_COORDS[city]
    try:
        txt = requests.get(
            f"https://tgftp.nws.noaa.gov/data/observations/metar/stations/{icao}.TXT",
            timeout=5
        ).text
        df  = parse_metar_to_dataframe(io.StringIO(txt))
        row = df.iloc[-1]
        return row["temp"], row["dewpoint"], row["wind_speed"]
    except:
        return None, None, None

# ============ GPT PROMPT ============

def ask_gpt(question: str, confidence: float) -> str:
    prompt = textwrap.dedent(f"""
        You are a prediction-market analyst.
        Final blended confidence: {confidence:.1f}%.

        Market Question:
        {question}

        Reply exactly:
        Range: [e.g. 75°–76°]
        Side: [Yes or No]
        Probability: [xx%]
        Reasoning: [one sentence]
    """).strip()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Be concise and clear."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.3,
        max_tokens=150
    )
    return resp.choices[0].message.content.strip()

def parse_reply(txt: str):
    out = {"Range":"", "Side":"", "Probability":"", "Reasoning":""}
    for L in txt.splitlines():
        for k in out:
            if L.lower().startswith(k.lower()+":"):
                out[k] = L.split(":",1)[1].strip()
    return out

# ============ STREAMLIT UI ============

st.title("🌡️ Temp-Only Sniper v2")

st.markdown("""
Upload a **screenshot** of a “Highest temperature in X” Kalshi market.  
Supported: **LA**, **New York**, **Miami** only.
""")

uploaded = st.file_uploader("PNG/JPG screenshot", type=["png","jpg","jpeg"])
if st.button("Analyze") and uploaded:
    text = extract_text(uploaded.read())
    st.subheader("📝 Extracted Text")
    st.write(text)

    tl = text.lower()
    if "highest temperature" not in tl:
        st.error("This bot only handles “Highest temperature” markets.")
    else:
        city = next((c for c in CITY_COORDS if c.lower() in tl), "")
        if not city:
            st.error("Only LA, New York or Miami are supported.")
        else:
            # Fetch signals
            (avg, spread, temps), raw = get_weather_ensemble(city)
            nowc = get_precip_nowcast(city)
            hrrr = get_hrrr_nowcast(city)
            mt, dp, ws = get_metar(city)

            # Display them
            st.write(f"🌡️ Temps: {temps} → avg {avg}°F, spread {spread:.1f}°")
            st.write(f"⛈️ Nowcast rain: {nowc*100:.1f}%")
            st.write(f"🌪️ HRRR storm: {hrrr*100:.1f}%")
            if mt is not None:
                st.write(f"✈️ METAR (°C): temp {mt:.1f}, dew {dp:.1f}, wind {ws:.0f} kt")

            # Blend: 60% weather raw, 15% nowcast, 15% HRRR
            final_conf = raw*0.6 + nowc*100*0.15 + hrrr*100*0.15
            st.write(f"🎯 Blended confidence: {final_conf:.1f}%")

            # GPT pick
            raw_reply = ask_gpt(text, final_conf)
            out       = parse_reply(raw_reply)

            st.subheader("🔮 Prediction")
            st.write(f"**Range:** {out['Range']}")
            st.write(f"**Side:** {out['Side']}")
            st.write(f"**Probability:** {out['Probability']}")
            st.write(f"**Reasoning:** {out['Reasoning']}")