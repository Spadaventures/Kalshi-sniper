# live_sniper.py

import json
import csv
import threading
from datetime import datetime
import websocket  # websocket-client

# === CONFIGURATION ===
SLUGS = [
    "kxhighlax-25jun19",   # LAX airport
    "kxhighny-25jun19",    # NYC Central Park
    "kxhighmia-25jun19"    # Miami Intl
]
WS_URL    = "wss://stream.kalshi.com/v1/feed"
LOG_FILE  = "market_log.csv"

# === WEB SOCKET CALLBACKS ===
def on_open(ws):
    """Subscribe to the prices channel for each market slug."""
    for slug in SLUGS:
        ws.send(json.dumps({
            "action":  "subscribe",
            "channel": "prices",
            "market":  slug
        }))

def on_message(ws, raw_msg):
    """Called on each incoming message — log YES% for our markets."""
    try:
        msg = json.loads(raw_msg)
        if msg.get("channel") == "prices" and msg.get("market") in SLUGS:
            yes_pct   = float(msg.get("yes", 0.0))
            timestamp = datetime.utcnow().isoformat()
            with open(LOG_FILE, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, msg["market"], yes_pct])
    except Exception:
        # you might log parsing errors here
        pass

def on_error(ws, error):
    """Handle or log errors."""
    print("WebSocket error:", error)

# === LOG FILE INITIALIZATION ===
# If the CSV doesn't exist yet, create it with headers
try:
    with open(LOG_FILE, "x", newline="") as f:
        csv.writer(f).writerow(["timestamp","slug","yes_pct"])
except FileExistsError:
    pass  # already initialized

# === MAIN ENTRYPOINT ===
if __name__ == "__main__":
    ws_app = websocket.WebSocketApp(
        WS_URL,
        on_open    = on_open,
        on_message = on_message,
        on_error   = on_error
    )
    # Run WebSocket in background thread so the main thread stays alive
    threading.Thread(target=ws_app.run_forever, daemon=True).start()

    print("🔴 Live 3-City Temp Sniper is running. Writing to", LOG_FILE)
    try:
        # Keep main thread alive indefinitely
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down.")
        ws_app.close()