import pytest
from flask import url_for
from app.models import Customer, Lot, RevenueItem, OperatingCost, User
from app.extensions import db
from app.services.customer_service import (
    normalize_customer_name,
    get_or_create_canonical_customer,
    merge_customers,
    clean_and_migrate_all_customers
)


def test_normalize_customer_name_aliases():
    """Kiểm tra quy tắc chuẩn hóa tên khách hàng, mã và người liên hệ"""
    # Keep Rise variations
    name, code, contact = normalize_customer_name('Keeprise')
    assert name == 'Keep Rise'
    assert code == 'KEEPRISE'

    name, code, contact = normalize_customer_name('keep rise')
    assert name == 'Keep Rise'

    # Sunluxe with contact prefix
    name, code, contact = normalize_customer_name('MR THẮNG_Sunluxe')
    assert name == 'Sunluxe'
    assert code == 'SUNLUXE'
    assert contact == 'Mr. Thắng'

    name, code, contact = normalize_customer_name('Anh Thắng _Sunluxe')
    assert name == 'Sunluxe'
    assert contact == 'Mr. Thắng'

    # JiaYi with contact prefix
    name, code, contact = normalize_customer_name('MR THẮNG_Jiayi VN')
    assert name == 'JiaYi'
    assert contact == 'Mr. Thắng'

    # Huy Hoàng unicode NFC
    name, code, contact = normalize_customer_name('Huy Hoàng')
    assert name == 'Huy Hoàng'


def test_get_or_create_canonical_customer(app):
    """Kiểm tra tạo mới và lấy lại khách hàng chuẩn hóa"""
    with app.app_context():
        c1 = get_or_create_canonical_customer('MR THẮNG_Sunluxe')
        assert c1.name == 'Sunluxe'
        assert c1.contact_person == 'Mr. Thắng'

        c2 = get_or_create_canonical_customer('Sunluxe')
        assert c2.id == c1.id
        assert c2.name == 'Sunluxe'


def test_customer_kpi_and_properties(app):
    """Kiểm tra tính toán KPI tài chính: số lô, doanh thu, chi phí, lợi nhuận, biên LN"""
    with app.app_context():
        cust = Customer(name='Công Ty Test KPI', code='TESTKPI')
        db.session.add(cust)
        db.session.flush()

        # Tạo 2 lô hàng cho khách hàng
        lot1 = Lot(
            lot_label='Lô Test 1',
            month=8,
            year=2026,
            customer_id=cust.id,
            company=cust.name,
            source_type='gido'
        )
        lot2 = Lot(
            lot_label='Lô Test 2',
            month=8,
            year=2026,
            customer_id=cust.id,
            company=cust.name,
            source_type='gido'
        )
        db.session.add_all([lot1, lot2])
        db.session.flush()

        # Thêm doanh thu và chi phí cho Lot 1: Sell 10M, Buy 6M, Ops 1M -> Net = 3M
        r1 = RevenueItem(lot_id=lot1.id, service_description='Cước test 1', sell_price=10000000.0, buy_price=6000000.0)
        c1 = OperatingCost(lot_id=lot1.id, description='Chi phí test 1', cost_amount=1000000.0, total_amount=1000000.0)

        # Lot 2: Sell 5M, Buy 3M, Ops 0 -> Net = 2M
        r2 = RevenueItem(lot_id=lot2.id, service_description='Cước test 2', sell_price=5000000.0, buy_price=3000000.0)

        db.session.add_all([r1, c1, r2])
        db.session.commit()

        # Refresh
        cust = Customer.query.get(cust.id)
        assert cust.total_lots == 2
        assert cust.total_revenue == 15000000.0
        assert cust.total_cost == (6000000.0 + 1000000.0 + 3000000.0)
        assert cust.net_profit == 5000000.0
        assert round(cust.margin_percent, 2) == round(5000000.0 / 15000000.0 * 100, 2)


def test_merge_customers(app):
    """Kiểm tra gộp khách hàng trùng lặp vào khách hàng chuẩn"""
    with app.app_context():
        src = Customer(name='Khách Gốc Trùng', code='SRC1')
        tgt = Customer(name='Khách Chuẩn Đích', code='TGT1')
        db.session.add_all([src, tgt])
        db.session.flush()

        lot = Lot(
            lot_label='Lô Cần Chuyển',
            month=8,
            year=2026,
            customer_id=src.id,
            company=src.name,
            source_type='gido'
        )
        db.session.add(lot)
        db.session.commit()

        # Thực hiện gộp
        success, msg = merge_customers(src.id, tgt.id)
        assert success is True

        lot_updated = Lot.query.get(lot.id)
        assert lot_updated.customer_id == tgt.id
        assert lot_updated.company == tgt.name

        src_updated = Customer.query.get(src.id)
        assert src_updated.is_active is False


def test_customer_routes(auth_client_manager, app):
    """Kiểm tra các route giao diện và API khách hàng"""
    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf_token')

    # 1. Danh sách khách hàng
    resp = auth_client_manager.get('/customers/')
    assert resp.status_code == 200
    assert 'Khách Hàng' in resp.get_data(as_text=True)

    # 2. Tạo mới khách hàng
    resp = auth_client_manager.post('/customers/new', data={
        'csrf_token': csrf_token,
        'name': 'Công Ty Mới Tinh',
        'code': 'MOITINH',
        'contact_person': 'Anh Tuấn',
        'phone': '0901234567',
        'email': 'tuan@example.com',
        'address': 'Hà Nội'
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        created = Customer.query.filter_by(name='Công Ty Mới Tinh').first()
        assert created is not None
        assert created.contact_person == 'Anh Tuấn'
        cust_id = created.id

    # 3. Chi tiết khách hàng
    resp = auth_client_manager.get(f'/customers/{cust_id}')
    assert resp.status_code == 200
    assert 'Công Ty Mới Tinh' in resp.get_data(as_text=True)

    # 4. Sửa khách hàng
    resp = auth_client_manager.post(f'/customers/{cust_id}/edit', data={
        'csrf_token': csrf_token,
        'name': 'Công Ty Mới Tinh Đã Đổi Tên',
        'code': 'MOITINH',
        'contact_person': 'Anh Tuấn Giám Đốc',
        'phone': '0909999999',
        'email': 'ceo@example.com',
        'address': 'TP.HCM',
        'tax_code': '0101234567',
        'notes': 'Khách hàng VIP'
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        updated = Customer.query.get(cust_id)
        assert updated.name == 'Công Ty Mới Tinh Đã Đổi Tên'
        assert updated.contact_person == 'Anh Tuấn Giám Đốc'

    # 5. API list
    resp = auth_client_manager.get('/customers/api/list')
    assert resp.status_code == 200
    res_json = resp.get_json()
    assert res_json.get('success') is True
    data = res_json.get('data', [])
    assert isinstance(data, list)
    assert any(c['name'] == 'Công Ty Mới Tinh Đã Đổi Tên' for c in data)
