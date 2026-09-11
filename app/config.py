import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

class Config:
    IS_PRODUCTION = os.getenv('FLASK_ENV') == 'production' or os.getenv('ENVIRONMENT') == 'production' or bool(os.getenv('RENDER'))
    DEBUG = os.getenv('FLASK_DEBUG', '0') == '1' and not IS_PRODUCTION

    # Secret Key
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        if IS_PRODUCTION:
            raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is mandatory in production!")
        SECRET_KEY = 'dev-insecure-secret-key-change-me'

    # Webhook Secret
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
    if IS_PRODUCTION and not WEBHOOK_SECRET:
        raise RuntimeError("CRITICAL SECURITY ERROR: WEBHOOK_SECRET environment variable is mandatory in production!")

    # Bot Upload Secret (separate from WEBHOOK_SECRET and CASHFLOW_BOT_TOKEN)
    BOT_UPLOAD_SECRET = os.getenv('BOT_UPLOAD_SECRET', '')

    # Telegram Secret Token for Webhook Verification (X-Telegram-Bot-Api-Secret-Token)
    TELEGRAM_SECRET_TOKEN = os.getenv('TELEGRAM_SECRET_TOKEN', '')

    # Database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        if IS_PRODUCTION:
            raise RuntimeError("CRITICAL DATABASE ERROR: DATABASE_URL environment variable is mandatory in production!")
        db_url = f"sqlite:///{BASE_DIR / 'data' / 'gic.db'}"

    if db_url == "sqlite:///:memory:":
        pass
    elif db_url.startswith("sqlite:///") and not os.path.isabs(db_url.replace("sqlite:///", "")):
        db_path = BASE_DIR / db_url.replace("sqlite:///", "")
        db_url = f"sqlite:///{db_path}"
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 30,
        'pool_recycle': 1800,
        'pool_pre_ping': True,
    } if 'postgres' in db_url else {}

    # Session Cookie Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '1' if IS_PRODUCTION else '0') == '1'
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_MANAGER_CHAT_ID = os.getenv('TELEGRAM_MANAGER_CHAT_ID', '')
    CASHFLOW_BOT_TOKEN = os.getenv('CASHFLOW_BOT_TOKEN', '')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    ALLOWED_CHAT_IDS = [
        cid.strip() for cid in (os.getenv('ALLOWED_CHAT_IDS') or os.getenv('ALLOWED_CHAT_ID', '')).split(',')
        if cid.strip()
    ]
    # ALLOWED_CHAT_IDS is validated dynamically at request time in cashflow_bot_service

    # Uploads folder
    UPLOAD_FOLDER = BASE_DIR / 'data' / 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max
