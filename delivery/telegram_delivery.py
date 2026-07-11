"""
BioSetu - Layer 5: Telegram Delivery
----------------------------------------
Sends the generated farmer advisory (Layer 4 output) to a Telegram
chat/bot. Adapted from the working WildRakshak Telegram delivery
pattern, using environment variables instead of hardcoded credentials
(the hardcoded-token issue flagged in the WildRakshak audit must
never be repeated here).

Requires: pip install requests python-dotenv
Setup:
  1. Create a bot via @BotFather on Telegram, get the bot token.
  2. Message your bot once, then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id.
  3. Add both to your .env file:
       TELEGRAM_BOT_TOKEN=...
       TELEGRAM_CHAT_ID=...
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def send_telegram_message(message: str, bot_token: str = None, chat_id: str = None):
    """
    Sends a plain-text message to Telegram. Returns a dict with
    success status — never raises, so a delivery failure never
    crashes the rest of the pipeline (mirrors the graceful-fallback
    philosophy used in the advisory layer).
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat:
        return {
            "success": False,
            "error": "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID "
                     "(set them in your .env file).",
        }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": message, "parse_mode": "HTML"}

    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return {"success": True, "response": response.json()}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}


def format_alert_message(field_report: dict, advisory: dict) -> str:
    """
    Builds a clean, human-readable HTML-formatted Telegram message
    combining the readiness score, early warning level, and the
    Gemini-generated plain-language advisory.
    """
    readiness = field_report["readiness"]
    warning = field_report["early_warning"]
    loc = field_report["location"]

    level_emoji = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "LOW": "🟡",
        "NONE": "🟢",
        "UNKNOWN": "⚪",
    }.get(warning["level"], "⚪")

    text = (
        f"<b>🌾 BioSetu Field Report</b>\n"
        f"📍 Location: {loc['lat']}, {loc['lon']}\n\n"
        f"<b>Readiness Score:</b> {readiness['score']}/100 "
        f"(confidence: {readiness['confidence']}%)\n"
        f"<b>Early Warning:</b> {level_emoji} {warning['level']}\n\n"
        f"<b>Advisory ({advisory['language']}):</b>\n{advisory['message']}\n\n"
        f"<i>Source: {advisory['source']}</i>"
    )
    return text


def send_field_alert(field_report: dict, advisory: dict, bot_token: str = None, chat_id: str = None):
    """Convenience wrapper: formats and sends in one call."""
    message = format_alert_message(field_report, advisory)
    return send_telegram_message(message, bot_token, chat_id)


if __name__ == "__main__":
    # Example test using the real output structure from earlier runs
    example_report = {
        "location": {"lat": 30.15, "lon": 78.78},
        "readiness": {"score": 100.0, "confidence": 100.0},
        "early_warning": {
            "level": "HIGH",
            "reason": "Sustained heavy rainfall expected (48.2mm total) — waterlogging risk over coming days.",
        },
    }
    example_advisory = {
        "message": "जैविक दवा छिड़कने के लिए अभी का समय बहुत अच्छा है।",
        "language": "Hindi",
        "source": "gemini (gemini-flash-latest)",
    }

    result = send_field_alert(example_report, example_advisory)
    print(result)
