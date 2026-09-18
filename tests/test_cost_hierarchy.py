import pytest
from app.extensions import db
from app.models import Lot, RevenueItem, OperatingCost

def test_operating_cost_hierarchy(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Test Phân Rã Chi Phí')
        db.session.add(lot)
        db.session.flush()

        # Create a parent operating cost (e.g. Vận chuyển tổng: 10,000,000)
        parent_cost = OperatingCost(
            lot_id=lot.id,
            cost_type='Vận chuyển',
            description='Cước vận chuyển tổng Hải Phòng - Hà Nội',
            unit_price=10000000.0,
            total_amount=10000000.0,
            sell_price=12000000.0
        )
        db.session.add(parent_cost)
        db.session.commit()

        lot_id = lot.id
        parent_cost_id = parent_cost.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Add sub-cost 1 (Xe 1: 6,000,000 mua vào, 7,000,000 bán ra)
    res1 = auth_client_manager.post(f'/lots/{lot_id}/costs/{parent_cost_id}/sub_cost', data={
        'csrf_token': csrf_token,
        'service_description': 'Xe 1: 15C-123.45',
        'supplier': 'Nhà xe Hùng Cường',
        'vehicle_plate': '15C-123.45',
        'weight_class_select': 'Vận chuyển',
        'buy_price': '6.000.000',
        'sell_price': '7.000.000',
        'invoice_classification': 'has_invoice',
        'invoice_type': 'HĐ GTGT',
        'invoice_number': '0001234'
    })
    assert res1.status_code == 302

    # Add sub-cost 2 (Xe 2: 4,500,000 mua vào, 5,500,000 bán ra)
    res2 = auth_client_manager.post(f'/lots/{lot_id}/costs/{parent_cost_id}/sub_cost', data={
        'csrf_token': csrf_token,
        'service_description': 'Xe 2: 29H-567.89',
        'supplier': 'Nhà xe Thành Long',
        'vehicle_plate': '29H-567.89',
        'weight_class_select': 'Vận chuyển',
        'buy_price': '4.500.000',
        'sell_price': '5.500.000',
        'invoice_classification': 'no_invoice'
    })
    assert res2.status_code == 302

    with app.app_context():
        p = OperatingCost.query.get(parent_cost_id)
        assert p.is_parent is True
        assert len(p.active_sub_costs) == 2
        # Sum of children: 6,000,000 + 4,500,000 = 10,500,000
        assert p.effective_total_amount == 10500000.0
        # Sum of sell: 7,000,000 + 5,500,000 = 12,500,000
        assert p.effective_sell_price == 12500000.0

        current_lot = Lot.query.get(lot_id)
        # Lot total operating cost should only sum root items (which use effective_total_amount) -> 10,500,000
        # There should be NO double-counting with root + children
        assert current_lot.total_operating_cost == 10500000.0

        # Sub-costs have distinct suppliers and plates
        sub1 = p.active_sub_costs[0]
        assert sub1.supplier_name == 'Nhà xe Hùng Cường'
        assert sub1.vehicle_plate == '15C-123.45'
        assert sub1.invoice_classification == 'has_invoice'

        sub2 = p.active_sub_costs[1]
        assert sub2.supplier_name == 'Nhà xe Thành Long'
        assert sub2.vehicle_plate == '29H-567.89'
        assert sub2.invoice_classification == 'no_invoice'

        # Test leaf invoice stats: exactly 2 leaf costs
        stats = current_lot.invoice_stats
        assert stats['has_invoice']['count'] == 1
        assert stats['has_invoice']['total'] == 6000000.0
        assert stats['no_invoice']['count'] == 1
        assert stats['no_invoice']['total'] == 4500000.0

def test_revenue_item_hierarchy(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Test Phân Rã Cước Thu')
        db.session.add(lot)
        db.session.flush()

        # Create parent RevenueItem
        rev_item = RevenueItem(
            lot_id=lot.id,
            service_description='Cước vận tải trọn gói 2 xe',
            buy_price=8000000.0,
            sell_price=10000000.0,
            total_buy_price_excel=8000000.0,
            total_sell_price_excel=10000000.0
        )
        db.session.add(rev_item)
        db.session.commit()

        lot_id = lot.id
        item_id = rev_item.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Add sub-cost to RevenueItem (Xe con 1: 4,000,000 mua vào)
    res = auth_client_manager.post(f'/lots/{lot_id}/items/{item_id}/sub_cost', data={
        'csrf_token': csrf_token,
        'service_description': 'Chi phí xe sang tải 1',
        'supplier': 'Đội xe Tân Phát',
        'vehicle_plate': '98C-001.23',
        'buy_price': '4.000.000',
        'sell_price': '0',
        'invoice_classification': 'has_invoice'
    })
    assert res.status_code == 302

    # Add sub-cost to RevenueItem (Xe con 2: 4,200,000 mua vào)
    res = auth_client_manager.post(f'/lots/{lot_id}/items/{item_id}/sub_cost', data={
        'csrf_token': csrf_token,
        'service_description': 'Chi phí xe sang tải 2',
        'supplier': 'Đội xe Tân Phát',
        'vehicle_plate': '98C-004.56',
        'buy_price': '4.200.000',
        'sell_price': '0',
        'invoice_classification': 'no_invoice'
    })
    assert res.status_code == 302

    with app.app_context():
        item = RevenueItem.query.get(item_id)
        assert item.is_parent is True
        assert len(item.active_sub_costs) == 2
        # Effective buy price auto-sums children: 4,000,000 + 4,200,000 = 8,200,000
        assert item.effective_total_buy_price == 8200000.0

        current_lot = Lot.query.get(lot_id)
        assert current_lot.total_buy_cost == 8200000.0
        # Sub-costs under revenue items should NOT be added into total_operating_cost
        assert current_lot.total_operating_cost == 0.0

def test_cascade_delete_parent(auth_client_manager, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô Test Xóa Cha Con')
        db.session.add(lot)
        db.session.flush()

        parent_cost = OperatingCost(
            lot_id=lot.id,
            cost_type='Vận chuyển',
            description='Khoản mục cha',
            unit_price=5000000.0,
            total_amount=5000000.0
        )
        db.session.add(parent_cost)
        db.session.flush()

        child1 = OperatingCost(
            lot_id=lot.id,
            parent_cost_id=parent_cost.id,
            description='Con 1',
            total_amount=2000000.0
        )
        child2 = OperatingCost(
            lot_id=lot.id,
            parent_cost_id=parent_cost.id,
            description='Con 2',
            total_amount=3000000.0
        )
        db.session.add_all([child1, child2])
        db.session.commit()

        lot_id = lot.id
        parent_id = parent_cost.id
        c1_id = child1.id
        c2_id = child2.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # Delete parent via endpoint
    res = auth_client_manager.post(f'/lots/{lot_id}/costs/{parent_id}/delete', data={'csrf_token': csrf_token})
    assert res.status_code in (200, 302)

    with app.app_context():
        p = OperatingCost.query.get(parent_id)
        c1 = OperatingCost.query.get(c1_id)
        c2 = OperatingCost.query.get(c2_id)
        assert p.is_deleted is True
        assert c1.is_deleted is True
        assert c2.is_deleted is True

        current_lot = Lot.query.get(lot_id)
        assert current_lot.total_operating_cost == 0.0
