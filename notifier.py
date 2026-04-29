import requests
import os

class TelegramNotifier:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')

    MAX_MSG_LEN = 4000  # 텔레그램 한도 4096에 여유분 적용

    def _split_message(self, text):
        """4000자 초과 시 단락 기준으로 분할"""
        if len(text) <= self.MAX_MSG_LEN:
            return [text]
        chunks = []
        current = ""
        for line in text.split('\n'):
            candidate = (current + '\n' + line).lstrip('\n')
            if len(candidate) > self.MAX_MSG_LEN:
                if current:
                    chunks.append(current)
                # 단일 줄이 MAX_MSG_LEN 초과하는 경우 강제 분할
                while len(line) > self.MAX_MSG_LEN:
                    chunks.append(line[:self.MAX_MSG_LEN])
                    line = line[self.MAX_MSG_LEN:]
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def send_message(self, text):
        if not self.token or not self.chat_id:
            print("Telegram credentials not found. Skipping notification.")
            print(f"Message: {text}")
            return

        chat_ids = [cid.strip() for cid in str(self.chat_id).split(',')]
        chunks = self._split_message(text)
        if len(chunks) > 1:
            print(f"메시지가 길어 {len(chunks)}개로 분할 전송합니다.")
        print(f"Sending message to {len(chat_ids)} recipient(s)...")
        results = []

        for cid in chat_ids:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            for i, chunk in enumerate(chunks, 1):
                payload = {
                    "chat_id": cid,
                    "text": chunk,
                    "parse_mode": "HTML"
                }
                try:
                    if len(chunks) > 1:
                        print(f"Attempting to send message part {i}/{len(chunks)} to ChatID: {cid}...")
                    else:
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
