import requests
from flask import current_app

class TelegramService:
    @staticmethod
    def send_message(chat_id, text):
        """
        Sends a notification message to a Telegram user or group chat.
        Gracefully handles errors if bot token is not yet configured.
        """
        token = current_app.config.get('TELEGRAM_BOT_TOKEN')
        if not token or not chat_id:
            # Bot token or chat_id not configured, return False but don't crash
            return False, "Chưa cấu hình Telegram Bot Token hoặc Chat ID."
            
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=8)
            res_json = resp.json()
            if res_json.get('ok'):
                return True, "Thành công"
            else:
                return False, res_json.get('description', 'Telegram API error')
        except Exception as e:
            return False, str(e)
