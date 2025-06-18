import io
import os
import threading
import json
import textwrap

import numpy as np
import pandas as pd
import streamlit as st
import pytesseract
from PIL import Image
from openai import OpenAI
import websocket  # pip install websocket-client

# ── CONFIG ─────────────────────────────────────────────────────────────────────
st.set_page_config("3-City Temp Sniper", layout="wide")
secrets = st.secrets
client  = OpenAI(api_key=secrets["OPENAI_API_KEY"])
MODEL   = "gpt-4o"

LOG_FILE    = "predictions_log.csv"
GFS_FILE    = "gfs_ensemble.csv"
ECMWF_FILE  = "ecmwf_ensemble.csv"

CITY_COORDS = {
    "LA":    ("LA Airport",         "KLAX"),
    "NYC":   ("Central Park, NYC",  "USW00094728"),
    "MIAMI": ("Miami Int’l Airport","KMIA"),
}

# Initialize live‐price storage (no API keys)
if "live_yes" not in st.session_state:
    st.session_state["live_yes"] = {name: None for name, _ in CITY_COORDS.values()}

# ── WEBSOCKET CALLBACKS ─────────────────────────────────────────────────────────
def on_ws_message(ws, message):
    try:
        data = json.loads(message)
        market = data.get("market")
        yes_pct = data.get("yes")
        if market in st.session_state["live_yes"]:
            st.session_state["live_yes"][market] = float(yes_pct)
            # alert if our last_conf beats it
            conf = st.session_state.get("last_conf", 0.0)
            if conf and conf > yes_pct:
                st.toast(f"🚨 Edge on {market}: conf {conf:.1f}% > market {yes_pct:.1f}%")
    except:
        pass

def on_ws_open(ws):
    # subscribe to the three markets
    for market in st.session_state["live_yes"].keys():
        sub = {"action": "subscribe", "market": market}
        ws.send(json.dumps(sub))

def start_ws():
    ws = websocket.WebSocketApp(
        "wss://your-kalshi-websocket-endpoint",  # ← swap with real URL
        on_open=on_ws_open,
        on_message=on_ws_message,
    )
    ws.run_forever()

# fire up WS in background
threading.Thread(target=start_ws, daemon=True).start()

# ── OCR & CSV SIGNAL HELPERS ────────────────────────────────────────────────────
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
    members = [c for c in df.columns if c != "city"]
    out = {}
    for _, row in df.iterrows():
        temps = row[members].astype(float).tolist()
        out[row["city"]] = {
            "avg": round(np.mean(temps),1),
            "spread": round(max(temps)-min(temps),1),
        }
    return out

def get_signal(path):
    stats = load_csv_stats(path)
    return {name: stats.get(name,{}) for name, _ in CITY_COORDS.values()}

# ── (Stub) ML TRAINER & GPT PICKER ──────────────────────────────────────────────
def train_ml_model():
    # Stub: replace with your retraining logic
    return None, 0.72

def ask_gpt(city, summary, conf, market):
    st.session_state["last_conf"] = conf
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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Rows logged",    rows)
c2.metric("ML accuracy",    f"{ml_acc*100:.1f}%")
c3.metric("EV/day @ $100",  f"${ev_day:.1f}")
c4.metric("Live YES% (LA)", st.session_state["live_yes"]["LA Airport"] or "–")

# 2) Ensemble & physics signals summary
st.subheader("Ensemble Signals")
gfs   = get_signal(GFS_FILE)
ecmwf = get_signal(ECMWF_FILE)
cols  = st.columns(3)
for col, (code, (name, _)) in zip(cols, CITY_COORDS.items()):
    col.markdown(f"**{name}**")
    if gfs.get(name):
        col.write(f"GFS:   {gfs[name]['avg']}°F ±{gfs[name]['spread']}°")
    if ecmwf.get(name):
        col.write(f"ECMWF: {ecmwf[name]['avg']}°F ±{ecmwf[name]['spread']}°")

# 3) Screenshot uploader & GPT pick
st.subheader("Analyze a Kalshi Screenshot")
up = st.file_uploader("", type=["png","jpg","jpeg"])
if up:
    txt = extract_text(up.read())
    st.text_area("Extracted Text", txt, height=120)

    # route to one of the three cities
    city = None
    for code, (name, _) in CITY_COORDS.items():
        if code.lower() in txt:
            city = name
            break

    if not city:
        st.error("Unsupported market—only LA / NYC / Miami.")
    else:
        buckets = "\n".join(
            line for line in txt.splitlines() if "%" in line and "yes" in line
        )
        # placeholder summary + blended confidence (inject your logic here)
        summary = "Ensemble signals + live market sentiment"
        conf    = 60.0

        live_yes = st.session_state["live_yes"][city]
        st.metric("Live Market YES%", live_yes or "–", delta=f"Conf {conf:.1f}%")

        pick = ask_gpt(city, summary, conf, buckets)
        st.markdown(f"### 🎯 Bot’s Pick for {city}")
        st.write(pick)