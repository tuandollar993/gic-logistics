import os
import sys
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

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

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from app import create_app
from app.extensions import db
from app.models import User, CostEntryTask, Lot
from app.services.calculator import CalculatorService

app = create_app()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = (
        f"👋 <b>Xin chào! Chào mừng bạn đến với GIC Logistics Bot.</b>\n\n"
        f"Chat ID của bạn: <code>{chat_id}</code>\n\n"
        f"Để liên kết tài khoản GIC và nhận thông báo deadline điền CPVH, hãy gõ:\n"
        f"👉 <code>/link &lt;tên_đăng_nhập&gt;</code>\n"
        f"<i>(Ví dụ: /link nv_ngocan hoặc /link admin)</i>\n\n"
        f"<b>Các lệnh hữu ích:</b>\n"
        f"• <code>/mytasks</code> - Xem nhiệm vụ và deadline của bạn\n"
        f"• <code>/overview</code> - Xem tổng quan doanh thu & deadline (Quản lý)\n"
        f"• <code>/help</code> - Hướng dẫn sử dụng"
    )
    await update.message.reply_html(msg)

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Vui lòng cung cấp username: /link <tên_đăng_nhập>")
        return
        
    username = context.args[0].strip()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            await update.message.reply_text(f"❌ Không tìm thấy tài khoản '{username}' trong hệ thống.")
            return
            
        user.telegram_chat_id = chat_id
        db.session.commit()
        await update.message.reply_html(
            f"✅ <b>Liên kết thành công!</b>\n"
            f"Tài khoản: <b>{user.full_name}</b> ({user.role.upper()})\n"
            f"Từ bây giờ bạn sẽ nhận thông báo giao việc và nhắc nhở deadline tự động tại đây."
        )

async def mytasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    with app.app_context():
        user = User.query.filter_by(telegram_chat_id=chat_id).first()
        if not user:
            await update.message.reply_text("❌ Bạn chưa liên kết tài khoản. Gõ /link <username> để liên kết.")
            return
            
        tasks = CostEntryTask.query.filter_by(assigned_to=user.id, status='pending').all()
        if not tasks:
            await update.message.reply_text(f"🎉 Tuyệt vời {user.full_name}! Bạn hiện không có nhiệm vụ điền CPVH nào tồn đọng.")
            return
            
        lines = [f"📋 <b>DANH SÁCH NHIỆM VỤ CỦA {user.full_name.upper()}:</b>\n"]
        for t in tasks:
            lot = t.lot
            days = t.days_remaining
            status_tag = f"🔴 Quá hạn {abs(days)} ngày" if days < 0 else (f"⏰ Còn {days} ngày" if days > 0 else "⚠️ HÔM NAY")
            lines.append(
                f"• <b>{lot.lot_label}</b> ({lot.customer.name if lot.customer else ''})\n"
                f"  Số TK: {lot.customs_declaration or 'N/A'}\n"
                f"  Hạn chót: {t.deadline.strftime('%d/%m/%Y')} ({status_tag})\n"
            )
            
        lines.append("👉 <i>Vui lòng đăng nhập hệ thống web để cập nhật đầy đủ chi phí.</i>")
        await update.message.reply_html("\n".join(lines))

async def overview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with app.app_context():
        kpi = CalculatorService.get_monthly_kpi(8, 2026)
        overdue_cnt = CostEntryTask.query.filter(CostEntryTask.status != 'completed', CostEntryTask.deadline < date.today()).count()
        
        msg = (
            f"📊 <b>TỔNG QUAN TÀI CHÍNH & VẬN HÀNH GIC (T8/2026)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Doanh thu bán:</b> {kpi['revenue']:,.0f} ₫ (+{kpi['rev_growth']}% MoM)\n"
            f"• <b>Tổng chi phí:</b> {kpi['total_cost']:,.0f} ₫\n"
            f"• <b>Lợi nhuận ròng:</b> {kpi['net_profit']:,.0f} ₫ ({kpi['profit_margin']}%)\n"
            f"• <b>Target tháng:</b> {kpi['achievement_pct']}% đạt chỉ tiêu\n"
            f"• <b>Tiến độ CPVH:</b> {kpi['lots_with_cost']}/{kpi['lot_count']} lô ({kpi['cost_completion_pct']}%)\n"
            f"• <b>Nhiệm vụ quá hạn:</b> <b>{overdue_cnt} lô</b> 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_html(msg)

def run_bot():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("⚠️ Chưa cấu hình TELEGRAM_BOT_TOKEN trong file .env.")
        print("Vui lòng điền token được cấp từ @BotFather vào .env để kích hoạt Bot.")
        return
        
    print(f"🚀 Khởi động GIC Telegram Bot...")
    bot_app = ApplicationBuilder().token(token).build()
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("link", link_command))
    bot_app.add_handler(CommandHandler("mytasks", mytasks_command))
    bot_app.add_handler(CommandHandler("overview", overview_command))
    bot_app.run_polling()

if __name__ == '__main__':
    run_bot()
