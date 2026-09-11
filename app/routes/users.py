from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User
from app.security import admin_required, validate_password_strength, log_audit

users_bp = Blueprint('users', __name__)

@users_bp.route('/')
@login_required
@admin_required
def index():
    users = User.query.order_by(User.role.desc(), User.id.asc()).all()
    return render_template('users.html', users=users)

@users_bp.route('/new', methods=['POST'])
@login_required
@admin_required
def new_user():
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'staff')
    email = request.form.get('email', '').strip()
    telegram = request.form.get('telegram_chat_id', '').strip()
    
    if not username or not full_name or not password:
        flash('Vui lòng điền đầy đủ Tên đăng nhập, Họ tên và Mật khẩu.', 'danger')
        return redirect(url_for('users.index'))

    is_strong, pwd_err = validate_password_strength(password)
    if not is_strong:
        flash(f'Mật khẩu không đạt yêu cầu: {pwd_err}', 'danger')
        return redirect(url_for('users.index'))
        
    existing = User.query.filter_by(username=username).first()
    if existing:
        flash(f'Tên đăng nhập "{username}" đã tồn tại. Vui lòng chọn tên khác.', 'danger')
        return redirect(url_for('users.index'))
        
    try:
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            email=email,
            telegram_chat_id=telegram
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        log_audit('create_user', 'user', user.id, f"Created user {username} with role {role}",
                  after_state={'username': user.username, 'role': user.role, 'email': user.email})
        db.session.commit()
        flash(f'Đã thêm nhân sự "{full_name}" ({username}) thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi tạo tài khoản người dùng: {e}', 'danger')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', user.role)
    email = request.form.get('email', '').strip()
    telegram = request.form.get('telegram_chat_id', '').strip()
    password = request.form.get('password', '').strip()
    
    old_role = user.role
    if full_name:
        user.full_name = full_name
    if role in ['admin', 'manager', 'staff']:
        if user.role == 'admin' and role != 'admin':
            active_admins = User.query.filter_by(role='admin', is_active=True).count()
            if active_admins <= 1:
                flash('Không thể hạ quyền Quản trị viên duy nhất còn lại trong hệ thống!', 'danger')
                return redirect(url_for('users.index'))
        user.role = role
    user.email = email
    user.telegram_chat_id = telegram

    try:
        if password:
            is_strong, pwd_err = validate_password_strength(password)
            if not is_strong:
                flash(f'Mật khẩu không đạt: {pwd_err}', 'danger')
                return redirect(url_for('users.index'))
            user.set_password(password)
            log_audit('change_password', 'user', user.id, f"Password changed for user {user.username}")

        log_audit('update_user', 'user', user.id, f"Updated user {user.username}, role changed from {old_role} to {user.role}",
                  before_state={'role': old_role}, after_state={'role': user.role, 'email': user.email})
        db.session.flush()
        db.session.commit()
        flash(f'Đã cập nhật thông tin cho "{user.full_name}"!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi cập nhật người dùng: {e}', 'danger')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    is_strong, pwd_err = validate_password_strength(new_password)
    if not is_strong:
        flash(f'Mật khẩu mới không đạt: {pwd_err}', 'danger')
        return redirect(url_for('users.index'))

    try:
        user.set_password(new_password)
        log_audit('reset_password', 'user', user.id, f"Admin reset password for user {user.username}")
        db.session.flush()
        db.session.commit()
        flash(f'Đã đổi mật khẩu thành công cho tài khoản "{user.username}"!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi reset mật khẩu: {e}', 'danger')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_status(user_id):
    if user_id == current_user.id:
        flash('Bạn không thể tự vô hiệu hóa tài khoản của chính mình.', 'warning')
        return redirect(url_for('users.index'))

    user = User.query.get_or_404(user_id)
    if user.role == 'admin' and user.is_active:
        active_admins = User.query.filter_by(role='admin', is_active=True).count()
        if active_admins <= 1:
            flash('Không thể vô hiệu hóa Quản trị viên duy nhất còn hoạt động trong hệ thống!', 'danger')
            return redirect(url_for('users.index'))

    try:
        user.is_active = not user.is_active
        status_text = 'kích hoạt' if user.is_active else 'vô hiệu hóa'
        log_audit('toggle_user_status', 'user', user.id, f"Status toggled to {user.is_active} for {user.username}",
                  after_state={'is_active': user.is_active})
        db.session.flush()
        db.session.commit()
        flash(f'Đã {status_text} tài khoản "{user.username}"!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi thay đổi trạng thái: {e}', 'danger')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('Bạn không thể xóa tài khoản của chính mình.', 'danger')
        return redirect(url_for('users.index'))

    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        active_admins = User.query.filter_by(role='admin', is_active=True).count()
        if active_admins <= 1:
            flash('Không thể xóa Quản trị viên duy nhất trong hệ thống!', 'danger')
            return redirect(url_for('users.index'))

    # Check if assigned to any lots
    if user.assigned_lots.count() > 0 or user.assigned_tasks.count() > 0:
        flash(f'Không thể xóa nhân sự "{user.full_name}" vì đã được giao lô hàng hoặc nhiệm vụ chi phí. Hãy vô hiệu hóa tài khoản thay vì xóa.', 'warning')
        return redirect(url_for('users.index'))

    deleted_name = user.username
    deleted_id = user.id
    try:
        log_audit('delete_user', 'user', deleted_id, f"Deleted user {deleted_name}",
                  before_state={'username': deleted_name, 'id': deleted_id})
        db.session.delete(user)
        db.session.flush()
        db.session.commit()
        flash(f'Đã xóa nhân sự "{deleted_name}" khỏi hệ thống!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xóa người dùng: {e}', 'danger')
    return redirect(url_for('users.index'))
