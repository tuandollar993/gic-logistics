import os
import sys
import subprocess

port = os.getenv('PORT', '5000')

print('🚀 [STARTUP] Đang khởi động GIC Logistics All-in-One (Web + Bot + Clock)...')

bot_proc = None
if os.getenv('TELEGRAM_BOT_TOKEN'):
    print('🤖 [STARTUP] Kích hoạt Telegram Bot background...')
    bot_proc = subprocess.Popen([sys.executable, 'bot/telegram_bot.py'])
else:
    print('⚠️ [STARTUP] Chưa có TELEGRAM_BOT_TOKEN trong biến môi trường.')

# Tự động đồng bộ Webhook cho Cashflow Bot (@gidotien_bot)
from app.config import Config
cashflow_token = Config.CASHFLOW_BOT_TOKEN
secret_token = Config.TELEGRAM_SECRET_TOKEN
render_url = os.getenv('RENDER_EXTERNAL_URL') or 'https://gic-logistics.onrender.com'

if cashflow_token:
    try:
        import requests
        target_url = f"{render_url.rstrip('/')}/advances/bot-webhook"
        payload = {
            'url': target_url,
            'allowed_updates': ['message', 'edited_message', 'callback_query']
        }
        if secret_token:
            payload['secret_token'] = secret_token
        res = requests.post(f"https://api.telegram.org/bot{cashflow_token}/setWebhook", json=payload, timeout=10).json()
        print(f"🤖 [STARTUP] Telegram Cashflow Webhook: {res.get('description', res)}")
    except Exception as e:
        print(f"⚠️ [STARTUP] Lỗi đồng bộ Webhook: {e}")

# 1. Kiểm tra và khởi tạo DB
_app = None
print('📦 [STARTUP] Kiểm tra và khởi tạo cơ sở dữ liệu (db.create_all)...')
try:
    from app import create_app
    from app.extensions import db
    _app = create_app()
    with _app.app_context():
        db.create_all()
        # Tự động đồng bộ chuẩn hóa các dòng cước bị thiếu tổng tiền từ Excel
        try:
            from app.models import RevenueItem
            items = RevenueItem.query.filter(
                RevenueItem.buy_price > 0,
                (RevenueItem.total_buy_price_excel == 0.0) | (RevenueItem.total_buy_price_excel == None)
            ).all()
            for it in items:
                surcharges = (it.overtime_fee or 0) + (it.inspection_fee or 0) + (it.routing_fee or 0) + (it.empty_container or 0)
                it.total_buy_price_excel = (it.buy_price or 0) + (it.buy_price_loading or 0) + surcharges
            if items:
                db.session.commit()
                print(f'✅ [STARTUP] Đã tự động đồng bộ {len(items)} dòng cước giá mua trên production DB!')
        except Exception as db_sync_err:
            print(f'⚠️ [STARTUP] Cảnh báo đồng bộ dòng cước: {db_sync_err}')

        # Tự động dọn dẹp các lô trùng lặp batch cũ nếu còn sót lại
        try:
            from app.models import Lot
            has_high = Lot.query.filter(Lot.id >= 1000).first()
            if has_high:
                old_lots = Lot.query.filter(Lot.id < 1000).all()
                if old_lots:
                    for ol in old_lots:
                        db.session.delete(ol)
                    db.session.commit()
                    print(f'✅ [STARTUP] Đã dọn dẹp {len(old_lots)} lô trùng lặp batch cũ!')
        except Exception as dup_err:
            print(f'⚠️ [STARTUP] Cảnh báo kiểm tra lô trùng: {dup_err}')

        # Tự động chuẩn hóa phân loại chi phí cho OperatingCost
        try:
            from app.models import OperatingCost, classify_service_category
            all_costs = OperatingCost.query.all()
            updated_costs = 0
            for c in all_costs:
                cat = classify_service_category(c.description, c.cost_type)
                if c.cost_type != cat:
                    c.cost_type = cat
                    updated_costs += 1
            if updated_costs > 0:
                db.session.commit()
                print(f'✅ [STARTUP] Đã chuẩn hóa phân loại cho {updated_costs} khoản chi phí vận hành!')
        except Exception as cat_sync_err:
            print(f'⚠️ [STARTUP] Cảnh báo chuẩn hóa phân loại: {cat_sync_err}')
    print('✅ [STARTUP] Cơ sở dữ liệu đã sẵn sàng!')
except Exception as e:
    print(f'⚠️ [STARTUP] Cảnh báo tạo DB: {e}')

# 2. Khởi động Clock Scheduler bằng background thread (tiết kiệm ~100MB RAM)
scheduler = None
if _app:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()

        def scheduled_deadline_check():
            with _app.app_context():
                try:
                    from app.services.reminder_service import ReminderService
                    ReminderService.run_daily_deadline_check()
                except Exception as ex:
                    print(f'⚠️ [CLOCK] Lỗi kiểm tra deadline: {ex}')

        def scheduled_sync_advances():
            with _app.app_context():
                try:
                    from app.services.advance_service import auto_sync_active_months
                    auto_sync_active_months()
                except Exception as ex:
                    print(f'⚠️ [CLOCK] Lỗi đồng bộ Google Sheets: {ex}')

        scheduler.add_job(scheduled_deadline_check, 'cron', hour=8, minute=0, id='daily_deadline_check')
        scheduler.add_job(scheduled_sync_advances, 'interval', minutes=30, id='sync_advances_30min')
        scheduler.start()
        print('⏰ [STARTUP] Clock Scheduler background thread đã sẵn sàng (0MB RAM phụ)!')
    except Exception as e:
        print(f'⚠️ [STARTUP] Lỗi khởi động Clock Scheduler: {e}')

# 3. Khởi động Gunicorn Web Server với cấu hình tối ưu RAM
print(f'🌐 [STARTUP] Khởi động Gunicorn Web Server tại 0.0.0.0:{port}...')
cmd = [
    sys.executable, '-m', 'gunicorn',
    'app:create_app()',
    '--bind', f'0.0.0.0:{port}',
    '--workers', '1',
    '--threads', '2',
    '--max-requests', '250',
    '--max-requests-jitter', '25',
    '--timeout', '60'
]

try:
    subprocess.run(cmd)
except KeyboardInterrupt:
    pass
finally:
    if bot_proc:
        bot_proc.terminate()
    if scheduler:
        scheduler.shutdown(wait=False)
