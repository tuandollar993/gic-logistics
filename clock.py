import os
import sys
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def load_env(env_path):
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    load_env(BASE_DIR / '.env')

from app import create_app
from app.services.reminder_service import ReminderService

app = create_app()

def scheduled_deadline_check():
    with app.app_context():
        print('⏰ [CLOCK] Đang tự động rà soát deadline và gửi nhắc nhở hàng ngày...')
        ReminderService.run_daily_deadline_check()

def scheduled_sync_advances():
    with app.app_context():
        print('🔄 [CLOCK] Đang tự động đồng bộ dòng tiền tạm ứng từ Google Sheets...')
        try:
            from app.services.advance_service import auto_sync_active_months
            auto_sync_active_months()
            print('✅ [CLOCK] Đồng bộ dòng tiền tạm ứng hoàn tất!')
        except Exception as e:
            print(f'⚠️ [CLOCK] Lỗi đồng bộ Google Sheets: {e}')

if __name__ == '__main__':
    scheduler = BlockingScheduler()
    scheduler.add_job(scheduled_deadline_check, 'cron', hour=9, minute=0)
    # Tự động đồng bộ dòng tiền tạm ứng mỗi 15 phút
    scheduler.add_job(scheduled_sync_advances, 'interval', minutes=15)
    print('✅ [CLOCK] Đã kích hoạt APScheduler (Blocking):')
    print('   • Deadline Check: Hàng ngày lúc 09:00 AM')
    print('   • Google Sheets Sync: Tự động mỗi 15 phút')
    
    # Đồng bộ 1 lần ngay khi khởi động
    scheduled_sync_advances()
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
