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

def test_cross_border_transit_feeder_and_vn_delivery_vehicles(app):
    """
    Kiem tra nghiep vu van tai xuyen bien gioi:
    Xe Trung Quoc chuyen hang tu TQ -> VN sang xe tai cua khau sang 3 xe Viet Nam:
    - 50E89476 (Cont 1)
    - 77H03770 (Cont 2)
    - 29H81645 (8T)
    Xe Trung Quoc (R29173, BQ3500) la xe trung chuyen, khong tinh thanh xe van hanh rieng.
    Tong so xe cua lo phai la chinh xac 3 xe VN.
    """
    with app.app_context():
        c = Customer(code='CUST_KR_TEST', name='Keep Rise Test')
        db.session.add(c)
        db.session.commit()

        lot = Lot(lot_label='Lô 4', customer_id=c.id, month=8, year=2026, source_type='sales')
        db.session.add(lot)
        db.session.flush()

        r1 = RevenueItem(
            lot_id=lot.id,
            service_description='Phí cửa khẩu',
            weight_class='Cont (1)',
            buy_price=793000,
            sell_price=1250000
        )
        r2 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước vận chuyển Lạng Sơn - TP. Hồ Chí Minh',
            weight_class='Cont (1)',
            vehicle_plate_vn='50E89476',
            vehicle_plate_cn='R29173',
            buy_price=31000000,
            sell_price=50925926
        )
        r3 = RevenueItem(
            lot_id=lot.id,
            service_description='Phí cứa khẩu',
            weight_class='Cont (2)',
            buy_price=793000,
            sell_price=1250000
        )
        r4 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước vận chuyển Lạng Sơn - TP. Hồ Chí Minh',
            weight_class='Cont (2)',
            vehicle_plate_vn='77H03770',
            vehicle_plate_cn='R29173',
            buy_price=34000000,
            sell_price=50925926
        )
        r5 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước vận chuyển Lạng Sơn -Hà Nội...',
            weight_class='8T',
            vehicle_plate_vn='29H81645',
            vehicle_plate_cn='BQ3500\nBLH994',
            buy_price=30300000,
            sell_price=0
        )
        r6 = RevenueItem(
            lot_id=lot.id,
            service_description='DVTK HQ',
            buy_price=8000000,
            sell_price=8540000
        )
        db.session.add_all([r1, r2, r3, r4, r5, r6])
        db.session.commit()

        # 1. Total vehicle count must be 3
        assert lot.total_vehicle_count == 3

        # 2. Distinct vehicles list must be exactly the 3 VN vehicles
        vehicles = lot.distinct_vehicles
        assert len(vehicles) == 3
        assert vehicles[0]['plate'] == '50E89476'
        assert 'Cont 1' in vehicles[0]['label']
        assert vehicles[1]['plate'] == '77H03770'
        assert 'Cont 2' in vehicles[1]['label']
        assert vehicles[2]['plate'] == '29H81645'
        assert '8T' in vehicles[2]['label']

        # 3. Breakdown check
        breakdown = lot.vehicles_breakdown
        # 3 vehicles + 1 general cost group
        assert len(breakdown) == 4
        # Check Xe 1
        assert breakdown[0]['plate'] == '50E89476'
        assert breakdown[0]['transit_cn'] == 'R29173'
        assert len(breakdown[0]['revenue_items']) == 2
        # Check Xe 2
        assert breakdown[1]['plate'] == '77H03770'
        assert breakdown[1]['transit_cn'] == 'R29173'
        assert len(breakdown[1]['revenue_items']) == 2
        # Check Xe 3
        assert breakdown[2]['plate'] == '29H81645'
        assert 'BQ3500' in breakdown[2]['transit_cn']
        assert len(breakdown[2]['revenue_items']) == 1
        # Check General
        assert breakdown[3]['plate'] == 'general'
        assert len(breakdown[3]['revenue_items']) == 1

def test_parse_sales_report_multi_vehicle_lot_breakdown(app):
    """Kiểm tra logic bóc tách 3 xe Lô 4 Keep Rise T08 chuẩn từng xe và từng mục"""
    with app.app_context():
        lot = Lot.query.filter(Lot.month == 8, Lot.year == 2026, Lot.lot_label.ilike('%lô 4%')).first()
        if not lot:
            pytest.skip("Lô 4 T08 not found")

        assert lot.total_vehicle_count == 3
        breakdown = lot.vehicles_breakdown
        assert len(breakdown) == 4

        # Xe 1 (50E89476): 5 mục
        xe1 = next(b for b in breakdown if b['plate'] == '50E89476')
        assert len(xe1['revenue_items']) == 5
        xe1_descs = [ri.service_description for ri in xe1['revenue_items']]
        assert any('Cước vận chuyển' in d for d in xe1_descs)
        assert any('bốc xếp' in d for d in xe1_descs)
        assert any('Quatest' in d for d in xe1_descs)
        assert any('cửa khẩu' in d or 'cứa khẩu' in d for d in xe1_descs)
        assert any('DVTK HQ' in d for d in xe1_descs)

        # Xe 2 (77H03770): 3 mục
        xe2 = next(b for b in breakdown if b['plate'] == '77H03770')
        assert len(xe2['revenue_items']) == 3
        xe2_descs = [ri.service_description for ri in xe2['revenue_items']]
        assert any('Cước vận chuyển' in d for d in xe2_descs)
        assert any('bốc xếp' in d for d in xe2_descs)
        assert any('Quatest' in d for d in xe2_descs)

        # Xe 3 (29H81645): cước vận chuyển
        xe3 = next(b for b in breakdown if b['plate'] == '29H81645')
        assert len(xe3['revenue_items']) >= 1
        assert any('Cước vận chuyển' in ri.service_description for ri in xe3['revenue_items'])

        # Chi phí chung: Phí cửa khẩu & DVTK HQ
        general = next(b for b in breakdown if b['plate'] == 'general')
        gen_descs = [ri.service_description for ri in general['revenue_items']]
        assert any('cửa khẩu' in d for d in gen_descs)
        assert any('DVTK HQ' in d for d in gen_descs)

