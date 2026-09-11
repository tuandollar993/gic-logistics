from datetime import date

from app.extensions import db
from app.models import Lot, OperatingCost, RevenueItem
from app.services.calculator import CalculatorService


def test_soft_deleted_cost_is_excluded_from_lot_and_kpi(app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='LÔ KPI')
        db.session.add(lot)
        db.session.flush()
        visible = OperatingCost(lot_id=lot.id, description='visible', total_amount=100)
        deleted = OperatingCost(
            lot_id=lot.id, description='deleted', total_amount=900,
            sell_price=1200, is_deleted=True
        )
        db.session.add_all([visible, deleted])
        db.session.commit()

        # Expire the relationship so this also covers a fresh query/loading path.
        db.session.expire_all()
        loaded = db.session.get(Lot, lot.id)
        assert loaded.total_operating_cost == 100
        assert loaded.total_sell_revenue == 0
        assert CalculatorService.get_monthly_kpi(8, 2026)['operating_cost'] == 100
        assert db.session.get(OperatingCost, deleted.id).is_deleted is True


def test_complete_lot_requires_document_date(auth_client_staff, staff_user, app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='LÔ COMPLETE', assigned_to=staff_user)
        db.session.add(lot)
        db.session.flush()
        db.session.add(OperatingCost(
            lot_id=lot.id, description='Cost', total_amount=10,
            supplier_name='Supplier', invoice_type='Phiếu thu'
        ))
        db.session.commit()
        lot_id = lot.id

    with auth_client_staff.session_transaction() as sess:
        csrf_token = sess['_csrf_token']
    res = auth_client_staff.post(
        f'/costs/complete/{lot_id}', data={'csrf_token': csrf_token}, follow_redirects=True
    )
    assert res.status_code == 200
    assert 'Ngày chứng từ' in res.get_data(as_text=True)


def test_soft_deleted_revenue_item_is_excluded_from_lot_and_kpi(app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='LÔ REVENUE')
        db.session.add(lot)
        db.session.flush()
        visible = RevenueItem(lot_id=lot.id, total_buy_price_excel=100, total_sell_price_excel=200)
        deleted = RevenueItem(
            lot_id=lot.id, total_buy_price_excel=900, total_sell_price_excel=1200, is_deleted=True
        )
        db.session.add_all([visible, deleted])
        db.session.commit()
        deleted_id = deleted.id
        db.session.expire_all()

        loaded = db.session.get(Lot, lot.id)
        assert loaded.total_buy_cost == 100
        assert loaded.total_sell_revenue == 200
        assert len(loaded.active_revenue_items) == 1
        assert CalculatorService.get_monthly_kpi(8, 2026)['revenue'] == 200
        assert db.session.get(RevenueItem, deleted_id).is_deleted is True
