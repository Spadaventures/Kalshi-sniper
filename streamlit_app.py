import os
import io
import textwrap
import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st
import pytesseract
from PIL import Image
from netCDF4 import Dataset
from metpy.io import parse_metar_to_dataframe
from openai import OpenAI
import joblib

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, RandomizedSearchCV

# ============ CONFIG & SECRETS ============
st.set_page_config(page_title="Temp-Only Sniper v3", layout="centered")

OPENAI_API_KEY     = st.secrets["OPENAI_API_KEY"]
WEATHER_API_KEY    = st.secrets["WEATHER_API_KEY"]
WEATHERAPI_KEY     = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)
MODEL   = "gpt-4o"

LOG_FILE   = "predictions_log.csv"
MODEL_FILE = "bet_model_tuned.pkl"

# City → (lat, lon, ICAO)
CITY_COORDS = {
    "LA":        (34.05, -118.25, "KLAX"),
    "New York": (40.71,  -74.01, "KJFK"),
    "Miami":     (25.77,  -80.19, "KMIA"),
}

# ============ OCR & SIGNAL FUNCTIONS ============

def extract_text(img_bytes: bytes) -> str:
    return pytesseract.image_to_string(Image.open(io.BytesIO(img_bytes)))

def get_weather_ensemble(city: str):
    temps = []
    # OpenWeather 24h high
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "imperial"},
            timeout=5
        ).json()
        block = r.get("list", [])[:8]
        temps.append(max(e["main"]["temp"] for e in block))
    except: pass

    # WeatherAPI.com 1-day high
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
    now         = datetime.datetime.utcnow()
    date_str    = now.strftime("%Y%m%d")
    cycle_str   = f"{now.hour:02d}00"
    url = (
        f"https://thredds.ncep.noaa.gov/thredds/dodsC/"
        f"hrrr/hrrr_sfc/hrrr_sfc_{date_str}/"
        f"hrrr.t{cycle_str}.sfc.grib2"
    )
    try:
        ds   = Dataset(url)
        refl = ds.variables["REFL_L8"]    # [time,lat,lon]
        lats = ds.variables["lat"][:]
        lons = ds.variables["lon"][:]
        i = np.abs(lats - lat).argmin()
        j = np.abs(lons - lon).argmin()
        radar = refl[1, :, :]             # 1-h forecast
        win   = radar[
            max(0, i-2):min(i+3, radar.shape[0]),
            max(0, j-2):min(j+3, radar.shape[1])
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

# ============ AUTOMATIC HYPERPARAMETER TUNING & RETRAINING ============

def train_ml_model():
    if not os.path.exists(LOG_FILE):
        return None, None

    df = pd.read_csv(LOG_FILE).dropna(subset=["actual_outcome"])
    if len(df) < 10:
        return None, None

    # features
    df["nowcast_pct_f"]    = df["nowcast_pct"].astype(float)
    df["blend_conf_f"]     = df["blend_conf"].astype(float)
    df["weather_avg_f"]    = df["weather_avg"].astype(float)
    df["weather_spread_f"] = df["weather_spread"].astype(float)
    df["market_yes_pct_f"] = df["market_yes_pct"].astype(float)
    df["side_bin"]         = (df["gpt_side"] == "Yes").astype(int)
    df["win"]              = ((df["gpt_range"] == df["actual_outcome"]) & (df["side_bin"]==1)).astype(int)

    X = df[["weather_avg_f","weather_spread_f","nowcast_pct_f","blend_conf_f","market_yes_pct_f","side_bin"]]
    y = df["win"]

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)

    param_dist = {
        "n_estimators":    [100,200,300,400],
        "max_depth":       [None,5,10,20],
        "min_samples_split":[2,5,10],
        "min_samples_leaf":[1,2,4],
        "max_features":    ["auto","sqrt","log2"]
    }

    search = RandomizedSearchCV(
        RandomForestClassifier(random_state=42),
        param_distributions=param_dist,
        n_iter=20, cv=3, scoring="accuracy",
        n_jobs=-1, random_state=42
    )
    search.fit(Xtr, ytr)
    best = search.best_estimator_
    acc  = best.score(Xte, yte)

    joblib.dump(best, MODEL_FILE)
    return best, acc

# ============ GPT PROMPTING ============

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

# ============ BOOTSTRAP & UI ============

with st.spinner("🔧 Tuning & retraining model…"):
    clf, ml_acc = train_ml_model()

rows    = sum(1 for _ in open(LOG_FILE)) - 1 if os.path.exists(LOG_FILE) else 0
base_acc = ml_acc if ml_acc is not None else 0.72
ev_day   = (2*base_acc - 1)*100
ev_mon   = ev_day * 30

st.metric("📊 Logged rows", rows)
if ml_acc is not None:
    st.metric("🤖 ML accuracy", f"{ml_acc*100:.1f}%")
st.metric("🔮 Est. accuracy", f"{base_acc*100:.1f}%")
st.metric("💵 EV/day (@100)", f"${ev_day:.1f}", delta=f"${ev_mon:.0f}/mo")

st.title("🌡️ Temp-Only Sniper v3")
st.markdown("Upload a screenshot of “Highest temperature in X” (LA/NYC/Miami).")

up = st.file_uploader("PNG/JPG screenshot", type=["png","jpg","jpeg"])
if st.button("Analyze") and up:
    text = extract_text(up.read())
    st.subheader("📝 Extracted Text")
    st.write(text)

    if "highest temperature" not in text.lower():
        st.error("This bot only handles Highest temperature markets.")
    else:
        city = next((c for c in CITY_COORDS if c.lower() in text.lower()), "")
        if not city:
            st.error("Only LA, New York or Miami supported.")
        else:
            (avg, spread, temps), raw = get_weather_ensemble(city)
            nowc = get_precip_nowcast(city)
            hrrr = get_hrrr_nowcast(city)
            mt, dp, ws = get_metar(city)

            st.write(f"🌡️ Temps: {temps} → avg {avg}°F, spread {spread:.1f}°")
            # nowc & hrrr are blended in but not shown
            if mt is not None:
                st.write(f"✈️ METAR °C: {mt:.1f}, dew {dp:.1f}, wind {ws:.0f} kt")

            final_conf = raw*0.6 + nowc*100*0.15 + hrrr*100*0.15
            st.write(f"🎯 Blended confidence: {final_conf:.1f}%")

            raw_reply = ask_gpt(text, final_conf)
            out       = parse_reply(raw_reply)

            st.subheader("🔮 Prediction")
            st.write(f"**Range:** {out['Range']}")
            st.write(f"**Side:** {out['Side']}")
            st.write(f"**Probability:** {out['Probability']}")
            st.write(f"**Reasoning:** {out['Reasoning']}")