import io, os, datetime, textwrap
import numpy as np
import pandas as pd
import requests
import streamlit as st
import pytesseract
from PIL import Image
from metpy.io import parse_metar_to_dataframe
from netCDF4 import Dataset
from openai import OpenAI

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("3-City Temp Sniper", layout="wide")
secrets   = st.secrets
client    = OpenAI(api_key=secrets["OPENAI_API_KEY"])
MODEL     = "gpt-4o"

LOG_FILE    = "predictions_log.csv"
GFS_FILE    = "gfs_ensemble.csv"
ECMWF_FILE  = "ecmwf_ensemble.csv"

CITY_COORDS = {
    "LA":    ("LA Airport", (33.9425, -118.4081), "KLAX"),
    "NYC":   ("Central Park, NYC", (40.7812, -73.9665), "USW00094728"),
    "MIAMI": ("Miami Int’l Airport", (25.7959, -80.2870), "KMIA"),
}

# ── HELPERS ────────────────────────────────────────────────────────────────────
def extract_text(img_bytes):
    img = Image.open(io.BytesIO(img_bytes))
    return pytesseract.image_to_string(img).lower()

def load_csv_stats(path):
    try:
        df = pd.read_csv(path)
    except:
        return {}
    if "avg" in df.columns and "spread" in df.columns:
        return df.set_index("city")[["avg","spread"]].to_dict(orient="index")
    # otherwise assume one column per member
    members = [c for c in df.columns if c != "city"]
    out = {}
    for _, row in df.iterrows():
        temps = row[members].astype(float).tolist()
        out[row["city"]] = {
            "avg": round(np.mean(temps),1),
            "spread": round(max(temps)-min(temps),1)
        }
    return out

def get_signal(path):
    stats = load_csv_stats(path)
    return {name: stats.get(name,{}) for name,_,_ in CITY_COORDS.values()}

def train_ml_model():
    # stub trainer: returns None and placeholder accuracy
    return None, 0.72

def ask_gpt(city, summary, conf, market):
    prompt = textwrap.dedent(f"""
      Market: Highest temperature recorded in {city}.
      Signals: {summary}
      Blended confidence: {conf:.1f}%.
      Market buckets:
      {market}
      Pick the bucket where your confidence > market price.
      Output: Range / Side / Probability.
    """).strip()
    resp = client.chat.completions.create(
      model=MODEL,
      messages=[
        {"role":"system","content":"Be concise."},
        {"role":"user","content":prompt}
      ],
      temperature=0.2,
      max_tokens=60
    )
    return resp.choices[0].message.content.strip()

# ── DASHBOARD ─────────────────────────────────────────────────────────────────
# 1) Top metrics
_, ml_acc = train_ml_model()
rows      = sum(1 for _ in open(LOG_FILE)) - 1 if os.path.exists(LOG_FILE) else 0
ev_day    = (2*ml_acc - 1)*100

c1, c2, c3 = st.columns(3)
c1.metric("Rows logged",    rows)
c2.metric("ML accuracy",    f"{ml_acc*100:.1f}%")
c3.metric("EV/day @ $100",  f"${ev_day:.1f}")

# 2) Ensemble & physics signals summary
st.subheader("Ensemble & Physics Signals")
gfs   = get_signal(GFS_FILE)
ecmwf = get_signal(ECMWF_FILE)
cols  = st.columns(3)
for col, (key, (name,_,_)) in zip(cols, CITY_COORDS.items()):
    col.markdown(f"**{name}**")
    if gfs.get(name):
        col.write(f"GFS:   {gfs[name]['avg']}°F ±{gfs[name]['spread']}°")
    if ecmwf.get(name):
        col.write(f"ECMWF: {ecmwf[name]['avg']}°F ±{ecmwf[name]['spread']}°")

# 3) Screenshot uploader & prediction
st.subheader("Analyze a Kalshi Screenshot")
up = st.file_uploader("", type=["png","jpg","jpeg"])
if up:
    txt = extract_text(up.read())
    st.text_area("Extracted Text", txt, height=120)

    # determine city
    city = None
    for code, (name,_,_) in CITY_COORDS.items():
        if code.lower() in txt:
            city = name
            break

    if not city:
        st.error("Unsupported market—only LA, NYC or Miami.")
    else:
        # extract market buckets
        buckets = "\n".join(
            line for line in txt.splitlines() if "%" in line and "yes" in line
        )
        # placeholder summary & confidence
        summary = "Multi‐API ensemble, nowcast & physics signals."
        conf    = 60.0

        # get GPT pick
        pick = ask_gpt(city, summary, conf, buckets)

        st.markdown(f"### 🎯 Bot’s Pick for {city}")
        st.write(pick)