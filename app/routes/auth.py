from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from app.security import (
    is_safe_url,
    check_rate_limit,
    clear_rate_limit,
    manager_required,
    admin_required,
    role_required
)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'role', 'staff') == 'staff':
            return redirect(url_for('tasks.my_tasks'))
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        
        # 1. Rate limiting: Max 5 failed attempts per 5 minutes per IP + username
        rate_key = f"login_{client_ip}_{username.lower()}"
        allowed, wait_sec = check_rate_limit(rate_key, max_attempts=5, window_seconds=300)
        if not allowed:
            flash(f'Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng thử lại sau {wait_sec} giây.', 'danger')
            return render_template('login.html'), 429

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('Tài khoản của bạn đã bị vô hiệu hóa. Vui lòng liên hệ Quản trị viên.', 'danger')
                return render_template('login.html')

            clear_rate_limit(rate_key)
            login_user(user, remember=remember)
            flash(f'Chào mừng {user.full_name} ({user.role.upper()}) trở lại!', 'success')

            # 2. Prevent Open Redirect
            next_page = request.args.get('next')
            if next_page and not is_safe_url(next_page):
                next_page = None

            if user.role == 'staff':
                return redirect(next_page or url_for('tasks.my_tasks'))
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không chính xác.', 'danger')
            
    return render_template('login.html')

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Bạn đã đăng xuất thành công.', 'info')
    return redirect(url_for('auth.login'))
