import requests
import time
import os

TELEGRAM_BOT_TOKEN = os.getenv("NOC_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("NOC_TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Erro Telegram: {e}")
        pass

def telegram_health_check():

    if not TELEGRAM_BOT_TOKEN:
        return {"status": "ERROR", "message": "Token não configurado"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"

    try:
        start = time.time()

        response = requests.get(url, timeout=5)

        latency = round((time.time() - start) * 1000, 2)

        if response.status_code != 200:
            return {
                "status": "DOWN",
                "latency_ms": latency
            }

        data = response.json()

        if data.get("ok"):
            return {
                "status": "UP",
                "latency_ms": latency,
                "bot": data["result"]["username"]
            }

        return {
            "status": "ERROR",
            "latency_ms": latency
        }

    except Exception as e:
        return {
            "status": "DOWN",
            "message": str(e)
        }
