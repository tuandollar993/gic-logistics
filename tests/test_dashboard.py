import pytest
from app.models import Lot, Customer

def test_dashboard_requires_auth(client):
    res = client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_dashboard_requires_manager(auth_client_staff):
    res = auth_client_staff.get('/')
    assert res.status_code == 403

def test_dashboard_accessible_by_manager(app, auth_client_manager):
    with app.app_context():
        from app.extensions import db
        cust = Customer(name='Test Customer')
        db.session.add(cust)
        db.session.commit()

        lot = Lot(
            lot_label='LOT-TEST-01',
            month=8,
            year=2026,
            customer_id=cust.id
        )
        db.session.add(lot)
        db.session.commit()

    res = auth_client_manager.get('/')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'Dashboard' in html
    assert 'Top Lô Hàng' in html or 'kpi' in html

def test_dashboard_api_endpoints(auth_client_manager):
    res_kpis = auth_client_manager.get('/api/dashboard/kpis?month=8&year=2026')
    assert res_kpis.status_code == 200

    res_trend = auth_client_manager.get('/api/dashboard/trend?year=2026')
    assert res_trend.status_code == 200

    res_cust = auth_client_manager.get('/api/dashboard/customers?month=8&year=2026')
    assert res_cust.status_code == 200
