import requests
import os

class TelegramNotifier:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')

    def send_message(self, text):
        if not self.token or not self.chat_id:
            print("Telegram credentials not found. Skipping notification.")
            print(f"Message: {text}")
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")
            return None

if __name__ == "__main__":
    # Test
    notifier = TelegramNotifier()
    notifier.send_message("<b>Stock Analyzer Test</b>\nThis is a test message.")
