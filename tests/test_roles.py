import pytest

def test_user_management_admin(auth_client_admin):
    res = auth_client_admin.get('/users/')
    assert res.status_code == 200

def test_user_management_manager(auth_client_manager):
    res = auth_client_manager.get('/users/')
    assert res.status_code == 403

def test_user_management_staff(auth_client_staff):
    res = auth_client_staff.get('/users/')
    assert res.status_code == 403

def test_dashboard_access_admin(auth_client_admin):
    res = auth_client_admin.get('/')
    assert res.status_code == 200

def test_dashboard_access_manager(auth_client_manager):
    res = auth_client_manager.get('/')
    assert res.status_code == 200

def test_dashboard_access_staff(auth_client_staff):
    res = auth_client_staff.get('/')
    assert res.status_code == 403

def test_advances_management_admin(auth_client_admin):
    res = auth_client_admin.get('/advances/')
    assert res.status_code == 200

def test_advances_management_manager(auth_client_manager):
    res = auth_client_manager.get('/advances/')
    assert res.status_code == 200

def test_advances_management_staff(auth_client_staff):
    res = auth_client_staff.get('/advances/')
    assert res.status_code == 403

def test_cost_entry_allowed_for_staff(auth_client_staff, staff_user, app):
    from app.models import Lot, Customer
    from app.extensions import db
    from datetime import date
    with app.app_context():
        cust = Customer(name='Test Cust Roles', code='TCR01')
        db.session.add(cust)
        db.session.flush()
        lot = Lot(
            lot_label='LOT-TEST-ROLES-01',
            customer_id=cust.id,
            status='operating',
            month=9,
            year=2026,
            start_date=date(2026, 9, 1),
            assigned_to=staff_user
        )
        db.session.add(lot)
        db.session.commit()
        lot_id = lot.id

    res = auth_client_staff.get(f'/costs/entry/{lot_id}')
    assert res.status_code == 200
