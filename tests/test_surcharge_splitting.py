import pytest
from app.extensions import db
from app.models import Lot, Customer, RevenueItem
from scripts.normalize_surcharges import run_surcharge_normalization

def test_surcharge_normalization_and_splitting(app):
    with app.app_context():
        # Setup customer and lot
        cust = Customer(name='Test Customer Surcharge')
        db.session.add(cust)
        db.session.commit()

        lot = Lot(
            lot_label='Lô Test Surcharge',
            customer_id=cust.id,
            month=8,
            year=2026,
            source_type='gido'
        )
        db.session.add(lot)
        db.session.commit()

        # Item 1: Freight with surcharges (CSHT = 329,629, Vé xe = 164,814)
        item1 = RevenueItem(
            lot_id=lot.id,
            service_description='Cước vận chuyển hàng hóa',
            vehicle_plate_vn='20E00164',
            buy_price=28000000.0,
            sell_price=32407407.0,
            total_sell_price_excel=32901850.0,
            infrastructure_fee=329629.0,
            ticket_fee=164814.0
        )
        # Item 2: Standalone bốc xếp with loading_fee
        item2 = RevenueItem(
            lot_id=lot.id,
            service_description='Chi phí bốc xếp hàng',
            vehicle_plate_vn='20E00164',
            buy_price=1000000.0,
            sell_price=0.0,
            loading_fee=500000.0
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        # Run normalization
        res = run_surcharge_normalization(commit=True, app=app)
        assert res['parent_updated'] == 1
        assert res['split_items'] == 2
        assert res['bocxep_updated'] == 1

        # Re-fetch items from lot
        items = RevenueItem.query.filter_by(lot_id=lot.id).all()
        assert len(items) == 4

        # Verify parent item
        parent = RevenueItem.query.filter_by(id=item1.id).first()
        assert parent.sell_price == 32407407.0
        assert parent.total_sell_price_excel == 32407407.0
        assert parent.infrastructure_fee == 0.0
        assert parent.ticket_fee == 0.0

        # Verify split surcharges
        csht_item = RevenueItem.query.filter_by(lot_id=lot.id, service_description='Phí Cơ sở hạ tầng').first()
        assert csht_item is not None
        assert csht_item.buy_price == 329629.0
        assert csht_item.sell_price == 329629.0
        assert (csht_item.sell_price - csht_item.buy_price) == 0.0

        ticket_item = RevenueItem.query.filter_by(lot_id=lot.id, service_description='Vé xe').first()
        assert ticket_item is not None
        assert ticket_item.buy_price == 164814.0
        assert ticket_item.sell_price == 164814.0
        assert (ticket_item.sell_price - ticket_item.buy_price) == 0.0

        # Verify bốc xếp normalization
        bx_item = RevenueItem.query.filter_by(id=item2.id).first()
        assert bx_item.buy_price == 500000.0
        assert bx_item.sell_price == 500000.0
        assert (bx_item.sell_price - bx_item.buy_price) == 0.0

        # Second run should skip cleanly (idempotence)
        res2 = run_surcharge_normalization(commit=True, app=app)
        assert res2['split_items'] == 0
        assert res2['parent_updated'] == 0
