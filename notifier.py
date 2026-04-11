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

        chat_ids = [cid.strip() for cid in str(self.chat_id).split(',')]
        print(f"Sending message to {len(chat_ids)} recipient(s)...")
        results = []

        for cid in chat_ids:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML"
            }
            try:
                print(f"Attempting to send message to ChatID: {cid}...")
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 400 and "parse_mode" in payload:
                    print(f"HTML parsing failed for {cid}. Retrying as plain text...")
                    payload.pop("parse_mode")
                    response = requests.post(url, json=payload, timeout=10)
                
                response.raise_for_status()
                print(f"✅ Successfully sent to {cid}")
                results.append(response.json())
            except Exception as e:
                print(f"❌ Failed to send to {cid}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"   Response from Telegram: {e.response.text}")
        
        return results

if __name__ == "__main__":
    # Test
    notifier = TelegramNotifier()
    notifier.send_message("<b>Stock Analyzer Test</b>\nThis is a test message.")
