from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User

auth_bp = Blueprint('auth', __name__)

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash('Bạn không có quyền truy cập chức năng này (chỉ dành cho Quản lý).', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('Tài khoản của bạn đã bị vô hiệu hóa.', 'danger')
                return render_template('login.html')
            login_user(user, remember=remember)
            flash(f'Chào mừng {user.full_name} ({user.role.upper()}) trở lại!', 'success')
            next_page = request.args.get('next')
            if user.role == 'staff':
                return redirect(next_page or url_for('tasks.my_tasks'))
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không chính xác.', 'danger')
            
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Bạn đã đăng xuất thành công.', 'info')
    return redirect(url_for('auth.login'))
