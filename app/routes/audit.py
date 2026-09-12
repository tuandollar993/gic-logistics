"""
Routes cho tính năng AI Kiểm Toán Dữ Liệu Độc Lập.
Blueprint: audit_bp, prefix: /audit
"""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.services.audit_service import AuditService

audit_bp = Blueprint('audit', __name__)

@audit_bp.route('/')
@login_required
def index():
    """Trang chủ dashboard AI Kiểm toán dữ liệu độc lập."""
    report = AuditService.get_full_audit_report()
    return render_template(
        'audit.html',
        report=report
    )

@audit_bp.route('/api/data')
@login_required
def get_audit_data():
    """API trả về JSON toàn bộ số liệu kiểm toán."""
    report = AuditService.get_full_audit_report()
    return jsonify({
        'success': True,
        'report': report
    })
