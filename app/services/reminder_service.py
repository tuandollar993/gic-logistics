from datetime import date, datetime
from app.extensions import db
from app.models import CostEntryTask, ReminderLog, User
from app.services.telegram_service import TelegramService
from flask import current_app

class ReminderService:
    @staticmethod
    def send_task_assignment_notification(task):
        """Level 1: Thông báo khi quản lý giao lô mới"""
        assignee = task.assignee
        lot = task.lot
        if not assignee:
            return
            
        deadline_str = task.deadline.strftime('%d/%m/%Y')
        msg = (
            f"📦 <b>GIAO NHIỆM VỤ ĐIỀN CHI PHÍ VẬN HÀNH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Lô hàng:</b> {lot.lot_label or f'Lô #{lot.id}'}\n"
            f"• <b>Khách hàng:</b> {lot.customer.name if lot.customer else 'N/A'}\n"
            f"• <b>Công ty / Dự án:</b> {lot.company or 'N/A'}\n"
            f"• <b>Số tờ khai:</b> {lot.customs_declaration or 'N/A'}\n"
            f"• <b>Tháng:</b> {lot.month}/{lot.year}\n"
            f"• <b>Hạn chót (Deadline):</b> <b>{deadline_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 <i>Vui lòng truy cập hệ thống để nhập đủ chi phí và chứng từ trước deadline.</i>"
        )
        
        status = 'not_configured'
        if assignee.telegram_chat_id:
            ok, err = TelegramService.send_message(assignee.telegram_chat_id, msg)
            status = 'sent' if ok else f'failed: {err}'
            
        log = ReminderLog(
            task_id=task.id,
            channel='telegram',
            message=msg,
            status=status
        )
        db.session.add(log)
        db.session.commit()

    @staticmethod
    def send_manual_reminder(task_id):
        """Quản lý gửi nhắc nhở thủ công"""
        task = db.session.get(CostEntryTask, task_id)
        if not task:
            return False, "Không tìm thấy nhiệm vụ."
            
        assignee = task.assignee
        lot = task.lot
        days_left = task.days_remaining
        
        if days_left < 0:
            urgency = f"🚨 <b>CẢNH BÁO QUÁ HẠN {abs(days_left)} NGÀY!</b>"
        elif days_left == 0:
            urgency = "🔴 <b>HÔM NAY LÀ HẠN CHÓT CUỐI CÙNG!</b>"
        else:
            urgency = f"⏰ <b>CÒN {days_left} NGÀY ĐẾN HẠN!</b>"
            
        msg = (
            f"{urgency}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Quản lý vừa gửi lời nhắc hoàn thiện chi phí cho lô:\n"
            f"• <b>Lô:</b> {lot.lot_label} ({lot.customer.name if lot.customer else ''})\n"
            f"• <b>Số TKHQ:</b> {lot.customs_declaration or 'N/A'}\n"
            f"• <b>Deadline:</b> {task.deadline.strftime('%d/%m/%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 <i>Yêu cầu nhân viên điền đủ hóa đơn, phiếu chi và nhấn Hoàn thành.</i>"
        )
        
        ok = False
        err = "Nhân viên chưa liên kết Telegram"
        if assignee and assignee.telegram_chat_id:
            ok, err = TelegramService.send_message(assignee.telegram_chat_id, msg)
            
        task.reminder_count = (task.reminder_count or 0) + 1
        task.last_reminded_at = datetime.utcnow()
        if task.status != 'completed':
            task.status = 'overdue' if days_left < 0 else 'reminded'
            
        log = ReminderLog(
            task_id=task.id,
            channel='telegram',
            message=msg,
            status='sent' if ok else f'failed: {err}'
        )
        db.session.add(log)
        db.session.commit()
        return ok, err

    @staticmethod
    def run_daily_deadline_check():
        """
        Runs automated daily check on all pending tasks and escalates reminders
        """
        pending_tasks = CostEntryTask.query.filter(CostEntryTask.status != 'completed').all()
        today = date.today()
        manager_chat_id = current_app.config.get('TELEGRAM_MANAGER_CHAT_ID')
        
        results = {'reminded': 0, 'overdue': 0, 'escalated': 0}
        
        for task in pending_tasks:
            days = (task.deadline - today).days
            lot = task.lot
            assignee = task.assignee
            staff_chat = assignee.telegram_chat_id if assignee else None
            
            # Level 5: Quá hạn
            if days < 0:
                task.status = 'overdue'
                results['overdue'] += 1
                msg_staff = (
                    f"🚨 <b>QUÁ HẠN ĐIỀN CHI PHÍ VẬN HÀNH!</b>\n"
                    f"• Lô: {lot.lot_label} ({lot.customer.name if lot.customer else ''})\n"
                    f"• Đã quá hạn: {abs(days)} ngày (Hạn chót: {task.deadline.strftime('%d/%m/%Y')})\n"
                    f"• Yêu cầu bổ sung dữ liệu ngay lập tức!"
                )
                msg_mgr = (
                    f"🚨 <b>BÁO CÁO QUÁ HẠN: LÔ {lot.lot_label}</b>\n"
                    f"• Nhân viên phụ trách: {assignee.full_name if assignee else 'N/A'}\n"
                    f"• Khách hàng: {lot.customer.name if lot.customer else ''}\n"
                    f"• Quá hạn: {abs(days)} ngày."
                )
                if staff_chat:
                    TelegramService.send_message(staff_chat, msg_staff)
                if manager_chat_id:
                    TelegramService.send_message(manager_chat_id, msg_mgr)
                results['escalated'] += 1

            # Level 4: Còn 1 ngày
            elif days == 1 or days == 0:
                results['reminded'] += 1
                urgency = "HÔM NAY" if days == 0 else "NGÀY MAI"
                msg_staff = (
                    f"🔴 <b>KHẨN CẤP: DEADLINE VÀO {urgency}!</b>\n"
                    f"• Lô: {lot.lot_label} ({lot.customer.name if lot.customer else ''})\n"
                    f"• Hạn chót: {task.deadline.strftime('%d/%m/%Y')}\n"
                    f"• Vui lòng hoàn thành để tránh bị báo cáo quá hạn."
                )
                if staff_chat:
                    TelegramService.send_message(staff_chat, msg_staff)
                if manager_chat_id and days == 0:
                    TelegramService.send_message(manager_chat_id, f"⚠️ Lô {lot.lot_label} của {assignee.full_name if assignee else ''} đến hạn chót hôm nay.")

            # Level 3: Còn 3 ngày
            elif days == 3:
                results['reminded'] += 1
                msg_staff = (
                    f"⚠️ <b>CẢNH BÁO TIẾN ĐỘ: CÒN 3 NGÀY</b>\n"
                    f"• Lô: {lot.lot_label} ({lot.customer.name if lot.customer else ''})\n"
                    f"• Hạn chót: {task.deadline.strftime('%d/%m/%Y')}"
                )
                if staff_chat:
                    TelegramService.send_message(staff_chat, msg_staff)

            # Level 2: Còn 5 ngày
            elif days == 5:
                results['reminded'] += 1
                msg_staff = (
                    f"⏰ <b>NHẮC TIẾN ĐỘ ĐIỀN CHI PHÍ: CÒN 5 NGÀY</b>\n"
                    f"• Lô: {lot.lot_label} ({lot.customer.name if lot.customer else ''})\n"
                    f"• Deadline: {task.deadline.strftime('%d/%m/%Y')}"
                )
                if staff_chat:
                    TelegramService.send_message(staff_chat, msg_staff)

            task.last_reminded_at = datetime.utcnow()
            task.reminder_count = (task.reminder_count or 0) + 1
            
        db.session.commit()
        return results
