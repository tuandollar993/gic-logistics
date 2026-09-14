import pytest
from datetime import datetime, timezone, date
from app.extensions import db
from app.models import Lot, Customer, OperatingCost, RevenueItem
from app.services.cpvh_matcher import CPVHMatcher
from app.services.calculator import CalculatorService
from app.constants import STANDARD_OPERATING_COST_ITEMS

def test_vehicle_tracking_and_grouping(app):
    with app.app_context():
        cust = Customer(code='CUST_VEHICLE', name='Cong Ty Xe')
        db.session.add(cust)
        db.session.commit()

        lot = Lot(
            lot_label='LOT-V-01',
            customer_id=cust.id,
            month=8,
            year=2026,
            source_type='sales'
        )
        db.session.add(lot)
        db.session.flush()

        # Add revenue items with vehicle plates
        r1 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước xe 1',
            vehicle_plate_vn='20E-00164',
            sell_price=5000000
        )
        r2 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước xe 2',
            vehicle_plate_cn='FB2019',
            sell_price=6000000
        )
        db.session.add_all([r1, r2])

        # Add operating costs: one for 20E-00164, one for a 3rd vehicle R29173, one general
        c1 = OperatingCost(
            lot_id=lot.id,
            cost_type='Phí cửa khẩu',
            description='Phí kiểm hóa xe 1',
            vehicle_plate='20E-00164',
            total_amount=500000
        )
        c2 = OperatingCost(
            lot_id=lot.id,
            cost_type='Phí cửa khẩu',
            description='Phí kiểm hóa xe 3',
            vehicle_plate='R29173',
            total_amount=600000
        )
        c3 = OperatingCost(
            lot_id=lot.id,
            cost_type='Phí thông quan',
            description='Truyền tờ khai chung',
            vehicle_plate='',
            total_amount=200000
        )
        db.session.add_all([c1, c2, c3])
        db.session.commit()

        # Check distinct vehicles
        vehicles = lot.distinct_vehicles
        plates = [v['plate'] for v in vehicles]
        assert '20E-00164' in plates
        assert 'FB2019' in plates
        assert 'R29173' in plates
        assert lot.total_vehicle_count == 3

        # Check costs grouped by vehicle
        grouped = lot.costs_by_vehicle
        assert '20E-00164' in grouped
        assert len(grouped['20E-00164']) == 1
        assert 'R29173' in grouped
        assert len(grouped['R29173']) == 1
        assert 'general' in grouped
        assert len(grouped['general']) == 1

def test_create_lot_with_template_costs(auth_client_manager, app):
    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf_token')

    resp = auth_client_manager.post('/lots/new', data={
        'csrf_token': csrf_token,
        'customer_name': 'Khach Mau Test',
        'lot_label': 'LOT-TMPL-01',
        'month': 8,
        'year': 2026,
        'init_template_costs': 'on'
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        lot = Lot.query.filter_by(lot_label='LOT-TMPL-01').first()
        assert lot is not None
        assert lot.is_sales_lot is True
        # Check standard 16 template items were auto-generated
        active_costs = lot.active_operating_costs
        assert len(active_costs) == len(STANDARD_OPERATING_COST_ITEMS)
        assert len(active_costs) == 16
        descriptions = [c.description for c in active_costs]
        assert 'Mua phí xe Trung Quốc' in descriptions
        assert 'Phí Biên Phòng' in descriptions
        assert 'Phí cơ giới sang hàng (pallet kéo tay)' in descriptions

def test_init_template_costs_endpoint(auth_client_manager, app):
    with app.app_context():
        cust = Customer(code='CUST_EMPTY', name='Khach Rong')
        db.session.add(cust)
        lot = Lot(lot_label='LOT-EMPTY-01', customer_id=cust.id, month=8, year=2026, source_type='sales')
        db.session.add(lot)
        db.session.commit()
        lot_id = lot.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf_token')

    # Call the init-template-costs endpoint
    resp = auth_client_manager.post(
        f'/lots/{lot_id}/init-template-costs',
        data={'csrf_token': csrf_token},
        headers={'X-CSRFToken': csrf_token},
        follow_redirects=True
    )
    assert resp.status_code == 200

    with app.app_context():
        lot = Lot.query.get(lot_id)
        assert len(lot.active_operating_costs) == 16

    # Call again, should not duplicate
    resp2 = auth_client_manager.post(
        f'/lots/{lot_id}/init-template-costs',
        data={'csrf_token': csrf_token},
        headers={'X-CSRFToken': csrf_token},
        follow_redirects=True
    )
    assert resp2.status_code == 200
    with app.app_context():
        lot = Lot.query.get(lot_id)
        assert len(lot.active_operating_costs) == 16

def test_quick_x_delete_ajax(auth_client_manager, app):
    with app.app_context():
        cust = Customer(code='CUST_DEL', name='Khach Xoa')
        db.session.add(cust)
        lot = Lot(lot_label='LOT-DEL-01', customer_id=cust.id, month=8, year=2026, source_type='sales')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            cost_type='Phí cửa khẩu',
            description='Phí không phát sinh',
            total_amount=100000
        )
        db.session.add(cost)
        db.session.commit()
        lot_id = lot.id
        cost_id = cost.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf_token')

    # Test AJAX deletion on /lots/<lot_id>/costs/<cost_id>/delete
    resp = auth_client_manager.post(
        f'/lots/{lot_id}/costs/{cost_id}/delete',
        data={'csrf_token': csrf_token},
        headers={
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrf_token
        }
    )
    assert resp.status_code == 200
    json_data = resp.get_json()
    assert json_data['success'] is True

    with app.app_context():
        c = db.session.get(OperatingCost, cost_id)
        assert c.is_deleted is True

def test_cross_month_cpvh_suggestions(app):
    with app.app_context():
        c1 = Customer(code='CUST_AA', name='Cong Ty TNHH Alpha Logistics')
        c2 = Customer(code='CUST_BB', name='Cong Ty Beta')
        db.session.add_all([c1, c2])
        db.session.commit()

        # Sales lot in Month 7 with declaration 10600001234
        lot_m7 = Lot(
            lot_label='LOT-JUL-01',
            customs_declaration='10600001234',
            customer_id=c1.id,
            month=7,
            year=2026,
            source_type='sales'
        )
        # Sales lot in Month 8 with declaration 99999999999
        lot_m8 = Lot(
            lot_label='LOT-AUG-01',
            customs_declaration='99999999999',
            customer_id=c2.id,
            month=8,
            year=2026,
            source_type='sales'
        )
        # Unresolved group in Month 8 having declaration 10600001234
        unresolved = Lot(
            lot_label='CPVH-AUG-01',
            customs_declaration='10600001234',
            customer_id=c1.id,
            month=8,
            year=2026,
            source_type='cpvh'
        )
        db.session.add_all([lot_m7, lot_m8, unresolved])
        db.session.commit()

        all_sales_lots = [lot_m7, lot_m8]
        suggestions = CPVHMatcher.suggest_candidates(unresolved, all_sales_lots)
        assert len(suggestions) > 0
        best_match = suggestions[0]
        # Should strongly suggest lot_m7 from Month 7 due to identical customs declaration!
        assert best_match['lot_id'] == lot_m7.id
        assert '10600001234' in best_match['reason']
        assert best_match['score'] >= 0.8

def test_monthly_kpi_vehicle_count(app):
    with app.app_context():
        c = Customer(code='CUST_KPI_VEH', name='Khach KPI Xe')
        db.session.add(c)
        db.session.commit()

        lot1 = Lot(lot_label='KPI-L-01', customer_id=c.id, month=9, year=2026, source_type='sales')
        lot2 = Lot(lot_label='KPI-L-02', customer_id=c.id, month=9, year=2026, source_type='sales')
        db.session.add_all([lot1, lot2])
        db.session.flush()

        # Lot 1 has 2 vehicles
        r1 = RevenueItem(lot_id=lot1.id, vehicle_plate_vn='29C-11111', sell_price=1000000)
        r2 = RevenueItem(lot_id=lot1.id, vehicle_plate_vn='29C-22222', sell_price=1000000)
        # Lot 2 has 1 vehicle
        r3 = RevenueItem(lot_id=lot2.id, vehicle_plate_vn='29C-33333', sell_price=1000000)
        db.session.add_all([r1, r2, r3])
        db.session.commit()

        kpi = CalculatorService.get_monthly_kpi(9, 2026)
        assert kpi['lot_count'] == 2
        assert kpi['vehicle_count'] == 3
