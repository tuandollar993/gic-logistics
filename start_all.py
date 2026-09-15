import os
import sys
import subprocess

port = os.getenv('PORT', '5000')

print('🚀 [STARTUP] Đang khởi động GIC Logistics All-in-One (Web + Bot + Clock)...')

# Tự động đồng bộ Webhook cho Cashflow Bot (@gidotien_bot)
from app.config import Config
tg_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
cf_bot_token = os.getenv('CASHFLOW_BOT_TOKEN') or Config.CASHFLOW_BOT_TOKEN

# Nếu TELEGRAM_BOT_TOKEN thực chất là token của Cashflow Bot (8728564714), dùng làm cashflow_token
if not cf_bot_token and tg_bot_token and tg_bot_token.startswith('8728564714:'):
    cf_bot_token = tg_bot_token

bot_thread = None
if tg_bot_token and tg_bot_token != cf_bot_token and not tg_bot_token.startswith('8728564714:'):
    print('🤖 [STARTUP] Kích hoạt Telegram Bot background thread...')
    try:
        from bot.telegram_bot import start_bot_thread
        bot_thread = start_bot_thread()
    except Exception as bot_err:
        print(f'⚠️ [STARTUP] Lỗi khởi động Telegram Bot: {bot_err}')
else:
    print('ℹ️ [STARTUP] Bỏ qua polling bot thread (tránh xung đột Webhook với Cashflow Bot).')

secret_token = Config.TELEGRAM_SECRET_TOKEN or 'gic_tg_sec_2026_9ad8d26c9f413921'
render_url = os.getenv('RENDER_EXTERNAL_URL') or 'https://gic-logistics.onrender.com'

if cf_bot_token:
    try:
        import requests
        target_url = f"{render_url.rstrip('/')}/advances/bot-webhook"
        payload = {
            'url': target_url,
            'allowed_updates': ['message', 'edited_message', 'callback_query'],
            'secret_token': secret_token
        }
        res = requests.post(f"https://api.telegram.org/bot{cf_bot_token}/setWebhook", json=payload, timeout=10).json()
        print(f"🤖 [STARTUP] Telegram Cashflow Webhook: {res.get('description', res)}")
    except Exception as e:
        print(f"⚠️ [STARTUP] Lỗi đồng bộ Webhook: {e}")

# 1. Kiểm tra và khởi tạo DB
_app = None
print('📦 [STARTUP] Kiểm tra và khởi tạo cơ sở dữ liệu (db.create_all)...')
try:
    from app import create_app
    from app.extensions import db
    from flask_migrate import upgrade as _migrate_upgrade
    _app = create_app()
    with _app.app_context():
        try:
            _migrate_upgrade()
            print('✅ [STARTUP] Đã tự động cập nhật Alembic migration thành công!')
        except Exception as mig_err:
            print(f'⚠️ [STARTUP] Cảnh báo Alembic migration: {mig_err}')
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

        # Tự động chuẩn hóa tách phụ phí độc lập (CSHT, vé xe, bốc xếp...) Giá mua = Giá bán
        try:
            from scripts.normalize_surcharges import run_surcharge_normalization
            sc_res = run_surcharge_normalization(commit=True, app=_app)
            if sc_res and sc_res.get('split_items', 0) > 0:
                print(f"✅ [STARTUP] Đã tách riêng {sc_res['split_items']} phụ phí độc lập (Giá mua = Giá bán)!")
        except Exception as sc_err:
            print(f'⚠️ [STARTUP] Cảnh báo chuẩn hóa phụ phí: {sc_err}')

        # Tự động chuẩn hóa phân loại chi phí cho OperatingCost (chỉ quét các khoản chưa phân loại)
        try:
            from app.models import OperatingCost, classify_service_category
            unclassified_costs = OperatingCost.query.filter(
                (OperatingCost.cost_type == None) | (OperatingCost.cost_type == '')
            ).all()
            updated_costs = 0
            for c in unclassified_costs:
                cat = classify_service_category(c.description, c.cost_type)
                if c.cost_type != cat:
                    c.cost_type = cat
                    updated_costs += 1
            if updated_costs > 0:
                db.session.commit()
                print(f'✅ [STARTUP] Đã chuẩn hóa phân loại cho {updated_costs} khoản chi phí vận hành!')
        except Exception as cat_sync_err:
            print(f'⚠️ [STARTUP] Cảnh báo chuẩn hóa phân loại: {cat_sync_err}')
        finally:
            db.session.remove()

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
                finally:
                    db.session.remove()

        def scheduled_sync_advances():
            with _app.app_context():
                try:
                    from app.services.advance_service import auto_sync_active_months
                    auto_sync_active_months()
                except Exception as ex:
                    print(f'⚠️ [CLOCK] Lỗi đồng bộ Google Sheets: {ex}')
                finally:
                    db.session.remove()

        def scheduled_advance_refund_reminder():
            with _app.app_context():
                try:
                    from app.services.reminder_service import ReminderService
                    ReminderService.run_advance_refund_reminder()
                except Exception as ex:
                    print(f'⚠️ [CLOCK] Lỗi nhắc nhở hoàn ứng: {ex}')
                finally:
                    db.session.remove()

        scheduler.add_job(scheduled_deadline_check, 'cron', hour=8, minute=0, id='daily_deadline_check')
        scheduler.add_job(scheduled_advance_refund_reminder, 'cron', hour=8, minute=5, id='advance_refund_reminder')
        scheduler.add_job(scheduled_sync_advances, 'interval', minutes=30, id='sync_advances_30min')
        scheduler.start()
        print('⏰ [STARTUP] Clock Scheduler background thread đã sẵn sàng (0MB RAM phụ)!')
    except Exception as e:
        print(f'⚠️ [STARTUP] Lỗi khởi động Clock Scheduler: {e}')

# 3. Khởi động Gunicorn Web Server với cấu hình tối ưu RAM
# Không dùng --max-requests nhỏ để tránh fork đồng thời 2 worker gây đỉnh nhọn RAM 640MB
print(f'🌐 [STARTUP] Khởi động Gunicorn Web Server tại 0.0.0.0:{port}...')
cmd = [
    sys.executable, '-m', 'gunicorn',
    'app:create_app()',
    '--bind', f'0.0.0.0:{port}',
    '--workers', '1',
    '--threads', '4',
    '--timeout', '60'
]

try:
    subprocess.run(cmd)
except KeyboardInterrupt:
    pass
finally:
    if scheduler:
        scheduler.shutdown(wait=False)
