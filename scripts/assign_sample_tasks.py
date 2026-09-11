import sys
from pathlib import Path
from datetime import date, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app import create_app
from app.extensions import db
from app.models import Lot, User, CostEntryTask

def assign_tasks():
    app = create_app()
    with app.app_context():
        # Get active staff members
        staff = User.query.filter_by(role='staff', is_active=True).all()
        if not staff:
            print("Không tìm thấy nhân viên.")
            return
            
        # Get lots in months 7, 8, 9 of 2026
        recent_lots = Lot.query.filter(Lot.year == 2026, Lot.month.in_([7, 8, 9])).order_by(Lot.id.desc()).all()
        print(f"Tìm thấy {len(recent_lots)} lô hàng trong T7-T9/2026")
        
        today = date.today()
        assigned_count = 0
        
        for idx, lot in enumerate(recent_lots):
            assigned_user = staff[idx % len(staff)]
            lot.assigned_to = assigned_user.id
            
            deadline_offset = (idx % 5) - 1  # -1 (overdue), 0 (today), 1 (tomorrow), 2, 3
            task_deadline = today + timedelta(days=deadline_offset)
            lot.cost_deadline = task_deadline
            
            has_costs = len(lot.operating_costs) > 0
            if has_costs and idx % 2 == 0:
                lot.status = 'completed'
                task_status = 'completed'
            else:
                lot.status = 'overdue' if deadline_offset < 0 else 'in_progress'
                task_status = 'overdue' if deadline_offset < 0 else 'pending'
                
            task = CostEntryTask.query.filter_by(lot_id=lot.id).first()
            if not task:
                task = CostEntryTask(
                    lot_id=lot.id,
                    assigned_to=assigned_user.id,
                    deadline=task_deadline,
                    status=task_status
                )
                db.session.add(task)
            else:
                task.assigned_to = assigned_user.id
                task.deadline = task_deadline
                task.status = task_status
                
            assigned_count += 1
            
        db.session.commit()
        print(f"✅ Đã phân công {assigned_count} lô hàng và tạo task deadline cho 10 nhân viên!")

if __name__ == '__main__':
    assign_tasks()
