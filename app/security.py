import os
import re
import time
import secrets
import mimetypes
from urllib.parse import urlparse, urljoin
from functools import wraps
from flask import request, session, abort, jsonify, redirect, url_for, flash, current_app
from flask_login import current_user

# ==============================================================================
# 1. CSRF PROTECTION (Zero External Dependency, Constant-Time Comparison)
# ==============================================================================

CSRF_EXEMPT_ROUTES = set()

def csrf_exempt(f):
    """Decorator to mark a route or view function as exempt from CSRF validation."""
    f._csrf_exempt = True
    CSRF_EXEMPT_ROUTES.add(f.__name__)
    return f

def generate_csrf_token():
    """Tạo hoặc lấy CSRF token trong session của người dùng."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

def validate_csrf():
    """Kiểm tra CSRF token cho các HTTP request có thể thay đổi dữ liệu."""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return True

    # Kiểm tra xem view function có được exempt không
    if current_app and request.endpoint:
        view_func = current_app.view_functions.get(request.endpoint)
        if view_func and getattr(view_func, '_csrf_exempt', False):
            return True

    session_token = session.get('_csrf_token')
    if not session_token:
        # Nếu session chưa có token, sinh token mới và từ chối request POST hiện tại
        generate_csrf_token()
        return False

    # Lấy token từ header hoặc form hoặc JSON body
    request_token = (
        request.headers.get('X-CSRFToken') or
        request.headers.get('X-CSRF-Token') or
        request.form.get('csrf_token') or
        (request.get_json(silent=True) or {}).get('csrf_token')
    )

    if not request_token or not isinstance(request_token, str):
        return False

    return secrets.compare_digest(session_token, request_token)


# ==============================================================================
# 2. ROLE MATRIX & AUTHORIZATION DECORATORS
# ==============================================================================

def role_required(*allowed_roles):
    """
    Decorator kiểm tra vai trò người dùng (Staff / Manager / Admin).
    Từ chối truy cập từ backend nếu không có quyền.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': 'Yêu cầu đăng nhập'}), 401
                return redirect(url_for('auth.login', next=request.url))
            
            user_role = getattr(current_user, 'role', 'staff')
            if user_role not in allowed_roles:
                msg = f"Bạn không có quyền truy cập trang này (Yêu cầu: {', '.join(allowed_roles)})."
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': msg, 'role': user_role}), 403
                from flask import abort
                abort(403)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Chỉ dành riêng cho Admin hệ thống."""
    return role_required('admin')(f)

def manager_required(f):
    """Dành cho Manager hoặc Admin."""
    return role_required('manager', 'admin')(f)


# ==============================================================================
# 3. OPEN REDIRECT PREVENTION
# ==============================================================================

def is_safe_url(target):
    """Xác thực URL redirect là an toàn (nằm trên cùng host, không redirect ra ngoài)."""
    if not target or not isinstance(target, str):
        return False
    target = target.strip()
    if target.startswith('//') or '\\' in target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


# ==============================================================================
# 4. IN-MEMORY RATE LIMITER
# ==============================================================================

_rate_limits = {}

def check_rate_limit(key, max_attempts=5, window_seconds=300):
    """
    Kiểm tra giới hạn tần suất thao tác (Rate Limit).
    Mặc định 5 lần trong 5 phút.
    Trả về (is_allowed, remaining_seconds).
    """
    now = time.time()
    history = _rate_limits.get(key, [])
    # Loại bỏ các lần thử đã quá hạn window
    history = [t for t in history if now - t < window_seconds]
    
    if len(history) >= max_attempts:
        remaining = int(window_seconds - (now - history[0]))
        return False, max(1, remaining)
        
    history.append(now)
    _rate_limits[key] = history
    return True, 0

def clear_rate_limit(key):
    """Xóa lịch sử khi đăng nhập thành công."""
    if key in _rate_limits:
        del _rate_limits[key]


# ==============================================================================
# 5. PASSWORD STRENGTH VALIDATION
# ==============================================================================

WEAK_PASSWORDS = {'123456', 'admin123', 'password', '12345678', 'admin@123', 'gic123456'}

def validate_password_strength(password):
    """Kiểm tra độ mạnh của mật khẩu."""
    if not password or len(password) < 8:
        return False, "Mật khẩu phải có ít nhất 8 ký tự."
    if password.lower() in WEAK_PASSWORDS:
        return False, "Mật khẩu quá đơn giản, vui lòng chọn mật khẩu an toàn hơn."
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        return False, "Mật khẩu phải chứa cả chữ và số."
    return True, ""


# ==============================================================================
# 6. BILL FILE VALIDATION (MAGIC BYTES & MIME INSPECTION)
# ==============================================================================

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'pdf'}
ALLOWED_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
    'application/pdf'
}

# Magic bytes signatures
MAGIC_NUMBERS = {
    'jpeg': b'\xFF\xD8\xFF',
    'png': b'\x89PNG\r\n\x1a\n',
    'pdf': b'%PDF',
}

def validate_bill_file(file_bytes, filename, max_size_bytes=10 * 1024 * 1024):
    """
    Xác thực nghiêm ngặt file hóa đơn upload:
    - Kích thước không vượt quá max_size_bytes (10MB)
    - Phần mở rộng hợp lệ
    - Magic bytes khớp chính xác với định dạng công bố
    """
    if not file_bytes:
        return False, "Dữ liệu file rỗng."
        
    if len(file_bytes) > max_size_bytes:
        return False, f"Dung lượng file vượt quá giới hạn tối đa ({max_size_bytes // (1024 * 1024)}MB)."

    # Kiểm tra đuôi file
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Định dạng file '.{ext}' không được phép. Chỉ chấp nhận: JPG, PNG, WEBP, PDF."

    # Kiểm tra Magic Bytes
    if ext in ('jpg', 'jpeg'):
        if not file_bytes.startswith(b'\xFF\xD8\xFF'):
            return False, "Nội dung file không phải định dạng JPEG hợp lệ (Magic bytes sai)."
    elif ext == 'png':
        if not file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            return False, "Nội dung file không phải định dạng PNG hợp lệ (Magic bytes sai)."
    elif ext == 'pdf':
        if not file_bytes.startswith(b'%PDF'):
            return False, "Nội dung file không phải định dạng PDF hợp lệ (Magic bytes sai)."
    elif ext == 'webp':
        if len(file_bytes) < 12 or file_bytes[:4] != b'RIFF' or file_bytes[8:12] != b'WEBP':
            return False, "Nội dung file không phải định dạng WEBP hợp lệ."

    # Kiểm tra không chứa script nguy hiểm (Polyglot HTML / PHP)
    lowered_header = file_bytes[:512].lower()
    dangerous_patterns = [b'<?php', b'<script', b'<html', b'<!doctype html', b'eval(']
    for pat in dangerous_patterns:
        if pat in lowered_header:
            return False, "Phát hiện mã thực thi độc hại trong file tải lên."

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or ('image/jpeg' if ext in ('jpg', 'jpeg') else 'application/octet-stream')
    return True, mime_type


# ==============================================================================
# 6. AUDIT TRAIL LOGGING
# ==============================================================================

SENSITIVE_AUDIT_KEYS = {'password', 'password_hash', 'token', 'secret', 'api_key', 'authorization'}

def sanitize_audit_state(state):
    """
    Loại bỏ các trường nhạy cảm (mật khẩu, password_hash, token, secret)
    khỏi before_state và after_state trong Audit Log.
    """
    if state is None:
        return None
    if isinstance(state, dict):
        clean = {}
        for k, v in state.items():
            k_lower = str(k).lower()
            if any(sk in k_lower for sk in SENSITIVE_AUDIT_KEYS):
                clean[k] = '[REDACTED]'
            else:
                clean[k] = sanitize_audit_state(v)
        return clean
    if isinstance(state, list):
        return [sanitize_audit_state(item) for item in state]
    return state


def log_audit(action, target_type, target_id=None, details=None, user_id=None, ip_address=None,
              before_state=None, after_state=None, reason=None, request_id=None, actor=None, auto_commit=False):
    """
    Ghi nhận nhật ký kiểm toán (Audit Trail) nguyên tử cùng transaction nghiệp vụ:
    - Loại bỏ auto_commit.
    - Tự động lọc sạch (sanitize) password/hash nhạy cảm.
    - Chỉ thêm AuditLog vào db.session hiện tại để commit chung 1 transaction duy nhất.
    """
    import json
    import uuid
    from flask import g
    from app.extensions import db
    from app.models import AuditLog

    uid = user_id
    if uid is None and current_user and current_user.is_authenticated:
        uid = current_user.id

    act = actor
    if not act:
        if current_user and current_user.is_authenticated:
            act = getattr(current_user, 'username', str(current_user.id))
        else:
            act = 'system'

    ip = ip_address
    if not ip and request:
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except Exception:
            ip = None

    req_id = request_id
    if not req_id and request:
        try:
            req_id = request.headers.get('X-Request-ID') or getattr(g, 'request_id', None)
        except Exception:
            pass
    if not req_id:
        req_id = uuid.uuid4().hex[:16]

    clean_before = sanitize_audit_state(before_state)
    clean_after = sanitize_audit_state(after_state)

    b_state = json.dumps(clean_before, ensure_ascii=False) if isinstance(clean_before, (dict, list)) else (str(clean_before) if clean_before is not None else None)
    a_state = json.dumps(clean_after, ensure_ascii=False) if isinstance(clean_after, (dict, list)) else (str(clean_after) if clean_after is not None else None)

    entry = AuditLog(
        user_id=uid,
        actor=act,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        before_state=b_state,
        after_state=a_state,
        reason=str(reason) if reason is not None else None,
        request_id=req_id,
        details=str(details) if details is not None else None,
        ip_address=ip
    )
    db.session.add(entry)
    return entry


