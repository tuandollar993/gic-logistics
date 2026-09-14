import pytest
from app.extensions import db
from app.models import Lot, Customer, User, RevenueItem, OperatingCost
from app.services.calculator import CalculatorService

def test_lot_deferred_revenue_properties(app):
    with app.app_context():
        lot = Lot(
            lot_label='LÔ-T08-01',
            month=8,
            year=2026,
            source_type='gido'
        )
        db.session.add(lot)
        db.session.commit()

        # Regular revenue item (same month as lot)
        ri_current = RevenueItem(
            lot_id=lot.id,
            buy_price=5_000_000,
            sell_price=10_000_000,
            total_buy_price_excel=5_000_000,
            total_sell_price_excel=10_000_000
        )
        # Deferred revenue item (issued in month 9)
        ri_deferred = RevenueItem(
            lot_id=lot.id,
            buy_price=0,
            sell_price=15_000_000,
            total_buy_price_excel=0,
            total_sell_price_excel=15_000_000,
            revenue_month=9,
            revenue_year=2026,
            revenue_invoice_number='HD-00123'
        )
        # Operating cost with sell price deferred to month 9
        cost_deferred = OperatingCost(
            lot_id=lot.id,
            cost_type='Phí thông quan',
            description='Phí tờ khai HQ',
            total_amount=2_000_000,
            unit_price=2_000_000,
            sell_price=4_000_000,
            revenue_month=9,
            revenue_year=2026
        )

        db.session.add_all([ri_current, ri_deferred, cost_deferred])
        db.session.commit()

        # Check model properties
        assert ri_current.is_deferred_revenue is False
        assert ri_current.effective_revenue_month == 8
        assert ri_current.effective_revenue_year == 2026

        assert ri_deferred.is_deferred_revenue is True
        assert ri_deferred.effective_revenue_month == 9
        assert ri_deferred.effective_revenue_year == 2026

        assert cost_deferred.is_deferred_revenue is True
        assert cost_deferred.effective_revenue_month == 9
        assert cost_deferred.effective_revenue_year == 2026

        # Lot total sell revenue (all items)
        assert lot.total_sell_revenue == 29_000_000
        assert lot.total_buy_cost == 5_000_000
        assert lot.total_operating_cost == 2_000_000
        assert lot.net_profit == 22_000_000
        assert lot.has_deferred_revenue is True

        # Recognized revenue for Month 8
        assert lot.get_recognized_revenue(8, 2026) == 10_000_000
        # Recognized revenue for Month 9
        assert lot.get_recognized_revenue(9, 2026) == 19_000_000


def test_calculator_cross_month_kpi_and_trend(app):
    with app.app_context():
        # Lot in Month 8
        lot_aug = Lot(
            lot_label='LÔ-T08-01',
            month=8,
            year=2026,
            source_type='gido'
        )
        # Lot in Month 9
        lot_sep = Lot(
            lot_label='LÔ-T09-01',
            month=9,
            year=2026,
            source_type='gido'
        )
        db.session.add_all([lot_aug, lot_sep])
        db.session.commit()

        # Month 8 Lot: Cost 7M (5M buy, 2M ops), Sell 29M (10M recognized in T8, 19M deferred to T9)
        ri_aug_curr = RevenueItem(
            lot_id=lot_aug.id,
            buy_price=5_000_000,
            sell_price=10_000_000,
            total_buy_price_excel=5_000_000,
            total_sell_price_excel=10_000_000
        )
        ri_aug_def = RevenueItem(
            lot_id=lot_aug.id,
            buy_price=0,
            sell_price=15_000_000,
            total_buy_price_excel=0,
            total_sell_price_excel=15_000_000,
            revenue_month=9,
            revenue_year=2026
        )
        cost_aug_def = OperatingCost(
            lot_id=lot_aug.id,
            cost_type='Cửa khẩu',
            description='Phí sang tải',
            total_amount=2_000_000,
            unit_price=2_000_000,
            sell_price=4_000_000,
            revenue_month=9,
            revenue_year=2026
        )

        # Month 9 Lot: Cost 4M (3M buy, 1M ops), Sell 20M recognized in T9
        ri_sep_curr = RevenueItem(
            lot_id=lot_sep.id,
            buy_price=3_000_000,
            sell_price=20_000_000,
            total_buy_price_excel=3_000_000,
            total_sell_price_excel=20_000_000
        )
        cost_sep_curr = OperatingCost(
            lot_id=lot_sep.id,
            cost_type='Vận chuyển',
            description='Cước đường bộ',
            total_amount=1_000_000,
            unit_price=1_000_000,
            sell_price=0
        )

        db.session.add_all([ri_aug_curr, ri_aug_def, cost_aug_def, ri_sep_curr, cost_sep_curr])
        db.session.commit()

        # Check Month 8 KPI
        kpi_aug = CalculatorService.get_monthly_kpi(8, 2026)
        assert kpi_aug['revenue'] == 10_000_000  # Recognized in Month 8
        assert kpi_aug['operational_revenue'] == 29_000_000  # Total shipment revenue
        assert kpi_aug['deferred_out_revenue'] == 19_000_000
        assert kpi_aug['deferred_in_revenue'] == 0
        assert kpi_aug['buy_cost'] == 5_000_000
        assert kpi_aug['operating_cost'] == 2_000_000
        assert kpi_aug['net_profit'] == 10_000_000 - 7_000_000  # 3M

        # Check Month 9 KPI
        kpi_sep = CalculatorService.get_monthly_kpi(9, 2026)
        assert kpi_sep['revenue'] == 20_000_000 + 19_000_000  # 39M (includes 19M from August lot!)
        assert kpi_sep['operational_revenue'] == 20_000_000
        assert kpi_sep['deferred_in_revenue'] == 19_000_000
        assert kpi_sep['deferred_out_revenue'] == 0
        assert kpi_sep['buy_cost'] == 3_000_000
        assert kpi_sep['operating_cost'] == 1_000_000
        assert kpi_sep['net_profit'] == 39_000_000 - 4_000_000  # 35M

        # Check Year Trend
        trend = CalculatorService.get_year_trend(2026)
        m8_data = next(d for d in trend if d['month_num'] == 8)
        m9_data = next(d for d in trend if d['month_num'] == 9)
        assert m8_data['revenue'] == 10_000_000
        assert m9_data['revenue'] == 39_000_000


def test_edit_revenue_period_route(app, auth_client_manager):
    with app.app_context():
        lot = Lot(
            lot_label='LÔ-TEST-EDIT',
            month=8,
            year=2026,
            source_type='gido'
        )
        db.session.add(lot)
        db.session.commit()

        ri = RevenueItem(
            lot_id=lot.id,
            buy_price=1_000_000,
            sell_price=5_000_000,
            service_description='Vận chuyển hàng'
        )
        cost = OperatingCost(
            lot_id=lot.id,
            description='Phí nâng hạ',
            total_amount=500_000,
            sell_price=1_000_000
        )
        db.session.add_all([ri, cost])
        db.session.commit()

        lot_id = lot.id
        ri_id = ri.id
        cost_id = cost.id

    with auth_client_manager.session_transaction() as sess:
        csrf_token = sess.get('_csrf_token', 'test_csrf')

    # 1. Edit RevenueItem to next month
    resp = auth_client_manager.post(f'/lots/{lot_id}/items/{ri_id}/edit', data={
        'csrf_token': csrf_token,
        'service_description': 'Vận chuyển hàng T8 xuất HĐ T9',
        'buy_price': '1.000.000',
        'sell_price': '5.000.000',
        'revenue_period_option': 'next',
        'revenue_invoice_number': 'HD-777'
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        updated_ri = db.session.get(RevenueItem, ri_id)
        assert updated_ri.revenue_month == 9
        assert updated_ri.revenue_year == 2026
        assert updated_ri.revenue_invoice_number == 'HD-777'
        assert updated_ri.is_deferred_revenue is True

    # 2. Edit OperatingCost to custom month
    resp2 = auth_client_manager.post(f'/lots/{lot_id}/costs/{cost_id}/edit', data={
        'csrf_token': csrf_token,
        'service_description': 'Phí nâng hạ T8 xuất HĐ T10',
        'buy_price': '500.000',
        'sell_price': '1.000.000',
        'revenue_period_option': 'custom',
        'revenue_month': '10',
        'revenue_year': '2026'
    }, follow_redirects=True)
    assert resp2.status_code == 200

    with app.app_context():
        updated_cost = db.session.get(OperatingCost, cost_id)
        assert updated_cost.revenue_month == 10
        assert updated_cost.revenue_year == 2026
        assert updated_cost.is_deferred_revenue is True
