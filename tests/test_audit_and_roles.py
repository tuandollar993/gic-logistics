import json
import pytest
from app.models import User, AuditLog
from app.extensions import db
from app.security import log_audit

def test_audit_log_atomic_transaction(app):
    with app.app_context():
        # 1. log_audit without auto_commit participates in caller transaction
        entry = log_audit(
            action='test_action',
            target_type='lot',
            target_id=10,
            details='Testing atomic log',
            before_state={'status': 'draft'},
            after_state={'status': 'approved'},
            reason='Management approved',
            actor='test_admin',
            auto_commit=False
        )
        assert entry is not None
        assert entry.actor == 'test_admin'
        assert json.loads(entry.before_state) == {'status': 'draft'}
        assert json.loads(entry.after_state) == {'status': 'approved'}
        assert entry.reason == 'Management approved'
        assert entry.request_id is not None

        # Rollback caller transaction -> entry is not saved
        db.session.rollback()
        assert AuditLog.query.filter_by(action='test_action').count() == 0

        # Commit caller transaction -> entry is saved
        log_audit(
            action='test_action_committed',
            target_type='lot',
            target_id=11,
            actor='test_admin',
            auto_commit=False
        )
        db.session.commit()
        saved = AuditLog.query.filter_by(action='test_action_committed').first()
        assert saved is not None
        assert saved.actor == 'test_admin'

def test_cannot_demote_last_admin(auth_client_admin, admin_user, app):
    # Only 1 admin exists in this test
    with app.app_context():
        assert User.query.filter_by(role='admin', is_active=True).count() == 1

    res = auth_client_admin.post(
        f'/users/{admin_user}/edit',
        data={'full_name': 'Admin Name', 'role': 'staff', 'email': '', 'telegram_chat_id': ''},
        follow_redirects=True
    )
    with app.app_context():
        u = db.session.get(User, admin_user)
        assert u.role == 'admin'

def test_cannot_delete_last_admin(auth_client_admin, admin_user, app):
    # Create another manager and staff so lots don't block
    res = auth_client_admin.post(f'/users/{admin_user}/delete', follow_redirects=True)
    with app.app_context():
        u = db.session.get(User, admin_user)
        assert u is not None
        assert u.role == 'admin'
