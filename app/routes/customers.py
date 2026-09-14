from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Customer, Lot
from app.routes.auth import manager_required
from app.services.customer_service import (
    normalize_customer_name,
    get_or_create_canonical_customer,
    merge_customers
)

customers_bp = Blueprint('customers', __name__)


def get_all_customers_with_metrics(search_query='', sort_by='revenue', filter_status='all'):
    """
    Truy vấn danh sách khách hàng kèm số liệu thống kê (Lô, Doanh thu, Chi phí, Lợi nhuận)
    Tối ưu hóa: Load danh sách lô và group trong bộ nhớ để đạt tốc độ < 0.1s.
    """
    # 1. Load all active sales lots
    all_lots = Lot.sales_lots_query().order_by(
        Lot.year.desc(), Lot.month.desc(), Lot.id.desc()
    ).all()

    # 2. Group lots by customer_id
    lots_by_cust = defaultdict(list)
    for l in all_lots:
        if l.customer_id:
            lots_by_cust[l.customer_id].append(l)

    # 3. Query customers
    q = Customer.query.filter_by(is_active=True)
    if search_query:
        sq = f"%{search_query.strip().lower()}%"
        q = q.filter(
            (db.func.lower(Customer.name).like(sq)) |
            (db.func.lower(Customer.code).like(sq)) |
            (db.func.lower(Customer.contact_person).like(sq)) |
            (db.func.lower(Customer.phone).like(sq))
        )

    raw_customers = q.all()
    results = []

    total_kpi = {
        'total_customers': len(raw_customers),
        'active_customers': 0,
        'total_lots': 0,
        'total_revenue': 0.0,
        'total_cost': 0.0,
        'total_profit': 0.0,
        'avg_margin': 0.0
    }

    for c in raw_customers:
        c_lots = lots_by_cust.get(c.id, [])
        lot_count = len(c_lots)

        rev = sum(l.total_sell_revenue for l in c_lots)
        buy = sum(l.total_buy_cost for l in c_lots)
        ops = sum(l.total_operating_cost for l in c_lots)
        cost = buy + ops
        profit = sum(l.net_profit for l in c_lots)
        margin = ((profit / rev) * 100.0) if rev > 0 else 0.0

        latest_lot = c_lots[0] if c_lots else None
        latest_period = f"T{latest_lot.month:02d}/{latest_lot.year}" if latest_lot and latest_lot.month else "-"

        if lot_count > 0:
            total_kpi['active_customers'] += 1
            total_kpi['total_lots'] += lot_count
            total_kpi['total_revenue'] += rev
            total_kpi['total_cost'] += cost
            total_kpi['total_profit'] += profit

        # Filter by status if requested
        if filter_status == 'active' and lot_count == 0:
            continue
        elif filter_status == 'profitable' and profit <= 0:
            continue
        elif filter_status == 'unprofitable' and profit >= 0:
            continue

        results.append({
            'customer': c,
            'lot_count': lot_count,
            'revenue': rev,
            'cost': cost,
            'profit': profit,
            'margin': round(margin, 2),
            'latest_lot': latest_lot,
            'latest_period': latest_period
        })

    if total_kpi['total_revenue'] > 0:
        total_kpi['avg_margin'] = round((total_kpi['total_profit'] / total_kpi['total_revenue']) * 100.0, 2)

    # Sorting
    if sort_by == 'revenue':
        results.sort(key=lambda x: x['revenue'], reverse=True)
    elif sort_by == 'profit':
        results.sort(key=lambda x: x['profit'], reverse=True)
    elif sort_by == 'lots':
        results.sort(key=lambda x: x['lot_count'], reverse=True)
    elif sort_by == 'margin':
        results.sort(key=lambda x: x['margin'], reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x['customer'].name.lower())

    return results, total_kpi


@customers_bp.route('/', methods=['GET'])
@login_required
def index():
    """Trang Tổng Quan & Bảng Danh Sách Khách Hàng Chuẩn Hóa"""
    search_q = request.args.get('q', '').strip()
    sort_by = request.args.get('sort', 'revenue')
    filter_status = request.args.get('status', 'all')

    customers_data, kpi = get_all_customers_with_metrics(
        search_query=search_q,
        sort_by=sort_by,
        filter_status=filter_status
    )

    all_active_customers = Customer.query.filter_by(is_active=True).order_by(Customer.name.asc()).all()

    return render_template(
        'customers.html',
        customers_data=customers_data,
        kpi=kpi,
        search_q=search_q,
        sort_by=sort_by,
        filter_status=filter_status,
        all_active_customers=all_active_customers
    )


@customers_bp.route('/<int:customer_id>', methods=['GET'])
@login_required
def detail(customer_id):
    """Trang Chi Tiết Khách Hàng: Hồ sơ doanh nghiệp + Toàn bộ lịch sử các lô hàng"""
    customer = Customer.query.get_or_404(customer_id)

    # Get all sales lots for this customer
    lots = Lot.sales_lots_query().filter_by(customer_id=customer.id).order_by(
        Lot.year.desc(), Lot.month.desc(), Lot.id.desc()
    ).all()

    total_revenue = sum(l.total_sell_revenue for l in lots)
    total_buy = sum(l.total_buy_cost for l in lots)
    total_ops = sum(l.total_operating_cost for l in lots)
    total_cost = total_buy + total_ops
    net_profit = sum(l.net_profit for l in lots)
    margin = (net_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    # Monthly breakdown
    monthly_data = defaultdict(lambda: {'lots': 0, 'rev': 0.0, 'cost': 0.0, 'profit': 0.0})
    for l in lots:
        k = f"T{l.month:02d}/{l.year}" if l.month else "Khác"
        monthly_data[k]['lots'] += 1
        monthly_data[k]['rev'] += l.total_sell_revenue
        monthly_data[k]['cost'] += (l.total_buy_cost + l.total_operating_cost)
        monthly_data[k]['profit'] += l.net_profit

    # Sort months chronologically if possible
    monthly_summary = []
    for k, v in monthly_data.items():
        m_margin = (v['profit'] / v['rev'] * 100.0) if v['rev'] > 0 else 0.0
        monthly_summary.append({
            'period': k,
            'lots': v['lots'],
            'rev': v['rev'],
            'cost': v['cost'],
            'profit': v['profit'],
            'margin': round(m_margin, 2)
        })

    all_other_customers = Customer.query.filter(
        Customer.id != customer.id,
        Customer.is_active == True
    ).order_by(Customer.name.asc()).all()

    return render_template(
        'customer_detail.html',
        customer=customer,
        lots=lots,
        total_revenue=total_revenue,
        total_cost=total_cost,
        net_profit=net_profit,
        margin=round(margin, 2),
        monthly_summary=monthly_summary,
        all_other_customers=all_other_customers
    )


@customers_bp.route('/new', methods=['POST'])
@login_required
@manager_required
def new_customer():
    """Tạo mới khách hàng chuẩn hóa"""
    raw_name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    contact_person = request.form.get('contact_person', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    tax_code = request.form.get('tax_code', '').strip()
    notes = request.form.get('notes', '').strip()

    if not raw_name:
        flash('Vui lòng nhập tên khách hàng.', 'danger')
        return redirect(url_for('customers.index'))

    canonical_name, def_code, def_contact = normalize_customer_name(raw_name)

    # Check if exists
    existing = Customer.query.filter(
        db.func.lower(Customer.name) == canonical_name.lower()
    ).first()

    if existing:
        flash(f"Khách hàng '{existing.name}' đã tồn tại trong hệ thống!", 'warning')
        return redirect(url_for('customers.detail', customer_id=existing.id))

    cust = Customer(
        name=canonical_name,
        code=code or def_code,
        contact_person=contact_person or def_contact,
        phone=phone,
        email=email,
        address=address,
        tax_code=tax_code,
        notes=notes
    )
    db.session.add(cust)
    db.session.commit()
    flash(f"Đã thêm thành công khách hàng chuẩn hóa: '{canonical_name}'!", 'success')
    return redirect(url_for('customers.detail', customer_id=cust.id))


@customers_bp.route('/<int:customer_id>/edit', methods=['POST'])
@login_required
@manager_required
def edit_customer(customer_id):
    """Cập nhật thông tin khách hàng"""
    customer = Customer.query.get_or_404(customer_id)
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    contact_person = request.form.get('contact_person', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    tax_code = request.form.get('tax_code', '').strip()
    notes = request.form.get('notes', '').strip()

    if not name:
        flash('Tên khách hàng không được để trống.', 'danger')
        return redirect(url_for('customers.detail', customer_id=customer.id))

    # Check name duplicate if changed
    if name.lower() != customer.name.lower():
        existing = Customer.query.filter(
            db.func.lower(Customer.name) == name.lower(),
            Customer.id != customer.id
        ).first()
        if existing:
            flash(f"Tên '{name}' đã được dùng cho khách hàng khác!", 'danger')
            return redirect(url_for('customers.detail', customer_id=customer.id))

    customer.name = name
    customer.code = code
    customer.contact_person = contact_person
    customer.phone = phone
    customer.email = email
    customer.address = address
    customer.tax_code = tax_code
    customer.notes = notes

    # Sync to lots
    Lot.query.filter_by(customer_id=customer.id).update({'company': name})

    db.session.commit()
    flash(f"Đã cập nhật thông tin khách hàng '{customer.name}' thành công!", 'success')
    return redirect(url_for('customers.detail', customer_id=customer.id))


@customers_bp.route('/merge', methods=['POST'])
@login_required
@manager_required
def merge_customers_route():
    """Gộp 2 khách hàng trùng lặp và chuyển toàn bộ các lô hàng sang khách hàng đích"""
    source_id = request.form.get('source_customer_id', type=int)
    target_id = request.form.get('target_customer_id', type=int)

    if not source_id or not target_id:
        flash('Vui lòng chọn đầy đủ khách hàng cần gộp và khách hàng đích.', 'danger')
        return redirect(url_for('customers.index'))

    success, msg = merge_customers(source_id, target_id)
    if success:
        flash(f"✅ {msg}", 'success')
        return redirect(url_for('customers.detail', customer_id=target_id))
    else:
        flash(f"❌ Lỗi: {msg}", 'danger')
        return redirect(url_for('customers.index'))


@customers_bp.route('/api/list', methods=['GET'])
@login_required
def api_list():
    """API JSON trả về danh sách khách hàng chuẩn hóa cho autocomplete / dropdown"""
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name.asc()).all()
    return jsonify({
        'success': True,
        'data': [c.to_dict() for c in customers]
    })
