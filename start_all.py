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

print('⏰ [STARTUP] Kích hoạt Clock Scheduler background...')
clock_proc = subprocess.Popen([sys.executable, 'clock.py'])

print('📦 [STARTUP] Kiểm tra và khởi tạo cơ sở dữ liệu (db.create_all)...')
try:
    from app import create_app
    from app.extensions import db
    _app = create_app()
    with _app.app_context():
        db.create_all()
    print('✅ [STARTUP] Cơ sở dữ liệu đã sẵn sàng!')
except Exception as e:
    print(f'⚠️ [STARTUP] Cảnh báo tạo DB: {e}')

print(f'🌐 [STARTUP] Khởi động Gunicorn Web Server tại 0.0.0.0:{port}...')
cmd = [
    sys.executable, '-m', 'gunicorn',
    'app:create_app()',
    '--bind', f'0.0.0.0:{port}',
    '--workers', '1',
    '--threads', '4',
    '--timeout', '120'
]

try:
    subprocess.run(cmd)
except KeyboardInterrupt:
    pass
finally:
    if bot_proc:
        bot_proc.terminate()
    if clock_proc:
        clock_proc.terminate()
