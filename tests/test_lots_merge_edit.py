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
