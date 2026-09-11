import os
import base64
import pytest
from app.models import CashAdvanceBillMedia, Lot, OperatingCost, CashAdvanceTransaction
from app.extensions import db

def test_bill_view_unauthenticated(client):
    res = client.get('/advances/bill/test_bill_1')
    assert res.status_code in (302, 401)

def test_bill_view_headers(auth_client_manager, app):
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
        bf = CashAdvanceBillMedia(
            id='test_bill_1',
            filename='test_bill.png',
            mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'),
            file_size=len(raw_png)
        )
        db.session.add(bf)
        db.session.commit()

    res = auth_client_manager.get('/advances/bill/test_bill_1')
    assert res.status_code == 200
    assert res.headers.get('X-Content-Type-Options') == 'nosniff'
    assert 'private' in res.headers.get('Cache-Control', '')
    assert 'no-store' in res.headers.get('Cache-Control', '')

def test_staff_cannot_view_unassigned_bill(auth_client_staff, app):
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
        bf = CashAdvanceBillMedia(
            id='test_bill_unassigned',
            filename='secret.png',
            mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'),
            file_size=len(raw_png)
        )
        db.session.add(bf)
        db.session.commit()

    res = auth_client_staff.get('/advances/bill/test_bill_unassigned')
    assert res.status_code == 403

def test_staff_can_view_assigned_bill(auth_client_staff, staff_user, app):
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
        lot = Lot(
            month=8,
            year=2026,
            lot_label='LÔ TEST ASSIGNED',
            assigned_to=staff_user
        )
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description='Chi phí hải quan test_bill_assigned',
            cost_amount=500000.0,
            note='test_bill_assigned'
        )
        db.session.add(cost)
        db.session.flush()

        bf = CashAdvanceBillMedia(
            id='test_bill_assigned',
            filename='assigned.png',
            mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'),
            file_size=len(raw_png),
            operating_cost_id=cost.id,
            lot_id=lot.id
        )
        db.session.add(bf)
        db.session.commit()

    res = auth_client_staff.get('/advances/bill/test_bill_assigned')
    assert res.status_code == 200


def test_staff_can_view_bill_for_cost_they_filled(auth_client_staff, staff_user, app):
    """Cost-linked bills must use filled_by, not the non-existent created_by."""
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        lot = Lot(month=8, year=2026, lot_label='LÔ COST OWNER')
        db.session.add(lot)
        db.session.flush()
        cost = OperatingCost(lot_id=lot.id, description='Cost owner', filled_by=staff_user)
        db.session.add(cost)
        db.session.flush()
        db.session.add(CashAdvanceBillMedia(
            id='test_bill_cost_owner', filename='owner.png', mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'), file_size=len(raw_png),
            operating_cost_id=cost.id
        ))
        db.session.commit()

    assert auth_client_staff.get('/advances/bill/test_bill_cost_owner').status_code == 200


def test_staff_cannot_view_transaction_bill_from_content(auth_client_staff, staff_user, app):
    """Free text mentioning a user must never grant bill access."""
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        tx = CashAdvanceTransaction(month=8, year=2026, content='Chi cho Staff Test')
        db.session.add(tx)
        db.session.flush()
        db.session.add(CashAdvanceBillMedia(
            id='test_bill_transaction_private', filename='transaction.png', mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'), file_size=len(raw_png),
            transaction_id=tx.id
        ))
        db.session.commit()

    assert auth_client_staff.get('/advances/bill/test_bill_transaction_private').status_code == 403

def test_staff_can_view_own_uploaded_bill(auth_client_staff, staff_user, app):
    with app.app_context():
        raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
        bf = CashAdvanceBillMedia(
            id='test_bill_own',
            filename='own.png',
            mime_type='image/png',
            data_base64=base64.b64encode(raw_png).decode('ascii'),
            file_size=len(raw_png),
            uploaded_by=staff_user
        )
        db.session.add(bf)
        db.session.commit()

    res = auth_client_staff.get('/advances/bill/test_bill_own')
    assert res.status_code == 200


def test_upload_bill_rbac_web_staff(auth_client_staff):
    # Staff upload via web is rejected with 403
    res_staff = auth_client_staff.post('/advances/api/upload-bill', data={})
    assert res_staff.status_code == 403

def test_upload_bill_rbac_web_manager(auth_client_manager):
    # Manager upload via web is allowed through auth (fails with 400 for empty data)
    res_mgr = auth_client_manager.post('/advances/api/upload-bill', data={})
    assert res_mgr.status_code == 400
    assert 'Không có dữ liệu file' in res_mgr.get_json().get('message', '')

def test_upload_bill_bot_token(client, monkeypatch):
    monkeypatch.setenv('BOT_UPLOAD_SECRET', 'super_secret_upload_key_123')
    raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'

    # Unauthorized without secret
    res_no_auth = client.post(
        '/advances/api/upload-bill',
        json={'data_base64': base64.b64encode(raw_png).decode('ascii'), 'filename': 'receipt.png'}
    )
    assert res_no_auth.status_code == 401

    # Unauthorized with wrong secret
    res_bad_auth = client.post(
        '/advances/api/upload-bill',
        headers={'X-Bot-Token': 'wrong_token'},
        json={'data_base64': base64.b64encode(raw_png).decode('ascii'), 'filename': 'receipt.png'}
    )
    assert res_bad_auth.status_code == 401

    # Authorized with BOT_UPLOAD_SECRET
    res_good = client.post(
        '/advances/api/upload-bill',
        headers={'X-Bot-Token': 'super_secret_upload_key_123'},
        json={'data_base64': base64.b64encode(raw_png).decode('ascii'), 'filename': 'receipt.png', 'id': 'bot_bill_1'}
    )
    assert res_good.status_code == 200
    assert res_good.get_json()['ok'] is True


def test_upload_bill_rejects_unknown_fk(auth_client_manager):
    raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    res = auth_client_manager.post('/advances/api/upload-bill', json={
        'data_base64': base64.b64encode(raw_png).decode('ascii'), 'filename': 'receipt.png',
        'transaction_id': 999999
    })
    assert res.status_code == 404


def test_upload_bill_rolls_back_when_audit_fails(auth_client_manager, app, monkeypatch):
    """The DB bill row must not survive an audit failure."""
    import app.routes.advances as advances_routes
    monkeypatch.setattr(advances_routes, 'log_audit', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('audit failed')))
    raw_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    response = auth_client_manager.post('/advances/api/upload-bill', json={
        'id': 'rollback_bill', 'filename': 'receipt.png',
        'data_base64': base64.b64encode(raw_png).decode('ascii')
    })
    assert response.status_code == 500
    with app.app_context():
        assert db.session.get(CashAdvanceBillMedia, 'rollback_bill') is None

def test_bill_upload_validates_file():
    from app.security import validate_bill_file
    fake_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    valid, res_val = validate_bill_file(fake_png, 'receipt.png')
    assert valid is True
    assert res_val == 'image/png'

    fake_script = b'<' + b'script>alert(1)<' + b'/script>'
    valid, err = validate_bill_file(fake_script, 'receipt.png')
    assert valid is False

    polyglot = b'\x89PNG\r\n\x1a\n<' + b'?p' + b'hp echo 1; ?>'
    valid, err = validate_bill_file(polyglot, 'receipt.png')
    assert valid is False
    assert 'thực thi' in err or 'độc hại' in err
