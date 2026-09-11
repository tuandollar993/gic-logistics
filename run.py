import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Built-in fallback .env loader
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
from app.extensions import db
from app.services.reminder_service import ReminderService
from apscheduler.schedulers.background import BackgroundScheduler

app = create_app()

def init_scheduler():
    scheduler = BackgroundScheduler(daemon=True)
    def scheduled_deadline_check():
        with app.app_context():
            print("⏰ Đang tự động rà soát deadline và gửi nhắc nhở hàng ngày...")
            ReminderService.run_daily_deadline_check()

    def scheduled_sync_advances():
        with app.app_context():
            print("🔄 [RUN] Đang tự động đồng bộ dòng tiền tạm ứng từ Google Sheets...")
            try:
                from app.services.advance_service import auto_sync_active_months
                auto_sync_active_months()
                print("✅ [RUN] Đồng bộ dòng tiền tạm ứng hoàn tất!")
            except Exception as e:
                print(f"⚠️ [RUN] Lỗi đồng bộ Google Sheets: {e}")

    scheduler.add_job(scheduled_deadline_check, 'cron', hour=9, minute=0)
    scheduler.add_job(scheduled_sync_advances, 'interval', minutes=15)
    scheduler.start()
    print("✅ Đã kích hoạt APScheduler:")
    print("   • Rà soát deadline: Hàng ngày vào lúc 09:00 AM")
    print("   • Đồng bộ dòng tiền tạm ứng: Mỗi 15 phút")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
    init_scheduler()
    
    print("\n" + "=" * 70)
    print("🚀 HỆ THỐNG DASHBOARD & QUẢN LÝ VẬN HÀNH GIC ĐANG CHẠY TẠI:")
    print("👉 http://127.0.0.1:5000")
    print("👉 http://localhost:5000")
    print("=" * 70)
    print("Tài khoản đăng nhập Quản trị:")
    print("• Quản lý:  admin       / pass: admin123")
    print("• Nhân viên: Quản lý thêm tài khoản nhân viên tại tab 'Quản Lý Nhân Viên'")
    print("=" * 70 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
