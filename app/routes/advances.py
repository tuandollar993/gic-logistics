import os
import hmac
from urllib.parse import urlparse
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    jsonify, send_file, Response, abort, current_app
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import CashAdvanceMonthly, CashAdvanceTransaction, CashAdvanceBillMedia, Lot, OperatingCost
from app.security import (
    manager_required,
    admin_required,
    csrf_exempt,
    validate_bill_file,
    check_rate_limit,
    log_audit
)
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


def _is_allowed_legacy_storage_url(url):
    """Only permit the configured Supabase storage host for legacy bill URLs."""
    configured = os.environ.get('SUPABASE_URL', '').strip()
    parsed = urlparse(url or '')
    allowed = urlparse(configured).hostname if configured else None
    return bool(
        parsed.scheme == 'https' and parsed.hostname and allowed
        and hmac.compare_digest(parsed.hostname.lower(), allowed.lower())
    )


def _parse_optional_id(value, label):
    if value in (None, ''):
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f'{label} không hợp lệ'
    if parsed <= 0:
        return None, f'{label} không hợp lệ'
    return parsed, None

@advances_bp.route('/', methods=['GET'])
@login_required
@manager_required
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
@manager_required
def sync_data():
    month = request.form.get('month', type=int) or (request.get_json(silent=True) or {}).get('month', 8)
    year = request.form.get('year', type=int) or (request.get_json(silent=True) or {}).get('year', 2026)

    # Check month lock
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    if monthly and monthly.is_locked:
        msg = f"Tháng {month:02d}/{year} đã bị KHÓA SỔ. Không thể đồng bộ đè dữ liệu!"
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 403
        flash(msg, "warning")
        return redirect(url_for('advances.index', month=month, year=year))

    monthly, err = sync_month_from_google(month, year)
    if err:
        if request.is_json:
            return jsonify({'success': False, 'message': err}), 400
        flash(f"Lỗi đồng bộ từ Google Sheet: {err}", "danger")
    else:
        log_audit('sync_cashflow', 'cash_advance', f"{month}/{year}", f"Synced cashflow for {month}/{year}")
        msg = f"Đồng bộ thành công Tháng {month:02d}/{year} từ Google Sheet 'Dòng tiền GIDO theo tháng 2026'!"
        if request.is_json:
            return jsonify({'success': True, 'message': msg})
        flash(msg, "success")

    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/webhook', methods=['POST'])
@csrf_exempt
def google_sheet_webhook():
    """
    Webhook nhận tín hiệu tự động từ Google Apps Script mỗi khi có chỉnh sửa trên Google Sheet.
    Xác thực bằng X-Webhook-Secret header với hmac.compare_digest và rate limiting.
    """
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    allowed, _ = check_rate_limit(f"gsheet_hook_{client_ip}", max_attempts=15, window_seconds=60)
    if not allowed:
        return jsonify({'error': 'Too many requests'}), 429

    expected_secret = os.environ.get('WEBHOOK_SECRET')
    if not expected_secret:
        return jsonify({'error': 'Server webhook secret is not configured'}), 500

    secret = (
        request.headers.get('X-Webhook-Secret') or
        request.args.get('secret') or
        (request.get_json(silent=True) or {}).get('secret')
    )

    if not secret or not hmac.compare_digest(str(secret), str(expected_secret)):
        return jsonify({'error': 'Unauthorized'}), 401
    
    payload = request.get_json(silent=True) or {}
    month = request.args.get('month', type=int) or payload.get('month')
    year = request.args.get('year', type=int) or payload.get('year', 2026)

    try:
        from app.services.advance_service import auto_sync_active_months, sync_month_from_google
        if month:
            monthly_rec = CashAdvanceMonthly.query.filter_by(month=int(month), year=int(year)).first()
            if monthly_rec and monthly_rec.is_locked:
                return jsonify({'success': False, 'message': f'Tháng {month}/{year} đã khóa sổ'}), 403

            monthly, err = sync_month_from_google(int(month), int(year))
            if err:
                return jsonify({'success': False, 'error': err}), 500
            log_audit('webhook_sync', 'cash_advance', f"{month}/{year}", "Webhook triggered sync")
            return jsonify({'success': True, 'synced_month': month, 'synced_year': year})
        else:
            auto_sync_active_months()
            log_audit('webhook_sync_all', 'cash_advance', None, "Webhook triggered auto_sync_active_months")
            return jsonify({'success': True, 'message': 'Đã tự động đồng bộ các tháng từ Google Sheets!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@advances_bp.route('/add', methods=['POST'])
@login_required
@manager_required
def add():
    payload = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    month = int(payload.get('month', 8))
    year = int(payload.get('year', 2026))

    # Check lock
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    if monthly and monthly.is_locked:
        flash(f"Tháng {month:02d}/{year} đã bị khóa sổ. Không thể thêm giao dịch mới.", "warning")
        return redirect(url_for('advances.index', month=month, year=year))

    try:
        trans = add_transaction(payload)
        log_audit('add_transaction', 'cash_advance', trans.id, f"Added transaction in {month}/{year}: {trans.content}",
                  after_state={'trans_id': trans.id, 'content': trans.content, 'month': month, 'year': year})
        db.session.flush()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi thêm giao dịch: {e}", "danger")
        return redirect(url_for('advances.index', month=month, year=year))

    if request.is_json:
        return jsonify({'success': True, 'transaction': trans.to_dict()})

    flash("Đã thêm thành công giao dịch tạm ứng mới!", "success")
    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/update/<int:trans_id>', methods=['POST'])
@login_required
@manager_required
def update(trans_id):
    payload = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    try:
        trans = update_transaction(trans_id, payload)
        if not trans:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Không tìm thấy giao dịch hoặc tháng đã bị khóa'}), 404
            flash("Không tìm thấy giao dịch hoặc tháng đã bị khóa!", "danger")
            return redirect(url_for('advances.index'))

        log_audit('update_transaction', 'cash_advance', trans.id, f"Updated transaction {trans.id}",
                  after_state={'trans_id': trans.id, 'content': trans.content})
        db.session.flush()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 500
        flash(f"Lỗi cập nhật: {e}", "danger")
        return redirect(url_for('advances.index'))

    if request.is_json:
        return jsonify({'success': True, 'transaction': trans.to_dict()})

    flash("Cập nhật giao dịch thành công!", "success")
    return redirect(url_for('advances.index', month=trans.month, year=trans.year))


@advances_bp.route('/delete/<int:trans_id>', methods=['POST'])
@login_required
@manager_required
def delete(trans_id):
    month = request.args.get('month', type=int, default=8)
    year = request.args.get('year', type=int, default=2026)
    
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    if monthly and monthly.is_locked:
        flash(f"Tháng {month:02d}/{year} đã bị khóa sổ. Không thể xóa giao dịch.", "warning")
        return redirect(url_for('advances.index', month=month, year=year))

    try:
        ok = delete_transaction(trans_id)
        if ok:
            log_audit('delete_transaction', 'cash_advance', trans_id, f"Deleted transaction {trans_id}")
            db.session.flush()
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        ok = False

    if request.is_json:
        return jsonify({'success': ok})

    if ok:
        flash("Đã xóa bút toán tạm ứng!", "success")
    else:
        flash("Không thể xóa bút toán!", "danger")

    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/lock-month', methods=['POST'])
@login_required
@manager_required
def toggle_month_lock():
    """Khóa / Mở khóa sổ tháng dòng tiền để chống ghi đè dữ liệu"""
    month = request.form.get('month', type=int) or (request.get_json(silent=True) or {}).get('month')
    year = request.form.get('year', type=int) or (request.get_json(silent=True) or {}).get('year', 2026)

    if not month or not year:
        return jsonify({'success': False, 'message': 'Thiếu tham số tháng hoặc năm'}), 400

    try:
        monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
        if not monthly:
            monthly = CashAdvanceMonthly(month=month, year=year)
            db.session.add(monthly)

        monthly.is_locked = not monthly.is_locked
        if monthly.is_locked:
            monthly.locked_at = datetime.now(timezone.utc)
            monthly.locked_by = current_user.id
            status_msg = f"Đã KHÓA SỔ Tháng {month:02d}/{year}. Không cho phép đồng bộ hoặc chỉnh sửa."
            log_audit('lock_month', 'cash_advance', f"{month}/{year}", "Locked cashflow month",
                      after_state={'is_locked': True, 'month': month, 'year': year})
        else:
            monthly.locked_at = None
            monthly.locked_by = None
            status_msg = f"Đã MỞ KHÓA SỔ Tháng {month:02d}/{year}."
            log_audit('unlock_month', 'cash_advance', f"{month}/{year}", "Unlocked cashflow month",
                      after_state={'is_locked': False, 'month': month, 'year': year})

        db.session.flush()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Lỗi khóa/mở khóa sổ: {e}"}), 500

    if request.is_json:
        return jsonify({'success': True, 'is_locked': monthly.is_locked, 'message': status_msg})

    flash(status_msg, "info")
    return redirect(url_for('advances.index', month=month, year=year))


@advances_bp.route('/export', methods=['GET'])
@login_required
@manager_required
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
@login_required
def view_bill(bill_id):
    """
    Phục vụ trực tiếp ảnh biên lai/hóa đơn lưu từ Supabase với kiểm tra quyền truy cập qua Foreign Keys:
    - Manager và Admin được xem tất cả bill.
    - Staff chỉ được xem bill nếu:
      1. media.uploaded_by == current_user.id
      2. media.lot_id: lot.assigned_to == current_user.id or lot.created_by == current_user.id
      3. media.operating_cost_id: cost.filled_by == current_user.id or cost.lot thuộc user.
      4. Bill gắn transaction chưa có owner FK: chỉ manager/admin hoặc uploader được xem.
    - Headers bảo mật: private cache, no-sniff, không redirect ra URL public.
    """
    import base64
    import requests

    media = get_bill_media(bill_id)
    if not media:
        return jsonify({'error': 'Không tìm thấy hóa đơn/chứng từ'}), 404

    # 1. RBAC Access Control via explicit Foreign Keys
    if current_user.role not in ('admin', 'manager'):
        allowed = False
        if media.uploaded_by and media.uploaded_by == current_user.id:
            allowed = True
        elif media.lot_id:
            from app.models import Lot
            lot = db.session.get(Lot, media.lot_id)
            if lot and (lot.assigned_to == current_user.id or lot.created_by == current_user.id):
                allowed = True
        elif media.operating_cost_id:
            from app.models import OperatingCost
            cost = db.session.get(OperatingCost, media.operating_cost_id)
            if cost:
                if cost.filled_by == current_user.id:
                    allowed = True
                elif cost.lot and (cost.lot.assigned_to == current_user.id or cost.lot.created_by == current_user.id):
                    allowed = True
        # A CashAdvanceTransaction has no owner FK.  Never infer ownership by
        # matching names inside free-text content; that was an IDOR risk.

        if not allowed:
            abort(403, description="Forbidden: Bạn không có quyền truy cập hóa đơn/chứng từ này.")

    raw_bytes = None
    mime = media.mime_type or 'image/jpeg'

    if media.data_base64:
        try:
            raw_bytes = base64.b64decode(media.data_base64)
        except Exception as e:
            return jsonify({'error': f'Lỗi đọc ảnh: {e}'}), 500
    elif media.storage_url and media.storage_url.startswith('http'):
        if not _is_allowed_legacy_storage_url(media.storage_url):
            return jsonify({'error': 'URL bộ lưu trữ lịch sử không được phép'}), 403
        try:
            s_resp = requests.get(media.storage_url, timeout=15, stream=True)
            if s_resp.status_code == 200:
                raw_bytes = s_resp.content
                if 'Content-Type' in s_resp.headers:
                    mime = s_resp.headers['Content-Type'].split(';')[0].strip()
            else:
                return jsonify({'error': 'Không thể tải file từ bộ lưu trữ'}), 502
        except Exception as e:
            return jsonify({'error': f'Lỗi kết nối bộ lưu trữ: {e}'}), 502
    else:
        return jsonify({'error': 'Không tìm thấy dữ liệu hóa đơn/chứng từ'}), 404

    resp = Response(raw_bytes, mimetype=mime)
    resp.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Disposition'] = f'inline; filename="{media.filename or "receipt.jpg"}"'
    return resp


@advances_bp.route('/api/upload-bill', methods=['POST'])
@csrf_exempt
def upload_bill_api():
    """
    API cho phép Bot hoặc Web upload ảnh hóa đơn trực tiếp lên Supabase.
    - Web user: bắt buộc role Manager hoặc Admin.
    - Bot / Machine: bắt buộc header X-Bot-Token hoặc Authorization khớp BOT_UPLOAD_SECRET riêng biệt.
    - Kiểm tra file chặt chẽ bằng validate_bill_file().
    - Trả về { ok: True, bill_id, bill_url: /advances/bill/<id>, filename }. Tuyệt đối KHÔNG trả về storage_url public.
    """
    if current_user.is_authenticated:
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'ok': False, 'message': 'Forbidden: Chỉ Quản lý hoặc Quản trị viên mới được upload hóa đơn qua giao diện web'}), 403
    else:
        bot_token_header = request.headers.get('X-Bot-Token') or request.headers.get('Authorization', '').replace('Bearer ', '').strip()
        expected_secret = os.environ.get('BOT_UPLOAD_SECRET') or current_app.config.get('BOT_UPLOAD_SECRET', '')
        if not expected_secret or not bot_token_header or not hmac.compare_digest(bot_token_header, expected_secret):
            return jsonify({'ok': False, 'message': 'Unauthorized: Yêu cầu Bot Upload Token hợp lệ (BOT_UPLOAD_SECRET)'}), 401

    payload_json = request.get_json(silent=True) or {}
    media_id = request.form.get('id') or payload_json.get('id')
    tg_file_id = request.form.get('file_id') or payload_json.get('file_id')
    tx_id = request.form.get('transaction_id') or payload_json.get('transaction_id')
    cost_id = request.form.get('operating_cost_id') or payload_json.get('operating_cost_id')
    lot_id = request.form.get('lot_id') or payload_json.get('lot_id')

    file_bytes = None
    filename = 'receipt.jpg'
    mime_type = 'image/jpeg'

    if 'file' in request.files:
        uploaded_file = request.files['file']
        filename = uploaded_file.filename or 'receipt.jpg'
        file_bytes = uploaded_file.read()
    elif request.is_json and payload_json.get('data_base64'):
        import base64
        try:
            file_bytes = base64.b64decode(payload_json['data_base64'])
        except Exception:
            return jsonify({'ok': False, 'message': 'Chuỗi base64 không hợp lệ'}), 400
        filename = payload_json.get('filename', 'receipt.jpg')
    elif request.data:
        file_bytes = request.data
        filename = request.headers.get('X-Filename', 'receipt.jpg')

    if not file_bytes:
        return jsonify({'ok': False, 'message': 'Không có dữ liệu file'}), 400

    # Strict file validation
    is_valid, err_or_mime = validate_bill_file(file_bytes, filename)
    if not is_valid:
        return jsonify({'ok': False, 'message': f'File không hợp lệ: {err_or_mime}'}), 400

    mime_type = err_or_mime
    tx_id, error = _parse_optional_id(tx_id, 'transaction_id')
    if error:
        return jsonify({'ok': False, 'message': error}), 400
    cost_id, error = _parse_optional_id(cost_id, 'operating_cost_id')
    if error:
        return jsonify({'ok': False, 'message': error}), 400
    lot_id, error = _parse_optional_id(lot_id, 'lot_id')
    if error:
        return jsonify({'ok': False, 'message': error}), 400

    # Validate every supplied FK before writing.  This yields a useful 404 on
    # pre-0003 schemas too, rather than relying on a database constraint.
    if tx_id and not db.session.get(CashAdvanceTransaction, tx_id):
        return jsonify({'ok': False, 'message': 'Không tìm thấy transaction_id'}), 404
    if cost_id and not db.session.get(OperatingCost, cost_id):
        return jsonify({'ok': False, 'message': 'Không tìm thấy operating_cost_id'}), 404
    if lot_id and not db.session.get(Lot, lot_id):
        return jsonify({'ok': False, 'message': 'Không tìm thấy lot_id'}), 404

    uploaded_by = current_user.id if current_user.is_authenticated else None
    try:
        media = save_bill_media(
            media_id=media_id, file_bytes=file_bytes, filename=filename,
            mime_type=mime_type, tg_file_id=tg_file_id, transaction_id=tx_id,
            operating_cost_id=cost_id, lot_id=lot_id, uploaded_by=uploaded_by
        )
        log_audit('upload_bill', 'bill', media.id,
                  f'Uploaded bill {media.id} ({filename}, {len(file_bytes)} bytes)')
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Unable to save bill and audit record atomically')
        return jsonify({'ok': False, 'message': 'Không thể lưu hóa đơn'}), 500

    return jsonify({
        'ok': True,
        'id': media.id,
        'bill_id': media.id,
        'bill_url': f"/advances/bill/{media.id}",
        'view_url': f"/advances/bill/{media.id}",
        'filename': media.filename,
        'size': media.file_size
    })


@advances_bp.route('/api/sync-bills', methods=['POST'])
@login_required
@manager_required
def sync_bills():
    """Đồng bộ toàn bộ hóa đơn từ Google Sheet FileDB về Supabase"""
    count, err = sync_all_bills_from_filedb()
    if err:
        return jsonify({'success': False, 'message': err}), 500
    log_audit('sync_bills_filedb', 'bill', None, f'Synced {count} bills from FileDB')
    db.session.flush()
    db.session.commit()
    return jsonify({'success': True, 'count': count, 'message': f'Đã đồng bộ {count} hóa đơn về Supabase!'})


def _get_telegram_secret_token():
    from app.config import Config
    tok = os.environ.get('TELEGRAM_SECRET_TOKEN')
    if tok is None:
        tok = getattr(Config, 'TELEGRAM_SECRET_TOKEN', None)
    if tok is None:
        tok = current_app.config.get('TELEGRAM_SECRET_TOKEN', '')
    return tok

@advances_bp.route('/bot-webhook', methods=['POST'])
@advances_bp.route('/telegram-bot-webhook', methods=['POST'])
@csrf_exempt
def telegram_cashflow_webhook():
    """Nhận webhook từ Telegram Bot (@gidotien_bot) để đọc bill và lưu Supabase (Fail-Closed)"""
    expected_token = _get_telegram_secret_token()
    if not expected_token:
        return jsonify({'ok': False, 'error': 'Webhook secret token not configured on server'}), 401

    secret_header = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not secret_header or not hmac.compare_digest(secret_header, expected_token):
        return jsonify({'ok': False, 'error': 'Invalid or missing secret token'}), 401

    client_ip = (request.headers.get('X-Forwarded-For') or request.remote_addr).split(',')[0].strip()
    allowed, _ = check_rate_limit(f"tg_bot_hook_{client_ip}", max_attempts=120, window_seconds=60)
    if not allowed:
        return jsonify({'ok': False, 'error': 'Rate limit exceeded'}), 429

    from app.services.cashflow_bot_service import handle_telegram_update
    update = request.get_json(force=True, silent=True)
    if update:
        try:
            handle_telegram_update(update)
        except Exception as e:
            print(f"[AdvancesRoute] Error in telegram webhook: {e}")
    return jsonify({'ok': True})


@advances_bp.route('/set-telegram-webhook', methods=['POST'])
@csrf_exempt
@login_required
@admin_required
def set_telegram_webhook():
    """Cài đặt webhook cho @gidotien_bot trỏ thẳng về server kèm Secret Token bảo mật"""
    import urllib.parse
    import requests
    from app.services.cashflow_bot_service import CASHFLOW_BOT_TOKEN

    expected_token = _get_telegram_secret_token()
    if not expected_token:
        return jsonify({'error': 'TELEGRAM_SECRET_TOKEN chưa được cấu hình'}), 400

    if not CASHFLOW_BOT_TOKEN:
        return jsonify({'error': 'CASHFLOW_BOT_TOKEN chưa được cấu hình trong biến môi trường'}), 500

    target_url = (request.form.get('url') or (request.get_json(silent=True) or {}).get('url') or f"{request.host_url.rstrip('/')}/advances/bot-webhook").strip()

    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme != 'https':
        return jsonify({'error': 'Invalid webhook URL: Chỉ chấp nhận URL HTTPS bảo mật'}), 400

    hostname = (parsed.hostname or '').lower()
    if not hostname or hostname in ('localhost', '127.0.0.1') or hostname.startswith('192.168.') or hostname.startswith('10.'):
        return jsonify({'error': 'Invalid webhook URL: Không chấp nhận localhost hoặc IP nội bộ'}), 400

    req_host = (request.host.split(':')[0]).lower()
    allowed_hosts = {req_host, 'gic-logistics.onrender.com'}
    configured_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if configured_host:
        allowed_hosts.add(configured_host.lower())
    if hostname not in allowed_hosts:
        return jsonify({'error': f'Invalid webhook URL: Host {hostname} không nằm trong danh sách máy chủ hợp lệ'}), 400

    if parsed.path not in ('/advances/bot-webhook', '/advances/telegram-bot-webhook'):
        return jsonify({'error': 'Invalid webhook URL: Đường dẫn webhook không hợp lệ'}), 400

    set_endpoint = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/setWebhook"
    payload = {
        'url': target_url,
        'secret_token': expected_token,
        'allowed_updates': ['message', 'edited_message', 'callback_query']
    }

    try:
        res = requests.post(set_endpoint, json=payload, timeout=10).json()
        info_endpoint = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/getWebhookInfo"
        info = requests.get(info_endpoint, timeout=10).json()
    except Exception as e:
        return jsonify({'error': f'Lỗi kết nối Telegram API: {e}'}), 502

    log_audit('set_telegram_webhook', 'telegram_webhook', None, f"Webhook set to {target_url}")
    db.session.flush()
    db.session.commit()
    return jsonify({'set_result': res, 'current_info': info, 'target_url': target_url})
