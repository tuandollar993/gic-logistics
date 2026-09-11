import os
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
    delete_transaction,
    save_bill_media,
    get_bill_media,
    sync_all_bills_from_filedb
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


@advances_bp.route('/webhook', methods=['GET', 'POST'])
def google_sheet_webhook():
    """
    Webhook nhận tín hiệu tự động từ Google Apps Script mỗi khi có chỉnh sửa trên Google Sheet.
    Chạy 100% trên Cloud, kích hoạt đồng bộ ngay lập tức mà không cần máy tính cá nhân bật.
    """
    secret = request.args.get('secret') or (request.get_json(silent=True) or {}).get('secret')
    expected_secret = os.environ.get('WEBHOOK_SECRET', 'gic-secret-2026')
    if secret and secret != expected_secret:
        return jsonify({'error': 'Unauthorized'}), 401
    
    payload = request.get_json(silent=True) or {}
    month = request.args.get('month', type=int) or payload.get('month')
    year = request.args.get('year', type=int) or payload.get('year', 2026)

    try:
        from app.services.advance_service import auto_sync_active_months, sync_month_from_google
        if month:
            monthly, err = sync_month_from_google(int(month), int(year))
            if err:
                return jsonify({'success': False, 'error': err}), 500
            return jsonify({'success': True, 'synced_month': month, 'synced_year': year})
        else:
            auto_sync_active_months()
            return jsonify({'success': True, 'message': 'Đã tự động đồng bộ các tháng từ Google Sheets!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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


@advances_bp.route('/bill/<bill_id>', methods=['GET'])
def view_bill(bill_id):
    """Phục vụ trực tiếp ảnh biên lai/hóa đơn lưu từ Supabase"""
    import base64
    from flask import Response
    
    media = get_bill_media(bill_id)
    if not media or not media.data_base64:
        if media and media.storage_url and media.storage_url.startswith('http'):
            return redirect(media.storage_url)
        return jsonify({'error': 'Không tìm thấy hóa đơn/chứng từ'}), 404

    try:
        raw_bytes = base64.b64decode(media.data_base64)
        mime = media.mime_type or 'image/jpeg'
        resp = Response(raw_bytes, mimetype=mime)
        resp.headers['Cache-Control'] = 'public, max-age=31536000'
        resp.headers['Content-Disposition'] = f'inline; filename="{media.filename or "receipt.jpg"}"'
        return resp
    except Exception as e:
        return jsonify({'error': f'Lỗi đọc ảnh: {e}'}), 500


@advances_bp.route('/api/upload-bill', methods=['POST'])
def upload_bill_api():
    """API cho phép Bot hoặc Client upload ảnh hóa đơn trực tiếp lên Supabase"""
    media_id = request.form.get('id') or (request.json.get('id') if request.is_json else None)
    tg_file_id = request.form.get('file_id') or (request.json.get('file_id') if request.is_json else None)
    
    file_bytes = None
    filename = 'receipt.jpg'
    mime_type = 'image/jpeg'

    if 'file' in request.files:
        uploaded_file = request.files['file']
        filename = uploaded_file.filename or 'receipt.jpg'
        mime_type = uploaded_file.content_type or 'image/jpeg'
        file_bytes = uploaded_file.read()
    elif request.is_json and request.json.get('data_base64'):
        import base64
        file_bytes = base64.b64decode(request.json['data_base64'])
        filename = request.json.get('filename', 'receipt.jpg')
        mime_type = request.json.get('mime_type', 'image/jpeg')
    elif request.data:
        file_bytes = request.data
        filename = request.headers.get('X-Filename', 'receipt.jpg')
        mime_type = request.headers.get('Content-Type', 'image/jpeg')

    if not file_bytes:
        return jsonify({'ok': False, 'message': 'Không có dữ liệu file'}), 400

    media = save_bill_media(media_id, file_bytes, filename, mime_type, tg_file_id)
    return jsonify({
        'ok': True,
        'id': media.id,
        'url': media.storage_url,
        'view_url': f"/advances/bill/{media.id}",
        'filename': media.filename,
        'size': media.file_size
    })


@advances_bp.route('/api/sync-bills', methods=['POST'])
@login_required
def sync_bills():
    """Đồng bộ toàn bộ hóa đơn từ Google Sheet FileDB về Supabase"""
    count, err = sync_all_bills_from_filedb()
    if err:
        return jsonify({'success': False, 'message': err}), 500
    return jsonify({'success': True, 'count': count, 'message': f'Đã đồng bộ {count} hóa đơn về Supabase!'})

