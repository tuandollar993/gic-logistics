from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import CostEntryTask, User
from app.routes.auth import manager_required
from app.services.reminder_service import ReminderService

tasks_bp = Blueprint('tasks', __name__)

@tasks_bp.route('/tracking')
@login_required
@manager_required
def tracking():
    status_filter = request.args.get('status', '')
    staff_filter = request.args.get('staff_id', type=int)
    
    query = CostEntryTask.query
    if status_filter == 'overdue':
        query = query.filter(CostEntryTask.status != 'completed', CostEntryTask.deadline < date.today())
    elif status_filter == 'pending':
        query = query.filter(CostEntryTask.status.in_(['pending', 'reminded']), CostEntryTask.deadline >= date.today())
    elif status_filter:
        query = query.filter_by(status=status_filter)
        
    if staff_filter:
        query = query.filter_by(assigned_to=staff_filter)
        
    tasks = query.order_by(CostEntryTask.deadline.asc()).all()
    staff_users = User.query.filter_by(role='staff', is_active=True).all()
    
    total_tasks = CostEntryTask.query.count()
    completed_count = CostEntryTask.query.filter_by(status='completed').count()
    overdue_count = CostEntryTask.query.filter(CostEntryTask.status != 'completed', CostEntryTask.deadline < date.today()).count()
    pending_count = total_tasks - completed_count - overdue_count
    
    return render_template(
        'tracking.html',
        tasks=tasks,
        staff_users=staff_users,
        status_filter=status_filter,
        staff_filter=staff_filter,
        stats={
            'total': total_tasks,
            'completed': completed_count,
            'overdue': overdue_count,
            'pending': pending_count,
            'completion_rate': round((completed_count / total_tasks * 100), 1) if total_tasks > 0 else 0
        }
    )

@tasks_bp.route('/my')
@login_required
def my_tasks():
    status_filter = request.args.get('status', '')
    query = CostEntryTask.query.filter_by(assigned_to=current_user.id)
    
    if status_filter == 'overdue':
        query = query.filter(CostEntryTask.status != 'completed', CostEntryTask.deadline < date.today())
    elif status_filter:
        query = query.filter_by(status=status_filter)
        
    tasks = query.order_by(CostEntryTask.deadline.asc()).all()
    
    return render_template(
        'my_tasks.html',
        tasks=tasks,
        status_filter=status_filter
    )

@tasks_bp.route('/remind/<int:task_id>', methods=['POST'])
@login_required
@manager_required
def remind(task_id):
    ok, msg = ReminderService.send_manual_reminder(task_id)
    if ok:
        flash('Đã gửi thông báo nhắc nhở qua Telegram thành công!', 'success')
    else:
        flash(f'Ghi nhận lượt nhắc nhở. Lưu ý: {msg}', 'warning')
    return redirect(request.referrer or url_for('tasks.tracking'))

@tasks_bp.route('/run-check', methods=['POST'])
@login_required
@manager_required
def run_deadline_check():
    results = ReminderService.run_daily_deadline_check()
    flash(f"Đã rà soát deadline: {results['reminded']} thông báo nhắc nhở, {results['overdue']} cảnh báo quá hạn.", 'info')
    return redirect(url_for('tasks.tracking'))
