import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'gic-secret-key-2026-secure')
    
    # Database
    db_url = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'data' / 'gic.db'}")
    if db_url.startswith("sqlite:///") and not os.path.isabs(db_url.replace("sqlite:///", "")):
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
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_MANAGER_CHAT_ID = os.getenv('TELEGRAM_MANAGER_CHAT_ID', '')
    
    # Uploads folder
    UPLOAD_FOLDER = BASE_DIR / 'data' / 'uploads'
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32MB max
