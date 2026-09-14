import re
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Lot, Customer, User, CostEntryTask, RevenueItem, Supplier, OperatingCost, CashAdvanceBillMedia
from app.security import manager_required, log_audit
from app.services.calculator import CalculatorService
from app.services.reminder_service import ReminderService
from app.services.excel_exporter import ExcelExporterService

lots_bp = Blueprint('lots', __name__)

def clean_money_input(val, default=0.0):
    """Làm sạch chuỗi nhập tiền tệ Việt Nam (VD: '3.250.000', '4,000,000', '3250000.0') thành float"""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ('-', '–'):
        return default
    is_neg = s.startswith('-') or (s.startswith('(') and s.endswith(')'))
    s = s.lstrip('-()').rstrip(')')
    s = s.replace('₫', '').replace('đ', '').replace('VND', '').replace('vnd', '').strip()
    
    # Chỉ bóc tách phần đuôi thập phân .0 hoặc ,0 (1 đến 2 số 0 sau dấu chấm/phẩy đơn)
    if s.count('.') <= 1 and s.count(',') <= 1:
        s = re.sub(r'[,.]0{1,2}$', '', s)
        
    s = s.replace('.', '').replace(',', '').replace(' ', '')
    try:
        amt = float(s)
        return -amt if is_neg else amt
    except (ValueError, TypeError):
        return default

def suggest_lot_label(month, year):
    """
    Tìm số thứ tự lô cao nhất trong tháng/năm đã chọn và đề xuất mã lô tiếp theo.
    Định dạng đề xuất: GIDO(tháng)(năm)-(số lô) ví dụ: GIDO092026-03
    """
    lots = Lot.query.filter_by(month=month, year=year, is_deleted=False).all()
    nums = []
    existing_labels = set()
    for l in lots:
        lbl = (l.lot_label or '').strip()
        if lbl:
            existing_labels.add(lbl.lower())
            # 1. Match GIDO{month}{year}-NN
            m = re.search(r'GIDO\d{6}[-_]?(\d+)', lbl, re.IGNORECASE)
            if m:
                nums.append(int(m.group(1)))
                continue
            # 2. Match "Lô (\d+)" (bỏ qua Lô CP vì là placeholder CPVH)
            if 'lô cp' not in lbl.lower() and 'lo cp' not in lbl.lower():
                m = re.search(r'lô\s*(\d+)', lbl, re.IGNORECASE)
                if m:
                    nums.append(int(m.group(1)))
                    continue
                m = re.search(r'(\d+)$', lbl)
                if m:
                    nums.append(int(m.group(1)))

    next_num = max(nums) + 1 if nums else 1
    while True:
        candidate = f"GIDO{month:02d}{year}-{next_num:02d}"
        if candidate.lower() not in existing_labels:
            break
        next_num += 1

    return candidate, next_num


@lots_bp.route('/api/suggest-label')
@login_required
def api_suggest_label():
    month = request.args.get('month', type=int) or datetime.now().month
    year = request.args.get('year', type=int) or datetime.now().year
    code, next_num = suggest_lot_label(month, year)
    return jsonify({
        'code': code,
        'alt_label': f"Lô {next_num:02d}",
        'next_num': next_num
    })


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
    
    from sqlalchemy.orm import joinedload, selectinload

    # 1. Sales Lots (Main list)
    sales_query = Lot.sales_lots_query().filter_by(month=selected_month, year=selected_year)
    sales_query = sales_query.filter(
        (Lot.revenue_items.any(RevenueItem.is_deleted.is_(False))) |
        (Lot.operating_costs.any(OperatingCost.is_deleted.is_(False))) |
        (Lot.tasks.any())
    )
    
    # If staff, can see all lots or only assigned depending on view mode
    if not current_user.is_manager:
        sales_query = sales_query.filter_by(assigned_to=current_user.id)
        
    if query:
        sales_query = sales_query.filter(
            (Lot.lot_label.ilike(f"%{query}%")) |
            (Lot.customs_declaration.ilike(f"%{query}%")) |
            (Lot.company.ilike(f"%{query}%"))
        )
        
    if status_filter:
        sales_query = sales_query.filter_by(status=status_filter)
        
    sales_query = sales_query.options(
        joinedload(Lot.customer),
        joinedload(Lot.assignee),
        selectinload(Lot.revenue_items),
        selectinload(Lot.operating_costs)
    )
    lots = sales_query.order_by(Lot.id.desc()).all()

    # 2. Unresolved CPVH Groups (Operating costs not yet matched to a single Sales Lot)
    unresolved_groups = []
    if current_user.is_manager:
        unresolved_query = Lot.unresolved_cpvh_query().filter_by(month=selected_month, year=selected_year)
        unresolved_query = unresolved_query.filter(
            Lot.operating_costs.any(OperatingCost.is_deleted.is_(False))
        )
        if query:
            unresolved_query = unresolved_query.filter(
                (Lot.lot_label.ilike(f"%{query}%")) |
                (Lot.customs_declaration.ilike(f"%{query}%")) |
                (Lot.company.ilike(f"%{query}%"))
            )
        unresolved_query = unresolved_query.options(
            joinedload(Lot.customer),
            selectinload(Lot.operating_costs)
        )
        unresolved_groups = unresolved_query.order_by(Lot.id.asc()).all()

    # Tự động đề xuất ghép lô thông minh (hỗ trợ cả các tháng trước)
    from app.services.cpvh_matcher import CPVHMatcher
    all_sales_lots = Lot.sales_lots_query().order_by(Lot.year.desc(), Lot.month.desc(), Lot.lot_label.asc()).all()
    for u in unresolved_groups:
        u.suggestions = CPVHMatcher.suggest_candidates(u, all_sales_lots)

    unresolved_total_ops = sum(u.total_operating_cost for u in unresolved_groups)
    total_month_vehicles = sum(l.total_vehicle_count for l in lots)
    staff_users = User.query.filter_by(is_active=True).all()
    
    suggested_code, next_num = suggest_lot_label(selected_month, selected_year)
    suggested_lo = f"Lô {next_num:02d}"
    canonical_customers = Customer.query.filter_by(is_active=True).order_by(Customer.name.asc()).all()
    
    return render_template(
        'lots.html',
        lots=lots,
        all_sales_lots=all_sales_lots,
        total_month_vehicles=total_month_vehicles,
        unresolved_groups=unresolved_groups,
        unresolved_total_ops=unresolved_total_ops,
        months=months,
        selected_month=selected_month,
        selected_year=selected_year,
        staff_users=staff_users,
        query=query,
        status_filter=status_filter,
        suggested_code=suggested_code,
        suggested_lo=suggested_lo,
        canonical_customers=canonical_customers
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
    other_lots = []
    if current_user.is_manager:
        other_lots = Lot.query.filter(
            Lot.id != lot.id,
            Lot.is_deleted == False
        ).order_by(Lot.year.desc(), Lot.month.desc(), Lot.lot_label).all()
        
    return render_template('lot_detail.html', lot=lot, staff_users=staff_users, suppliers=suppliers, other_lots=other_lots)

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
            
        from app.services.customer_service import get_or_create_canonical_customer
        cust = get_or_create_canonical_customer(customer_name)
        if not company:
            company = cust.name
            
        deadline = None
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if not lot_label:
            lot_label, _ = suggest_lot_label(month, year)
        else:
            # Ngăn chặn trùng lặp mã lô trong cùng một kỳ báo cáo
            existing = Lot.query.filter_by(month=month, year=year, lot_label=lot_label, is_deleted=False).first()
            if existing:
                code, _ = suggest_lot_label(month, year)
                flash(f"Tên lô '{lot_label}' đã tồn tại trong Tháng {month:02d}/{year}. Hệ thống đã tự động gán mã mới '{code}' để tránh trùng lặp.", 'warning')
                lot_label = code
                
        lot = Lot(
            lot_label=lot_label,
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
        
        # Tự động nạp sẵn 16 hạng mục chi phí vận hành chuẩn nếu người dùng chọn
        init_template = request.form.get('init_template_costs') in ('on', '1', 'true', True)
        if init_template:
            from app.constants import STANDARD_OPERATING_COST_ITEMS
            for item in STANDARD_OPERATING_COST_ITEMS:
                cost = OperatingCost(
                    lot_id=lot.id,
                    cost_type=item['cost_type'],
                    description=item['description'],
                    vehicle_count=item.get('default_vehicle_count', 1.0),
                    unit_price=0.0,
                    total_amount=0.0,
                    invoice_type=item.get('invoice_type', 'Không HĐ'),
                    payment_method='Tiền mặt'
                )
                db.session.add(cost)

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
        CalculatorService._cached_months = None
        flash(f'Đã tạo thành công {lot.lot_label} và giao việc!', 'success')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    # GET request: redirect to lots list (creation is handled via modal on lots.html)
    return redirect(url_for('lots.index'))


@lots_bp.route('/<int:lot_id>/init-template-costs', methods=['POST'])
@login_required
@manager_required
def init_template_costs(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    from app.constants import STANDARD_OPERATING_COST_ITEMS
    existing_descs = {c.description.strip().lower() for c in lot.active_operating_costs if c.description}
    added_count = 0
    for item in STANDARD_OPERATING_COST_ITEMS:
        if item['description'].strip().lower() not in existing_descs:
            cost = OperatingCost(
                lot_id=lot.id,
                cost_type=item['cost_type'],
                description=item['description'],
                vehicle_count=item.get('default_vehicle_count', 1.0),
                unit_price=0.0,
                total_amount=0.0,
                invoice_type=item.get('invoice_type', 'Không HĐ'),
                payment_method='Tiền mặt'
            )
            db.session.add(cost)
            added_count += 1
    db.session.commit()
    flash(f"Đã nạp thành công {added_count} hạng mục chi phí chuẩn vào {lot.lot_label}!", "success")
    return redirect(request.referrer or url_for('lots.detail', lot_id=lot.id))


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

@lots_bp.route('/<int:lot_id>/export-problematic-costs', methods=['GET'])
@login_required
def export_lot_problematic_costs(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    excel_buffer = ExcelExporterService.export_problematic_costs(lot_id=lot.id)
    safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', lot.lot_label)
    filename = f"Chi_phi_can_xu_ly_{safe_label}_T{lot.month:02d}_{lot.year}.xlsx"
    return send_file(
        excel_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@lots_bp.route('/export-problematic-costs', methods=['GET'])
@login_required
def export_monthly_problematic_costs():
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    excel_buffer = ExcelExporterService.export_problematic_costs(month=month, year=year)
    if month and year:
        filename = f"Chi_phi_can_xu_ly_T{month:02d}_{year}.xlsx"
    else:
        filename = "Chi_phi_can_xu_ly_Tat_ca.xlsx"
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
    
    buy_price = clean_money_input(request.form.get('buy_price', 0))
    sell_price = clean_money_input(request.form.get('sell_price', 0))
    surcharges = clean_money_input(request.form.get('surcharges', 0))

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
    
    buy_raw = request.form.get('buy_price')
    if buy_raw is not None and buy_raw != '':
        item.buy_price = clean_money_input(buy_raw)
        
    sell_raw = request.form.get('sell_price')
    if sell_raw is not None and sell_raw != '':
        item.sell_price = clean_money_input(sell_raw)
        
    surcharges_raw = request.form.get('surcharges')
    if surcharges_raw is not None and surcharges_raw != '':
        item.other_surcharge = clean_money_input(surcharges_raw)
    else:
        item.other_surcharge = 0.0
        
    item.total_buy_price_excel = item.buy_price
    item.total_sell_price_excel = (item.sell_price or 0.0) + (item.other_surcharge or 0.0)
    
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
        
    item = RevenueItem.query.filter_by(id=item_id, lot_id=lot.id, is_deleted=False).first_or_404()
    try:
        item.is_deleted = True
        item.deleted_at = datetime.now(timezone.utc)
        item.deleted_by = current_user.id
        log_audit('delete_revenue_item', 'revenue_item', item.id,
                  f'Soft deleted revenue item {item.id} from lot {lot.id}',
                  before_state={'lot_id': lot.id, 'total_buy_price': item.total_buy_price,
                                'total_sell_price': item.total_sell_price})
        db.session.commit()
        flash('Đã xóa mục thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xóa mục: {e}', 'danger')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/costs/<int:cost_id>/edit', methods=['POST'])
@login_required
def edit_cost_item(lot_id, cost_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa chi phí này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    cost = OperatingCost.query.filter_by(id=cost_id, lot_id=lot.id, is_deleted=False).first_or_404()
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
    if request.form.get('invoice_symbol') is not None:
        cost.invoice_symbol = request.form.get('invoice_symbol', '').strip()
    if request.form.get('supplier_tax_code') is not None:
        cost.supplier_tax_code = request.form.get('supplier_tax_code', '').strip()
    if request.form.get('document_date'):
        try:
            cost.document_date = datetime.strptime(request.form.get('document_date').strip(), '%Y-%m-%d').date()
        except Exception:
            pass

    # Xử lý xác nhận phân loại hóa đơn & Bắt buộc file khi chọn 'Có HĐ'
    inv_cls = request.form.get('invoice_classification')
    invoice_file = request.files.get('invoice_file')

    if inv_cls in ('has_invoice', 'no_invoice', 'unpayable_invoice'):
        if inv_cls == 'has_invoice' and not cost.has_invoice_file and (not invoice_file or not invoice_file.filename):
            flash('Lỗi: Khi chọn trạng thái "Có HĐ", bắt buộc phải tải lên file/ảnh hóa đơn!', 'danger')
            return redirect(url_for('lots.detail', lot_id=lot.id))
        cost.invoice_classification = inv_cls

    if invoice_file and invoice_file.filename:
        file_bytes = invoice_file.read()
        if len(file_bytes) > 0:
            from app.services.advance_service import save_bill_media
            save_bill_media(
                media_id=None,
                file_bytes=file_bytes,
                filename=invoice_file.filename,
                mime_type=invoice_file.mimetype or 'image/jpeg',
                operating_cost_id=cost.id,
                lot_id=lot.id,
                uploaded_by=current_user.id
            )
            if not inv_cls:
                cost.invoice_classification = 'has_invoice'

    buy_raw = request.form.get('buy_price')
    if buy_raw is not None and buy_raw != '':
        buy_p = clean_money_input(buy_raw)
        cost.total_amount = buy_p
        cost.unit_price = buy_p

    sell_raw = request.form.get('sell_price')
    if sell_raw is not None and sell_raw != '':
        cost.sell_price = clean_money_input(sell_raw)
        
    db.session.commit()
    flash('Đã cập nhật chi phí vận hành thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/costs/<int:cost_id>/invoice', methods=['POST'])
@login_required
def update_cost_invoice(lot_id, cost_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Bạn không có quyền chỉnh sửa chi phí này.'}), 403
        flash('Bạn không có quyền chỉnh sửa chi phí này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))

    cost = OperatingCost.query.filter_by(id=cost_id, lot_id=lot.id, is_deleted=False).first_or_404()

    inv_cls = request.form.get('invoice_classification')
    if inv_cls not in ('has_invoice', 'no_invoice', 'unpayable_invoice'):
        msg = 'Trạng thái hóa đơn không hợp lệ.'
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))

    invoice_file = request.files.get('invoice_file')
    has_existing = cost.has_invoice_file

    if inv_cls == 'has_invoice' and not has_existing and (not invoice_file or not invoice_file.filename):
        msg = 'Khi chọn "Có HĐ", bắt buộc phải tải lên file/ảnh hóa đơn!'
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))

    if invoice_file and invoice_file.filename:
        file_bytes = invoice_file.read()
        if len(file_bytes) > 0:
            from app.services.advance_service import save_bill_media
            save_bill_media(
                media_id=None,
                file_bytes=file_bytes,
                filename=invoice_file.filename,
                mime_type=invoice_file.mimetype or 'image/jpeg',
                operating_cost_id=cost.id,
                lot_id=lot.id,
                uploaded_by=current_user.id
            )

    cost.invoice_classification = inv_cls
    if request.form.get('invoice_type') is not None:
        cost.invoice_type = request.form.get('invoice_type', '').strip()
    if request.form.get('invoice_number') is not None:
        cost.invoice_number = request.form.get('invoice_number', '').strip()
    if request.form.get('invoice_symbol') is not None:
        cost.invoice_symbol = request.form.get('invoice_symbol', '').strip()
    if request.form.get('supplier_tax_code') is not None:
        cost.supplier_tax_code = request.form.get('supplier_tax_code', '').strip()
    if request.form.get('supplier_name') is not None:
        cost.supplier_name = request.form.get('supplier_name', '').strip()
    if request.form.get('document_date'):
        try:
            cost.document_date = datetime.strptime(request.form.get('document_date').strip(), '%Y-%m-%d').date()
        except Exception:
            pass

    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        latest_media = cost.latest_invoice_media
        st = lot.invoice_stats
        return jsonify({
            'success': True,
            'cost_id': cost.id,
            'invoice_classification': cost.invoice_classification,
            'invoice_classification_label': cost.invoice_classification_label,
            'has_invoice_file': cost.has_invoice_file,
            'media_id': latest_media.id if latest_media else None,
            'invoice_stats': {
                k: {'count': v['count'], 'total': v['total']}
                for k, v in st.items()
            }
        })

    flash('Đã cập nhật trạng thái hóa đơn thành công!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))

@lots_bp.route('/<int:lot_id>/costs/<int:cost_id>/delete', methods=['POST'])
@login_required
def delete_cost_item(lot_id, cost_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa chi phí này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    cost = OperatingCost.query.filter_by(id=cost_id, lot_id=lot.id).first_or_404()
    try:
        log_audit('delete_cost', 'cost', cost_id, f"Deleted cost item {cost_id} from lot {lot_id}",
                  before_state={'cost_id': cost.id, 'description': cost.description, 'total_amount': cost.total_amount})
        cost.is_deleted = True
        cost.deleted_at = datetime.now(timezone.utc)
        cost.deleted_by = current_user.id
        db.session.flush()
        db.session.commit()
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return jsonify({
                'success': True,
                'cost_id': cost_id,
                'total_operating_cost': lot.total_operating_cost,
                'cost_count': len(lot.active_operating_costs)
            })
        flash('Đã xóa khoản chi phí thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(f'Lỗi xóa chi phí: {e}', 'danger')
    return redirect(request.referrer or url_for('lots.detail', lot_id=lot.id))


@lots_bp.route('/<int:lot_id>/edit', methods=['POST'])
@login_required
def edit_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền chỉnh sửa lô hàng này.', 'danger')
        return redirect(url_for('lots.detail', lot_id=lot.id))
        
    lot_label = request.form.get('lot_label', '').strip()
    company = request.form.get('company', '').strip()
    customer_name = request.form.get('customer_name', '').strip()
    customs_declaration = request.form.get('customs_declaration', '').strip()
    status = request.form.get('status', '').strip()
    
    before_state = {
        'lot_label': lot.lot_label,
        'company': lot.company,
        'customs_declaration': lot.customs_declaration,
        'status': lot.status
    }
    
    if lot_label:
        lot.lot_label = lot_label
    lot.customs_declaration = customs_declaration
    
    if customer_name:
        from app.services.customer_service import get_or_create_canonical_customer
        cust = get_or_create_canonical_customer(customer_name)
        lot.customer_id = cust.id
        lot.company = company if company else cust.name
    elif company:
        lot.company = company
        
    if status in ['pending', 'assigned', 'in_progress', 'completed', 'overdue']:
        lot.status = status
        if status == 'completed' and not lot.completed_at:
            lot.completed_at = datetime.now(timezone.utc)
            
    # Quản lý có thể điều chỉnh thêm tháng/năm, người phụ trách và hạn chót
    if current_user.is_manager:
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        if month and 1 <= month <= 12:
            lot.month = month
        if year and 2020 <= year <= 2030:
            lot.year = year
            
        assigned_to = request.form.get('assigned_to', type=int)
        if assigned_to:
            lot.assigned_to = assigned_to
        elif 'assigned_to' in request.form and request.form.get('assigned_to') == '':
            lot.assigned_to = None
            
        deadline_str = request.form.get('cost_deadline')
        if deadline_str:
            try:
                lot.cost_deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
            except ValueError:
                pass
                
    log_audit('edit_lot', 'lot', lot.id,
              f"Cập nhật thông tin lô {lot.lot_label}",
              before_state=before_state,
              after_state={'lot_label': lot.lot_label, 'company': lot.company, 'customs': lot.customs_declaration, 'status': lot.status})
    db.session.commit()
    flash(f'Đã cập nhật thành công thông tin {lot.lot_label}!', 'success')
    return redirect(url_for('lots.detail', lot_id=lot.id))


@lots_bp.route('/<int:lot_id>/merge', methods=['POST'])
@login_required
@manager_required
def merge_lot(lot_id):
    target_lot = Lot.query.get_or_404(lot_id)
    source_lot_id = request.form.get('source_lot_id', type=int)
    
    if not source_lot_id or source_lot_id == target_lot.id:
        flash('Vui lòng chọn một lô hàng hợp lệ khác để gộp.', 'warning')
        return redirect(url_for('lots.detail', lot_id=target_lot.id))
        
    source_lot = Lot.query.filter_by(id=source_lot_id, is_deleted=False).first_or_404()
    source_label = source_lot.lot_label
    source_id = source_lot.id
    
    try:
        # 1. Chuyển toàn bộ các dòng doanh thu sang target_lot
        rev_count = RevenueItem.query.filter_by(lot_id=source_lot.id).update(
            {RevenueItem.lot_id: target_lot.id}, synchronize_session=False
        )
        
        # 2. Chuyển toàn bộ các dòng chi phí vận hành sang target_lot
        cost_count = OperatingCost.query.filter_by(lot_id=source_lot.id).update(
            {OperatingCost.lot_id: target_lot.id}, synchronize_session=False
        )
        
        # 3. Chuyển toàn bộ chứng từ ảnh hóa đơn sang target_lot
        media_count = CashAdvanceBillMedia.query.filter_by(lot_id=source_lot.id).update(
            {CashAdvanceBillMedia.lot_id: target_lot.id}, synchronize_session=False
        )
        
        # 4. Chuyển tasks nếu có
        CostEntryTask.query.filter_by(lot_id=source_lot.id).update(
            {CostEntryTask.lot_id: target_lot.id}, synchronize_session=False
        )
        
        # 5. Bổ sung tờ khai HQ nếu chưa có hoặc khác
        if source_lot.customs_declaration:
            if not target_lot.customs_declaration:
                target_lot.customs_declaration = source_lot.customs_declaration
            elif source_lot.customs_declaration not in target_lot.customs_declaration:
                target_lot.customs_declaration = f"{target_lot.customs_declaration}, {source_lot.customs_declaration}"
                
        # 6. Bổ sung thông tin cty nếu target_lot chưa có
        if source_lot.company and not target_lot.company:
            target_lot.company = source_lot.company
            
        # 7. Soft delete source_lot
        now_utc = datetime.now(timezone.utc)
        source_lot.is_deleted = True
        source_lot.deleted_at = now_utc
        source_lot.deleted_by = current_user.id
        
        log_audit('merge_lot', 'lot', target_lot.id,
                  f"Đã gộp lô {source_label} (ID: {source_id}) vào lô {target_lot.lot_label} (ID: {target_lot.id}) - Di chuyển {rev_count} mục cước, {cost_count} CPVH, {media_count} bill.",
                  before_state={'source_lot_id': source_id, 'target_lot_id': target_lot.id})
                  
        db.session.commit()
        flash(f'Đã gộp thành công {source_label} vào {target_lot.lot_label} (chuyển {rev_count} mục doanh thu và {cost_count} chi phí vận hành)!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi gộp lô hàng: {e}', 'danger')
        
    return redirect(url_for('lots.detail', lot_id=target_lot.id))


@lots_bp.route('/<int:lot_id>/delete', methods=['POST'])
@login_required
@manager_required
def delete_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    label = lot.lot_label
    m, y = lot.month, lot.year
    try:
        now_utc = datetime.now(timezone.utc)
        lot.is_deleted = True
        lot.deleted_at = now_utc
        lot.deleted_by = current_user.id
        for cost in lot.operating_costs:
            cost.is_deleted = True
            cost.deleted_at = now_utc
            cost.deleted_by = current_user.id
        log_audit('delete_lot', 'lot', lot_id, f"Soft deleted lot {label} (Tháng {m}/{y})",
                  before_state={'lot_id': lot_id, 'lot_label': label, 'month': m, 'year': y})
        db.session.flush()
        db.session.commit()
        flash(f'Đã xóa thành công lô hàng {label}!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xóa lô hàng: {e}', 'danger')
    return redirect(url_for('lots.index', month=m, year=y))


@lots_bp.route('/reconcile-cpvh', methods=['POST'])
@login_required
@manager_required
def reconcile_cpvh():
    unresolved_id = request.form.get('unresolved_lot_id', type=int)
    target_lot_id = request.form.get('target_lot_id', type=int)
    
    if not unresolved_id or not target_lot_id:
        flash('Vui lòng chọn đầy đủ nhóm chi phí và lô bán hàng cần ghép.', 'warning')
        return redirect(request.referrer or url_for('lots.index'))
        
    unresolved_lot = Lot.query.filter_by(id=unresolved_id, is_deleted=False, source_type='cpvh').first_or_404()
    target_lot = Lot.sales_lots_query().filter_by(id=target_lot_id).first_or_404()
    
    try:
        cost_count = OperatingCost.query.filter_by(lot_id=unresolved_lot.id).update(
            {OperatingCost.lot_id: target_lot.id}, synchronize_session=False
        )
        CashAdvanceBillMedia.query.filter_by(lot_id=unresolved_lot.id).update(
            {CashAdvanceBillMedia.lot_id: target_lot.id}, synchronize_session=False
        )
        
        now_utc = datetime.now(timezone.utc)
        unresolved_lot.is_deleted = True
        unresolved_lot.deleted_at = now_utc
        unresolved_lot.deleted_by = current_user.id
        
        CalculatorService.invalidate_cache()
        log_audit('reconcile_cpvh', 'lot', target_lot.id,
                  f"Đã ghép nhóm CPVH {unresolved_lot.lot_label} (ID: {unresolved_lot.id}) vào lô bán hàng {target_lot.lot_label} (ID: {target_lot.id}) - Di chuyển {cost_count} khoản CPVH.",
                  before_state={'unresolved_id': unresolved_lot.id, 'target_lot_id': target_lot.id})
        db.session.commit()
        flash(f"Đã ghép thành công {unresolved_lot.lot_label} vào {target_lot.lot_label} ({cost_count} khoản chi phí vận hành)!", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi ghép chi phí vận hành: {e}", 'danger')
        
    return redirect(url_for('lots.index', month=target_lot.month, year=target_lot.year))

