import streamlit as st
import openai
import requests
from PIL import Image
import pytesseract
import io
from datetime import datetime, timedelta
from openai import OpenAI
import os
import csv
import json

# ============ CONFIG ============
openai.api_key = st.secrets["OPENAI_API_KEY"]
MODEL_NAME = "gpt-4o"
WEATHERAPI_KEY = st.secrets["WEATHERAPI_KEY"]
TOMORROWIO_API_KEY = st.secrets["TOMORROWIO_API_KEY"]
OPENWEATHER_API_KEY = st.secrets["WEATHER_API_KEY"]
KALSHI_API_KEY = st.secrets["KALSHI_API_KEY"]
KALSHI_KEY_ID = st.secrets["KALSHI_KEY_ID"]

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
st.markdown("Upload a **screenshot of a Kalshi question with its YES/NO prices**. I’ll extract it and tell you the most likely outcome.")
uploaded_file = st.file_uploader("Upload Kalshi Screenshot", type=["png", "jpg", "jpeg"])

