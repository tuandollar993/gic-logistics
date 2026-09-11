from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Lot, Customer, User, CostEntryTask, RevenueItem, Supplier, OperatingCost
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
        
    from sqlalchemy.orm import joinedload, selectinload
    lots_query = lots_query.options(
        joinedload(Lot.customer),
        joinedload(Lot.assignee),
        selectinload(Lot.revenue_items),
        selectinload(Lot.operating_costs)
    )
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
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('lot_detail.html', lot=lot, staff_users=staff_users, suppliers=suppliers)

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
        
    # GET request: redirect to lots list (creation is handled via modal on lots.html)
    return redirect(url_for('lots.index'))

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

@lots_bp.route('/<int:lot_id>/items/add', methods=['POST'])
@login_required
def add_revenue_item(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa lô hàng này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    supplier = request.form.get('supplier', '').strip()
    vehicle_plate = request.form.get('vehicle_plate', '').strip()
    service_description = request.form.get('service_description', '').strip() or 'Khoản mục chi phí & doanh thu'
    
    weight_select = request.form.get('weight_class_select', '').strip()
    weight_custom = request.form.get('weight_class_custom', '').strip()
    if weight_select == 'Khác':
        weight_class = weight_custom or 'Khác'
    elif weight_select:
        weight_class = weight_select
    else:
        weight_class = request.form.get('weight_class', '').strip()
        
    invoice_number = request.form.get('invoice_number', '').strip()
    invoice_type = request.form.get('invoice_type', '').strip()
    
    try:
        buy_price = float(request.form.get('buy_price', 0) or 0)
    except ValueError:
        buy_price = 0.0
        
    try:
        sell_price = float(request.form.get('sell_price', 0) or 0)
    except ValueError:
        sell_price = 0.0
        
    try:
        surcharges = float(request.form.get('surcharges', 0) or 0)
    except ValueError:
        surcharges = 0.0

    cost = OperatingCost(
        lot_id=lot.id,
        cost_type=weight_class or 'Khoản mục chi phí',
        description=service_description,
        vehicle_plate=vehicle_plate,
        vehicle_count=1.0,
        unit_price=buy_price,
        total_amount=buy_price,
        sell_price=sell_price + surcharges,
        invoice_type=invoice_type,
        invoice_number=invoice_number,
        supplier_name=supplier,
        filled_by=current_user.id
    )
    db.session.add(cost)
    db.session.commit()
    flash(f'Đã thêm khoản mục thành công cho {lot.lot_label}!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/items/<int:item_id>/edit', methods=['POST'])
@login_required
def edit_revenue_item(lot_id, item_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa lô hàng này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    item = RevenueItem.query.filter_by(id=item_id, lot_id=lot.id).first_or_404()
    
    item.supplier = request.form.get('supplier', item.supplier or '').strip()
    item.vehicle_plate_vn = request.form.get('vehicle_plate', item.vehicle_plate_vn or '').strip()
    
    weight_select = request.form.get('weight_class_select', '').strip()
    weight_custom = request.form.get('weight_class_custom', '').strip()
    if weight_select == 'Khác':
        item.weight_class = weight_custom or 'Khác'
    elif weight_select:
        item.weight_class = weight_select
    elif request.form.get('weight_class'):
        item.weight_class = request.form.get('weight_class', '').strip()
        
    item.service_description = request.form.get('service_description', item.service_description or '').strip()
    
    try:
        item.buy_price = float(request.form.get('buy_price', item.buy_price) or 0)
    except ValueError:
        pass
        
    try:
        item.sell_price = float(request.form.get('sell_price', item.sell_price) or 0)
    except ValueError:
        pass
        
    try:
        surcharges = float(request.form.get('surcharges', item.other_surcharge or 0) or 0)
    except ValueError:
        surcharges = item.other_surcharge or 0.0
        
    item.other_surcharge = surcharges
    item.total_buy_price_excel = item.buy_price
    item.total_sell_price_excel = item.sell_price + surcharges
    
    db.session.commit()
    flash('Đã cập nhật mục doanh thu và chi phí thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_revenue_item(lot_id, item_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa lô hàng này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    item = RevenueItem.query.filter_by(id=item_id, lot_id=lot.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('Đã xóa mục thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/costs/<int:cost_id>/edit', methods=['POST'])
@login_required
def edit_cost_item(lot_id, cost_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa chi phí này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    cost = OperatingCost.query.filter_by(id=cost_id, lot_id=lot.id).first_or_404()
    cost.description = request.form.get('service_description', cost.description).strip()
    cost.supplier_name = request.form.get('supplier', cost.supplier_name or '').strip()
    cost.vehicle_plate = request.form.get('vehicle_plate', cost.vehicle_plate or '').strip()
    
    weight_select = request.form.get('weight_class_select', '').strip()
    weight_custom = request.form.get('weight_class_custom', '').strip()
    if weight_select == 'Khác':
        cost.cost_type = weight_custom or 'Khác'
    elif weight_select:
        cost.cost_type = weight_select
    elif request.form.get('weight_class'):
        cost.cost_type = request.form.get('weight_class', '').strip()
        
    cost.invoice_number = request.form.get('invoice_number', cost.invoice_number or '').strip()
    cost.invoice_type = request.form.get('invoice_type', cost.invoice_type or '').strip()
    
    try:
        buy_p = float(request.form.get('buy_price', cost.total_amount) or 0)
        cost.total_amount = buy_p
        cost.unit_price = buy_p
    except ValueError:
        pass

    try:
        sell_p = float(request.form.get('sell_price', cost.sell_price or 0) or 0)
        cost.sell_price = sell_p
    except ValueError:
        pass
        
    db.session.commit()
    flash('Đã cập nhật chi phí vận hành thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/costs/<int:cost_id>/delete', methods=['POST'])
@login_required
def delete_cost_item(lot_id, cost_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa chi phí này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    cost = OperatingCost.query.filter_by(id=cost_id, lot_id=lot.id).first_or_404()
    db.session.delete(cost)
    db.session.commit()
    flash('Đã xóa khoản chi phí thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

