import io
from datetime import datetime, timezone
import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Quotation
from app.services.quotation_service import (
    get_all_benchmarks,
    get_benchmarks_filtered,
    find_best_benchmark,
    get_quick_options,
    get_transport_matrix
)
from app.services.quotation_excel_generator import (
    generate_standard_quotation_excel,
    export_quotation_to_excel
)

quotations_bp = Blueprint('quotations', __name__)

@quotations_bp.route('/', methods=['GET'])
@login_required
def index():
    """Trang giao diện Đề Xuất Báo Giá & Tra Cứu Cơ Sở Định Giá"""
    cat_filter = request.args.get('category', 'all')
    search_query = request.args.get('q', '').strip()
    
    benchmarks = get_benchmarks_filtered(category=cat_filter, search=search_query)
    quick_opts = get_quick_options()
    transport_matrix = get_transport_matrix()
    
    recent_quotes = Quotation.query.filter_by(is_deleted=False).order_by(
        Quotation.id.desc()
    ).limit(10).all()

    # Thống kê tổng số lượng hạng mục theo từng nhóm
    all_b = get_all_benchmarks()
    stats = {
        'total': len(all_b),
        'van_chuyen': sum(1 for b in all_b if b['category'] == 'Vận chuyển'),
        'boc_xep': sum(1 for b in all_b if b['category'] == 'Bốc xếp'),
        'kiem_dinh': sum(1 for b in all_b if b['category'] == 'Kiểm định'),
        'to_khai': sum(1 for b in all_b if b['category'] == 'Tờ khai'),
        'cua_khau': sum(1 for b in all_b if b['category'] == 'Cửa khẩu'),
        'bao_hiem': sum(1 for b in all_b if b['category'] == 'Bảo hiểm'),
        'phu_phi': sum(1 for b in all_b if b['category'] == 'Phụ phí')
    }

    active_tab = request.args.get('tab')
    if not active_tab:
        if cat_filter != 'all' or search_query:
            active_tab = 'benchmark'
        else:
            active_tab = 'builder'

    return render_template(
        'quotations.html',
        benchmarks=benchmarks,
        transport_matrix=transport_matrix,
        quick_opts=quick_opts,
        recent_quotes=recent_quotes,
        stats=stats,
        current_cat=cat_filter,
        search_query=search_query,
        active_tab=active_tab
    )

@quotations_bp.route('/api/benchmarks', methods=['GET'])
@login_required
def api_benchmarks():
    """API trả về danh sách benchmark lọc theo phân loại & từ khóa"""
    cat = request.args.get('category', 'all')
    q = request.args.get('q', '').strip()
    items = get_benchmarks_filtered(category=cat, search=q)
    return jsonify({'success': True, 'count': len(items), 'data': items})

@quotations_bp.route('/api/suggest', methods=['GET'])
@login_required
def api_suggest():
    """API gợi ý đơn giá đề xuất và chuỗi cơ sở định giá dựa trên dịch vụ và loại xe"""
    cat = request.args.get('category', '').strip()
    name = request.args.get('name', '').strip()
    spec = request.args.get('spec', '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Vui lòng cung cấp tên tuyến đường hoặc dịch vụ'}), 400

    match = find_best_benchmark(cat, name, spec)
    if match:
        return jsonify({
            'success': True,
            'match': match,
            'unit': match.get('unit', 'Chuyến'),
            'recommended_price': match['recommended_price'],
            'basis_text': match['basis_text']
        })
    
    return jsonify({
        'success': True,
        'match': None,
        'recommended_price': 0,
        'basis_text': 'Chưa có dữ liệu chuyến tương đồng trong lịch sử. Bạn có thể nhập đơn giá đề xuất thủ công.'
    })

@quotations_bp.route('/api/save', methods=['POST'])
@login_required
def api_save():
    """API lưu trữ bảng báo giá gửi khách hàng"""
    data = request.get_json() or {}
    customer_name = (data.get('customer_name') or '').strip()
    if not customer_name:
        return jsonify({'success': False, 'error': 'Vui lòng nhập tên khách hàng / đối tác!'}), 400

    items = data.get('items') or []
    if not items:
        return jsonify({'success': False, 'error': 'Báo giá phải có ít nhất 1 hạng mục dịch vụ!'}), 400

    # Tính toán tổng tiền
    subtotal = 0.0
    for it in items:
        try:
            qty = float(it.get('quantity') or 1)
            raw_p = it.get('unit_price') or 0
            if isinstance(raw_p, str):
                raw_p = raw_p.replace(',', '').replace(' ', '').replace('%', '')
            price = float(raw_p)
        except (ValueError, TypeError):
            qty = 1.0
            price = 0.0
        total = qty * price
        it['total'] = total
        subtotal += total

    vat_percent = float(data.get('vat_percent') or 0)
    vat_amount = subtotal * (vat_percent / 100.0)
    total_amount = subtotal + vat_amount

    # Sinh mã báo giá tự động: BG-YYYYMM-XXX
    now = datetime.now()
    prefix = f"BG-{now.strftime('%Y%m')}-"
    latest_quote = Quotation.query.filter(Quotation.quote_code.like(f"{prefix}%")).order_by(Quotation.id.desc()).first()
    if latest_quote and latest_quote.quote_code:
        try:
            num = int(latest_quote.quote_code.split('-')[-1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    quote_code = f"{prefix}{num:03d}"

    quote = Quotation(
        quote_code=quote_code,
        customer_name=customer_name,
        contact_person=(data.get('contact_person') or '').strip(),
        phone=(data.get('phone') or '').strip(),
        created_by=current_user.id,
        valid_days=int(data.get('valid_days') or 15),
        items_json=json.dumps(items, ensure_ascii=False),
        subtotal=subtotal,
        vat_percent=vat_percent,
        vat_amount=vat_amount,
        total_amount=total_amount,
        notes=(data.get('notes') or '').strip(),
        status='sent'
    )
    db.session.add(quote)
    db.session.commit()

    return jsonify({
        'success': True,
        'quote_id': quote.id,
        'quote_code': quote.quote_code,
        'view_url': url_for('quotations.view_quote', quote_id=quote.id)
    })

@quotations_bp.route('/<int:quote_id>', methods=['GET'])
@login_required
def view_quote(quote_id):
    """Trang xem chi tiết và in ấn / xuất PDF bảng báo giá chuẩn nhận diện GIC Logistics"""
    quote = Quotation.query.filter_by(id=quote_id, is_deleted=False).first_or_404()
    items = []
    try:
        items = json.loads(quote.items_json or '[]')
    except Exception:
        pass

    matrix_routes = []
    aux_services = []
    for it in items:
        if it.get('type') == 'route_matrix' or ('xe_1_9t' in it or 'xe_5t' in it or 'cont_45' in it):
            matrix_routes.append(it)
        elif it.get('category') == 'Vận chuyển':
            matrix_routes.append(it)
        else:
            aux_services.append(it)

    return render_template('quotation_view.html', quote=quote, items=items, matrix_routes=matrix_routes, aux_services=aux_services)

@quotations_bp.route('/<int:quote_id>/delete', methods=['POST'])
@login_required
def delete_quote(quote_id):
    """Xóa mềm báo giá"""
    quote = Quotation.query.filter_by(id=quote_id, is_deleted=False).first_or_404()
    quote.is_deleted = True
    db.session.commit()
    flash(f'Đã xóa bảng báo giá {quote.quote_code} thành công!', 'success')
    return redirect(url_for('quotations.index'))

@quotations_bp.route('/download-standard-excel', methods=['GET'])
@login_required
def download_standard_excel():
    """Tải file Excel Báo Giá Logistics Chuẩn Hóa toàn bộ 5 bảng dịch vụ"""
    wb = generate_standard_quotation_excel()
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    filename = f"Bang_Bao_Gia_Dich_Vu_Logistics_GIC_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@quotations_bp.route('/<int:quote_id>/export-excel', methods=['GET'])
@login_required
def export_quote_excel(quote_id):
    """Xuất báo giá cụ thể của khách hàng sang file Excel chuyên nghiệp"""
    quote = Quotation.query.filter_by(id=quote_id, is_deleted=False).first_or_404()
    wb = export_quotation_to_excel(quote)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    filename = f"Bao_Gia_{quote.quote_code}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

