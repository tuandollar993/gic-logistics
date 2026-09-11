from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User
from app.routes.auth import manager_required

users_bp = Blueprint('users', __name__)

@users_bp.route('/')
@login_required
@manager_required
def index():
    users = User.query.order_by(User.role.desc(), User.id.asc()).all()
    return render_template('users.html', users=users)

@users_bp.route('/new', methods=['POST'])
@login_required
@manager_required
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
        
    existing = User.query.filter_by(username=username).first()
    if existing:
        flash(f'Tên đăng nhập "{username}" đã tồn tại. Vui lòng chọn tên khác.', 'danger')
        return redirect(url_for('users.index'))
        
    user = User(
        username=username,
        full_name=full_name,
        role=role,
        email=email,
        telegram_chat_id=telegram
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    flash(f'Đã thêm nhân sự "{full_name}" ({username}) thành công!', 'success')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/edit', methods=['POST'])
@login_required
@manager_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', user.role)
    email = request.form.get('email', '').strip()
    telegram = request.form.get('telegram_chat_id', '').strip()
    password = request.form.get('password', '').strip()
    
    if full_name:
        user.full_name = full_name
    if role in ['manager', 'staff']:
        user.role = role
    user.email = email
    user.telegram_chat_id = telegram
    
    if password:
        user.set_password(password)
        
    db.session.commit()
    flash(f'Đã cập nhật thông tin cho "{user.full_name}"!', 'success')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@login_required
@manager_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    
    if not new_password or len(new_password) < 4:
        flash('Mật khẩu mới phải có ít nhất 4 ký tự.', 'danger')
        return redirect(url_for('users.index'))
        
    user.set_password(new_password)
    db.session.commit()
    flash(f'Đã đổi mật khẩu thành công cho tài khoản "{user.username}"!', 'success')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@manager_required
def toggle_status(user_id):
    if user_id == current_user.id:
        flash('Bạn không thể tự vô hiệu hóa tài khoản của chính mình.', 'warning')
        return redirect(url_for('users.index'))
        
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status_text = 'kích hoạt' if user.is_active else 'vô hiệu hóa'
    flash(f'Đã {status_text} tài khoản "{user.username}"!', 'success')
    return redirect(url_for('users.index'))

@users_bp.route('/<int:user_id>/delete', methods=['POST'])
@login_required
@manager_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('Bạn không thể xóa tài khoản của chính mình.', 'danger')
        return redirect(url_for('users.index'))
        
    user = User.query.get_or_404(user_id)
    
    # Check if assigned to any lots
    if user.assigned_lots.count() > 0 or user.assigned_tasks.count() > 0:
        flash(f'Không thể xóa nhân sự "{user.full_name}" vì đã được giao lô hàng hoặc nhiệm vụ chi phí. Hãy vô hiệu hóa tài khoản thay vì xóa.', 'warning')
        return redirect(url_for('users.index'))
        
    db.session.delete(user)
    db.session.commit()
    flash(f'Đã xóa nhân sự "{user.full_name}" khỏi hệ thống!', 'success')
    return redirect(url_for('users.index'))

