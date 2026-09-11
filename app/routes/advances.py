from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user

from app.services.advance_service import (
    get_monthly_advances_data,
    get_all_available_months,
    sync_month_from_google,
    export_advances_excel,
    add_transaction,
    update_transaction,
    delete_transaction
)

advances_bp = Blueprint('advances', __name__)

@advances_bp.route('/', methods=['GET'])
@login_required
def index():
    now = datetime.now()
    # Mặc định lấy tháng 8/2026 nếu chưa có chọn, vì tháng 8/2026 có dữ liệu đầy đủ từ Google Sheet
    selected_month = request.args.get('month', type=int)
    selected_year = request.args.get('year', type=int)
    
    if not selected_month or not selected_year:
        # Nếu đang ở tháng 8 hoặc tháng 9 năm 2026
        selected_month = 8 if now.year == 2026 and now.month <= 8 else now.month
        selected_year = 2026

    query = request.args.get('q', '').strip()

    available_months = get_all_available_months()
    data = get_monthly_advances_data(selected_month, selected_year)

    transactions = data['transactions']
    if query:
        q_lower = query.lower()
        transactions = [
            t for t in transactions
            if q_lower in (t.content or '').lower() or
               q_lower in (t.trans_date or '').lower() or
               q_lower in (t.partner_invoice or '').lower() or
               q_lower in (t.accounting_status or '').lower()
        ]

    return render_template(
        'advances.html',
        selected_month=selected_month,
        selected_year=selected_year,
        months=available_months,
        monthly=data['monthly'],
        metrics=data['metrics'],
        transactions=transactions,
        query=query
    )


@advances_bp.route('/sync', methods=['POST'])
@login_required
def sync_data():
    month = request.form.get('month', type=int) or request.json.get('month', 8)
    year = request.form.get('year', type=int) or request.json.get('year', 2026)

    monthly, err = sync_month_from_google(month, year)
    if err:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 400
        flash(f"Lỗi đồng bộ từ Google Sheet: {err}", "danger")
    else:
        msg = f"Đồng bộ thành công Tháng {month:02d}/{year} từ Google Sheet 'Dòng tiền GIDO theo tháng 2026'!"
        if request.is_json:
            return jsonify({'success': True, 'message': msg})
        flash(msg, "success")

    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/add', methods=['POST'])
@login_required
def add():
    payload = request.form.to_dict() if request.form else (request.get_json() or {})
    month = int(payload.get('month', 8))
    year = int(payload.get('year', 2026))

    trans = add_transaction(payload)
    if request.is_json:
        return jsonify({'success': True, 'transaction': trans.to_dict()})

    flash("Đã thêm thành công giao dịch tạm ứng mới!", "success")
    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/update/<int:trans_id>', methods=['POST'])
@login_required
def update(trans_id):
    payload = request.form.to_dict() if request.form else (request.get_json() or {})
    trans = update_transaction(trans_id, payload)
    
    if not trans:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Không tìm thấy giao dịch'}), 404
        flash("Không tìm thấy giao dịch!", "danger")
        return redirect(url_for('advances.index'))

    if request.is_json:
        return jsonify({'success': True, 'transaction': trans.to_dict()})

    flash("Cập nhật giao dịch thành công!", "success")
    return redirect(url_for('advances.index', month=trans.month, year=trans.year))


@advances_bp.route('/delete/<int:trans_id>', methods=['POST'])
@login_required
def delete(trans_id):
    month = request.args.get('month', type=int, default=8)
    year = request.args.get('year', type=int, default=2026)
    
    ok = delete_transaction(trans_id)
    if request.is_json:
        return jsonify({'success': ok})

    if ok:
        flash("Đã xóa bút toán tạm ứng!", "success")
    else:
        flash("Không thể xóa bút toán!", "danger")

    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    month = request.args.get('month', type=int, default=8)
    year = request.args.get('year', type=int, default=2026)
    try:
        file_path, filename = export_advances_excel(month, year)
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f"Lỗi xuất file Excel: {e}", "danger")
        return redirect(url_for('advances.index', month=month, year=year))
