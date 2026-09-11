import pytest
from app.extensions import db
from app.models import Lot, Customer, RevenueItem, OperatingCost, CashAdvanceBillMedia
from app.routes.lots import clean_money_input


def test_clean_money_input():
    # Various money formats
    assert clean_money_input('3.250.000') == 3250000.0
    assert clean_money_input('3,250,000') == 3250000.0
    assert clean_money_input('3250000') == 3250000.0
    assert clean_money_input('3250000.0') == 3250000.0
    assert clean_money_input('3250000,0') == 3250000.0
    assert clean_money_input('3.250.000 ₫') == 3250000.0
    assert clean_money_input('3.250.000 đ') == 3250000.0
    assert clean_money_input('3.250.000 VND') == 3250000.0
    assert clean_money_input('-1.500.000') == -1500000.0
    assert clean_money_input('(1.500.000)') == -1500000.0
    assert clean_money_input('0') == 0.0
    assert clean_money_input('') == 0.0
    assert clean_money_input('-') == 0.0
    assert clean_money_input(None) == 0.0
    assert clean_money_input(4000000) == 4000000.0


def test_revenue_item_edit_syncs_excel_totals(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Test Quatest')
        db.session.add(lot)
        db.session.flush()

        # Item initially imported with 0.0 total_excel
        item = RevenueItem(
            lot_id=lot.id,
            service_description='Dịch vụ Quatest',
            buy_price=3250000.0,
            sell_price=4000000.0,
            total_buy_price_excel=0.0,
            total_sell_price_excel=0.0
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id
        lot_id = lot.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Edit item via endpoint
    res = auth_client_manager.post(f'/lots/{lot_id}/items/{item_id}/edit', data={
        'csrf_token': csrf_token,
        'buy_price': '3.250.000',
        'sell_price': '4.000.000',
        'other_surcharge': '0',
        'service_description': 'Dịch vụ Quatest'
    })
    assert res.status_code == 302

    with app.app_context():
        updated = RevenueItem.query.get(item_id)
        assert updated.total_buy_price == 3250000.0
        assert updated.total_sell_price == 4000000.0
        assert updated.total_buy_price_excel == 3250000.0
        assert updated.total_sell_price_excel == 4000000.0


def test_edit_lot_info_by_manager(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Ban Đầu', company='Cty Ban Đầu', customs_declaration='11111')
        db.session.add(lot)
        db.session.commit()
        lot_id = lot.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    res = auth_client_manager.post(f'/lots/{lot_id}/edit', data={
        'csrf_token': csrf_token,
        'lot_label': 'Lô Đã Đổi Tên',
        'company': 'Keep Rise Mới',
        'customer_name': 'Khách Mới VIP',
        'customs_declaration': '99999',
        'status': 'completed',
        'month': 9,
        'year': 2026
    }, follow_redirects=True)

    assert res.status_code == 200
    with app.app_context():
        updated = db.session.get(Lot, lot_id)
        assert updated.lot_label == 'Lô Đã Đổi Tên'
        assert updated.company == 'Keep Rise Mới'
        assert updated.customs_declaration == '99999'
        assert updated.status == 'completed'
        assert updated.month == 9
        assert updated.customer.name == 'Khách Mới VIP'


def test_merge_lots_functionality(auth_client_manager, app):
    with app.app_context():
        lot_a = Lot(month=8, year=2026, lot_label='Lô A Chính', customs_declaration='TK-A')
        lot_b = Lot(month=8, year=2026, lot_label='Lô B Kê Nhầm', customs_declaration='TK-B')
        db.session.add_all([lot_a, lot_b])
        db.session.flush()

        item_b = RevenueItem(lot_id=lot_b.id, service_description='Cước Lô B', buy_price=1000000, sell_price=1500000)
        cost_b = OperatingCost(lot_id=lot_b.id, description='Bốc xếp Lô B', total_amount=200000)
        media_b = CashAdvanceBillMedia(id='test_media_b', lot_id=lot_b.id)
        db.session.add_all([item_b, cost_b, media_b])
        db.session.commit()

        lot_a_id = lot_a.id
        lot_b_id = lot_b.id
        item_b_id = item_b.id
        cost_b_id = cost_b.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Merge lot B into lot A
    res = auth_client_manager.post(f'/lots/{lot_a_id}/merge', data={
        'csrf_token': csrf_token,
        'source_lot_id': lot_b_id
    }, follow_redirects=True)

    assert res.status_code == 200
    with app.app_context():
        loaded_a = db.session.get(Lot, lot_a_id)
        loaded_b = db.session.get(Lot, lot_b_id)

        # Lot B should be soft deleted
        assert loaded_b.is_deleted is True

        # Items, costs, and media should now belong to lot A
        loaded_item_b = db.session.get(RevenueItem, item_b_id)
        loaded_cost_b = db.session.get(OperatingCost, cost_b_id)
        loaded_media_b = db.session.get(CashAdvanceBillMedia, 'test_media_b')

        assert loaded_item_b.lot_id == lot_a_id
        assert loaded_cost_b.lot_id == lot_a_id
        assert loaded_media_b.lot_id == lot_a_id

        # Customs declaration should be concatenated
        assert 'TK-A' in loaded_a.customs_declaration
        assert 'TK-B' in loaded_a.customs_declaration


def test_edit_item_with_dot_money_formatting(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Edit Item')
        db.session.add(lot)
        db.session.flush()

        item = RevenueItem(lot_id=lot.id, service_description='Vận chuyển', buy_price=100, sell_price=200)
        cost = OperatingCost(lot_id=lot.id, description='Nâng hạ', total_amount=50)
        db.session.add_all([item, cost])
        db.session.commit()

        lot_id = lot.id
        item_id = item.id
        cost_id = cost.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Edit revenue item with dot formatted money 3.250.000 and 4.000.000
    res_item = auth_client_manager.post(f'/lots/{lot_id}/items/{item_id}/edit', data={
        'csrf_token': csrf_token,
        'service_description': 'Dịch vụ Quatest',
        'buy_price': '3.250.000',
        'sell_price': '4.000.000',
        'surcharges': '150.000'
    }, follow_redirects=True)
    assert res_item.status_code == 200

    # Edit operating cost with dot formatted money 750.000
    res_cost = auth_client_manager.post(f'/lots/{lot_id}/costs/{cost_id}/edit', data={
        'csrf_token': csrf_token,
        'service_description': 'Nâng hạ cont',
        'buy_price': '750.000',
        'sell_price': '900.000'
    }, follow_redirects=True)
    assert res_cost.status_code == 200

    with app.app_context():
        loaded_item = db.session.get(RevenueItem, item_id)
        assert loaded_item.buy_price == 3250000.0
        assert loaded_item.sell_price == 4000000.0
        assert loaded_item.other_surcharge == 150000.0
        assert loaded_item.total_buy_price == 3250000.0
        assert loaded_item.total_sell_price == 4150000.0

        loaded_cost = db.session.get(OperatingCost, cost_id)
        assert loaded_cost.total_amount == 750000.0
        assert loaded_cost.sell_price == 900000.0


def test_available_months_descending_order():
    from app.services.advance_service import get_all_available_months
    months = get_all_available_months()
    # Must be ordered descending: 12 down to 1
    month_numbers = [m for y, m in months]
    assert month_numbers == list(range(12, 0, -1))
    assert months[0] == (2026, 12)
    assert months[-1] == (2026, 1)


def test_suggest_lot_label_sequential_and_no_duplicates(app):
    from app.routes.lots import suggest_lot_label
    with app.app_context():
        # Clean test month
        code_1, num_1 = suggest_lot_label(11, 2026)
        assert code_1 == 'GIDO112026-01'
        assert num_1 == 1

        # Add lot 1 and lot 2
        lot1 = Lot(month=11, year=2026, lot_label='Lô 01')
        lot2 = Lot(month=11, year=2026, lot_label='Lô 02')
        db.session.add_all([lot1, lot2])
        db.session.commit()

        # Next should be 03
        code_3, num_3 = suggest_lot_label(11, 2026)
        assert code_3 == 'GIDO112026-03'
        assert num_3 == 3

        # Add GIDO112026-03
        lot3 = Lot(month=11, year=2026, lot_label='GIDO112026-03')
        db.session.add(lot3)
        db.session.commit()

        # Next should be 04
        code_4, num_4 = suggest_lot_label(11, 2026)
        assert code_4 == 'GIDO112026-04'
        assert num_4 == 4


def test_api_suggest_label_endpoint(auth_client_manager, app):
    res = auth_client_manager.get('/lots/api/suggest-label?month=12&year=2026')
    assert res.status_code == 200
    data = res.get_json()
    assert 'code' in data
    assert 'alt_label' in data
    assert data['code'].startswith('GIDO122026-')
    assert data['alt_label'].startswith('Lô ')


def test_create_new_lot_auto_code_and_duplicate_prevention(auth_client_manager, app):
    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # 1. Create lot with empty lot_label -> should auto assign suggested code
    res1 = auth_client_manager.post('/lots/new', data={
        'csrf_token': csrf_token,
        'customer_name': 'Khách Test Auto',
        'month': 10,
        'year': 2026,
        'lot_label': ''
    }, follow_redirects=True)
    assert res1.status_code == 200

    with app.app_context():
        created_1 = Lot.query.filter_by(month=10, year=2026, is_deleted=False).first()
        assert created_1 is not None
        assert created_1.lot_label == 'GIDO102026-01'

    # 2. Create another lot deliberately with duplicate label 'GIDO102026-01'
    res2 = auth_client_manager.post('/lots/new', data={
        'csrf_token': csrf_token,
        'customer_name': 'Khách Test Trùng',
        'month': 10,
        'year': 2026,
        'lot_label': 'GIDO102026-01'
    }, follow_redirects=True)
    assert res2.status_code == 200

    with app.app_context():
        lots = Lot.query.filter_by(month=10, year=2026, is_deleted=False).all()
        assert len(lots) == 2
        labels = [l.lot_label for l in lots]
        # Should have avoided duplicate by generating GIDO102026-02
        assert 'GIDO102026-01' in labels
        assert 'GIDO102026-02' in labels


def test_category_classification_and_descriptions(app):
    with app.app_context():
        # Test Cửa khẩu
        it_ck = RevenueItem(service_description='Phí cửa khẩu', weight_class='8T')
        assert it_ck.category == 'Cửa khẩu'
        assert it_ck.display_description == 'Phí cửa khẩu'

        # Test DVTK TQ & DVTK HQ
        it_tk_tq = RevenueItem(service_description='DVTK TQ')
        assert it_tk_tq.category == 'Tờ khai'
        assert it_tk_tq.display_description == 'Dịch vụ tờ khai Trung Quốc'

        it_tk_hq = RevenueItem(service_description='DVTK HQ')
        assert it_tk_hq.category == 'Tờ khai'
        assert it_tk_hq.display_description == 'Dịch vụ tờ khai Hải quan'

        # Test Bốc xếp
        it_bx = RevenueItem(service_description='Chi phí dịch vụ bốc xếp')
        assert it_bx.category == 'Bốc xếp'

        # Test Quatest
        it_qt = RevenueItem(service_description='Dịch vụ Quatest')
        assert it_qt.category == 'Kiểm định'

        # Test Vận chuyển
        it_vc = RevenueItem(service_description='Hữu Nghị - Phú Thọ', weight_class='25T')
        assert it_vc.category == 'Vận chuyển'

        # Test OperatingCost typo correction and classification
        op_bx = OperatingCost(cost_type='Bốp xếp', description='Bốc xếp hàng')
        assert op_bx.category == 'Bốc xếp'
        assert op_bx.display_cost_type == 'Bốc xếp'

        # Test OperatingCost items from user screenshot (Lô CP 5.0)
        op_qt = OperatingCost(cost_type='Phí thông quan', description='Quatest lấy mẫu sớm VN26040+VN26045')
        assert op_qt.category == 'Kiểm định'
        assert op_qt.display_cost_type == 'Kiểm định'

        op_bx2 = OperatingCost(cost_type='Phí thông quan', description='Bốc xếp keep VN26040+VN26045')
        assert op_bx2.category == 'Bốc xếp'

        op_kd = OperatingCost(cost_type='Phí bến bãi', description='Kiểm dịch y tế')
        assert op_kd.category == 'Kiểm định'

        op_csht = OperatingCost(cost_type='Phí bến bãi', description='Phí Cơ sở hạ tầng')
        assert op_csht.category == 'Cửa khẩu'

        op_hs = OperatingCost(cost_type='Phí thông quan', description='Xem trước hồ sơ + tiếp nhận')
        assert op_hs.category == 'Tờ khai'


def test_profit_margin_rounded(app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Test Margin')
        db.session.add(lot)
        db.session.flush()

        item = RevenueItem(lot_id=lot.id, buy_price=4370000.0, sell_price=800000.0, total_buy_price_excel=4370000.0, total_sell_price_excel=800000.0)
        db.session.add(item)
        db.session.commit()

        # (-3570000 / 800000) * 100 = -446.25%
        assert lot.profit_margin == -446.25


