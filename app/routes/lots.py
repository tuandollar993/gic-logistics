from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Lot, Customer, User, CostEntryTask
from app.routes.auth import manager_required
from app.services.calculator import CalculatorService
from app.services.reminder_service import ReminderService
from app.services.excel_exporter import ExcelExporterService

lots_bp = Blueprint('lots', __name__)

@lots_bp.route('/')
@login_required
def index():
    months = CalculatorService.get_available_months()
    default_year = 2026
    default_month = 8
    if months:
        default_year, default_month = months[0]
        
    selected_month = request.args.get('month', default_month, type=int)
    selected_year = request.args.get('year', default_year, type=int)
    query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    
    lots_query = Lot.query.filter_by(month=selected_month, year=selected_year)
    # Exclude completely empty placeholder lots
    lots_query = lots_query.filter(
        (Lot.revenue_items.any()) | (Lot.operating_costs.any()) | (Lot.tasks.any())
    )
    
    # If staff, can see all lots or only assigned depending on view mode
    if not current_user.is_manager:
        lots_query = lots_query.filter_by(assigned_to=current_user.id)
        
    if query:
        lots_query = lots_query.filter(
            (Lot.lot_label.ilike(f"%{query}%")) |
            (Lot.customs_declaration.ilike(f"%{query}%")) |
            (Lot.company.ilike(f"%{query}%"))
        )
        
    if status_filter:
        lots_query = lots_query.filter_by(status=status_filter)
        
    lots = lots_query.order_by(Lot.id.desc()).all()
    staff_users = User.query.filter_by(is_active=True).all()
    
    return render_template(
        'lots.html',
        lots=lots,
        months=months,
        selected_month=selected_month,
        selected_year=selected_year,
        staff_users=staff_users,
        query=query,
        status_filter=status_filter
    )

@lots_bp.route('/<int:lot_id>')
@login_required
def detail(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    # Check permissions: manager or assigned staff
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền truy cập lô hàng này.', 'danger')
        return redirect(url_for('lots.index'))
        
    staff_users = User.query.filter_by(role='staff', is_active=True).all() if current_user.is_manager else []
    return render_template('lot_detail.html', lot=lot, staff_users=staff_users)

@lots_bp.route('/new', methods=['GET', 'POST'])
@login_required
@manager_required
def new_lot():
    if request.method == 'POST':
        lot_label = request.form.get('lot_label', '').strip()
        customer_name = request.form.get('customer_name', '').strip()
        company = request.form.get('company', '').strip()
        customs_declaration = request.form.get('customs_declaration', '').strip()
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        assigned_to = request.form.get('assigned_to', type=int)
        deadline_str = request.form.get('cost_deadline')
        
        if not customer_name or not month or not year:
            flash('Vui lòng điền đủ Tên khách hàng, Tháng và Năm.', 'danger')
            return redirect(url_for('lots.index'))
            
        cust = Customer.query.filter_by(name=customer_name).first()
        if not cust:
            cust = Customer(name=customer_name)
            db.session.add(cust)
            db.session.flush()
            
        deadline = None
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
            except ValueError:
                pass
                
        lot = Lot(
            lot_label=lot_label or f"Lô mới",
            customer_id=cust.id,
            company=company,
            customs_declaration=customs_declaration,
            month=month,
            year=year,
            assigned_to=assigned_to if assigned_to else None,
            cost_deadline=deadline,
            created_by=current_user.id,
            status='assigned' if assigned_to else 'pending'
        )
        db.session.add(lot)
        db.session.flush()
        
        # If assigned to staff, create task and send reminder/notification
        if assigned_to and deadline:
            task = CostEntryTask(
                lot_id=lot.id,
                assigned_to=assigned_to,
                deadline=deadline,
                created_by=current_user.id
            )
            db.session.add(task)
            db.session.flush()
            ReminderService.send_task_assignment_notification(task)
            
        db.session.commit()
        flash(f'Đã tạo thành công {lot.lot_label} và giao việc!', 'success')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    customers = Customer.query.order_by(Customer.name).all()
    staff_users = User.query.filter_by(role='staff', is_active=True).all()
    return render_template('lot_form.html', customers=customers, staff_users=staff_users)

@lots_bp.route('/<int:lot_id>/assign', methods=['POST'])
@login_required
@manager_required
def assign_staff(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    assigned_to = request.form.get('assigned_to', type=int)
    deadline_str = request.form.get('deadline')
    
    if not assigned_to or not deadline_str:
        flash('Vui lòng chọn nhân viên và hạn chót (deadline).', 'warning')
        return redirect(url_for('lots.index'))
        
    deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
    lot.assigned_to = assigned_to
    lot.cost_deadline = deadline
    lot.status = 'assigned'
    
    # Create or update Task
    task = CostEntryTask.query.filter_by(lot_id=lot.id).first()
    if not task:
        task = CostEntryTask(
            lot_id=lot.id,
            assigned_to=assigned_to,
            deadline=deadline,
            created_by=current_user.id
        )
        db.session.add(task)
    else:
        task.assigned_to = assigned_to
        task.deadline = deadline
        task.status = 'pending'
        
    db.session.commit()
    ReminderService.send_task_assignment_notification(task)
    flash(f'Đã phân công {lot.lot_label} cho nhân viên và gửi thông báo Telegram!', 'success')
    return redirect(request.referrer or url_for('lots.index'))

@lots_bp.route('/export')
@login_required
@manager_required
def export_excel():
    months = CalculatorService.get_available_months()
    default_year = 2026
    default_month = 8
    if months:
        default_year, default_month = months[0]
        
    selected_month = request.args.get('month', default_month, type=int)
    selected_year = request.args.get('year', default_year, type=int)
    
    excel_buffer = ExcelExporterService.export_monthly_report(selected_month, selected_year)
    filename = f"Bao_cao_kinh_doanh_T{selected_month:02d}_{selected_year}.xlsx"
    
    return send_file(
        excel_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

