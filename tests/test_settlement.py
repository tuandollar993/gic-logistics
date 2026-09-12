import pytest
from datetime import date
from app.extensions import db
from app.models import CashAdvanceMonthly, CashAdvanceTransaction, MonthlySettlement
from app.services.settlement_service import (
    auto_classify_transactions,
    set_refund_deadlines,
    classify_single_transaction,
    mark_settled,
    mark_submitted,
    request_exclusion,
    approve_exclusion,
    reject_exclusion,
    calculate_settlement_summary,
    close_month,
    reopen_month,
    get_unsettled_transactions,
    get_pending_exclusions,
)
from app.services.reminder_service import ReminderService


@pytest.fixture
def sample_transactions(app):
    with app.app_context():
        # Clean up existing for test month 11/2026
        CashAdvanceTransaction.query.filter_by(month=11, year=2026).delete()
        MonthlySettlement.query.filter_by(month=11, year=2026).delete()
        db.session.commit()

        # 1. Expense with invoice
        tx1 = CashAdvanceTransaction(
            month=11,
            year=2026,
            row_index=1,
            content='Chi tiếp khách có hoá đơn',
            tuan_chi=1000000.0,
            partner_invoice='HD001',
        )
        # 2. Expense without invoice
        tx2 = CashAdvanceTransaction(
            month=11,
            year=2026,
            row_index=2,
            content='Chi mua nước uống tiền mặt',
            tuan_chi=200000.0,
        )
        # 3. Income transaction (should not be treated as expense)
        tx3 = CashAdvanceTransaction(
            month=11,
            year=2026,
            row_index=3,
            content='Cty cấp quỹ',
            tuan_thu_cty=5000000.0,
        )
        # 4. Partner expense with bill link
        tx4 = CashAdvanceTransaction(
            month=11,
            year=2026,
            row_index=4,
            content='Chi trả xe đối tác',
            partner_amount=3000000.0,
            bill_link='https://example.com/bill.jpg',
        )
        db.session.add_all([tx1, tx2, tx3, tx4])
        db.session.commit()
        ids = [tx1.id, tx2.id, tx3.id, tx4.id]
        return ids


def test_auto_classification_and_deadlines(app, sample_transactions):
    with app.app_context():
        count = auto_classify_transactions(11, 2026)
        assert count == 3  # tx1, tx2, tx4 (expenses only)

        dl_count = set_refund_deadlines(11, 2026)
        assert dl_count == 3

        tx1 = db.session.get(CashAdvanceTransaction, sample_transactions[0])
        tx2 = db.session.get(CashAdvanceTransaction, sample_transactions[1])
        tx4 = db.session.get(CashAdvanceTransaction, sample_transactions[3])

        assert tx1.invoice_category == 'has_invoice'
        assert tx2.invoice_category == 'no_invoice'
        assert tx4.invoice_category == 'has_invoice'
        assert tx1.refund_deadline == date(2026, 11, 30)


def test_exclusion_workflow(app, sample_transactions):
    with app.app_context():
        auto_classify_transactions(11, 2026)
        tx2_id = sample_transactions[1]

        # Request exclusion
        tx, err = request_exclusion(tx2_id, note='Tiền nước vỉa hè không có hoá đơn')
        assert err is None
        assert tx.exclusion_status == 'pending_approval'
        assert tx.exclusion_note == 'Tiền nước vỉa hè không có hoá đơn'

        # Check pending exclusions
        pending = get_pending_exclusions()
        assert any(p.id == tx2_id for p in pending)

        # Reject exclusion first to test reject path
        tx, err = reject_exclusion(tx2_id)
        assert err is None
        assert tx.exclusion_status == 'rejected'

        # Request again and approve
        request_exclusion(tx2_id, note='Gửi sếp duyệt lại')
        tx, err = approve_exclusion(tx2_id, approved_by_user_id=1)
        assert err is None
        assert tx.exclusion_status == 'approved'
        assert tx.refund_status == 'excluded'


def test_settlement_calculation_and_closing(app, sample_transactions):
    with app.app_context():
        auto_classify_transactions(11, 2026)
        tx1_id = sample_transactions[0]
        tx2_id = sample_transactions[1]

        # Mark tx1 as settled
        mark_settled(tx1_id)

        # Approve exclusion for tx2 (200,000đ)
        request_exclusion(tx2_id, 'Không HĐ')
        approve_exclusion(tx2_id, 1)

        summary = calculate_settlement_summary(11, 2026)
        # Total expenses = 1,000,000 + 200,000 + 3,000,000 = 4,200,000
        assert summary['total_expenses'] == 4200000.0
        # Excluded = 200,000
        assert summary['total_excluded'] == 200000.0
        # Remit to accounting = 4,200,000 - 200,000 = 4,000,000
        assert summary['total_to_remit'] == 4000000.0
        assert summary['count_settled'] == 1
        assert summary['count_excluded'] == 1

        # Close month
        settlement, err = close_month(11, 2026, closed_by_user_id=1)
        assert err is None
        assert settlement.status == 'closed'
        assert settlement.total_to_remit == 4000000.0

        # Reopen month
        settlement, err = reopen_month(11, 2026)
        assert err is None
        assert settlement.status == 'open'


def test_settlement_routes(auth_client_manager, app, sample_transactions):
    with auth_client_manager.session_transaction() as sess:
        sess['_csrf_token'] = 'test-token'

    tx_id = sample_transactions[0]
    headers = {'X-CSRF-Token': 'test-token'}

    # Auto classify route (JSON mode)
    res = auth_client_manager.post(
        '/advances/settlement/classify/11/2026',
        json={'csrf_token': 'test-token'},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json['success'] is True

    # Settle route (JSON mode)
    res = auth_client_manager.post(
        f'/advances/settlement/settle/{tx_id}',
        json={'csrf_token': 'test-token'},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json['success'] is True

    # Form POST mode (redirects to index)
    res = auth_client_manager.post(
        f'/advances/settlement/submit/{tx_id}',
        data={'csrf_token': 'test-token'},
    )
    assert res.status_code == 302

    # Summary route (GET)
    res = auth_client_manager.get('/advances/settlement/summary/11/2026')
    assert res.status_code == 200
    assert res.json['success'] is True
    assert 'summary' in res.json


def test_reminder_service_advance_refund(app, sample_transactions):
    with app.app_context():
        # Call reminder logic directly
        res = ReminderService.run_advance_refund_reminder()
        assert isinstance(res, dict)
        assert 'reminded' in res


def test_lot_reconciliation_and_export(auth_client_manager, app, sample_transactions):
    from app.models import Lot, OperatingCost
    from app.services.settlement_service import (
        preview_lot_reconciliation,
        apply_lot_reconciliation,
        export_no_invoice_excel
    )

    with app.app_context():
        # Create a sample Lot and OperatingCost matching tx2 (amount 200,000)
        lot = Lot(month=11, year=2026, lot_label='Lô Test 11', company='GIC Test')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description='Chi mua nước uống tiền mặt',
            total_amount=200000.0,
            invoice_type='Không HĐ',
            is_deleted=False
        )
        db.session.add(cost)
        db.session.commit()

        # Preview
        matches = preview_lot_reconciliation(11, 2026)
        assert len(matches) >= 1
        m = [match for match in matches if match['trans_amount'] == 200000.0][0]
        assert m['proposed_category'] == 'no_invoice'

        # Apply
        applied = apply_lot_reconciliation(11, 2026)
        assert applied >= 1

        tx2 = db.session.get(CashAdvanceTransaction, sample_transactions[1])
        assert tx2.invoice_category == 'no_invoice'

        # Test export no-invoice excel
        fpath, fname, count, tot = export_no_invoice_excel(11, 2026)
        assert count >= 1
        assert tot >= 200000.0
        import os
        assert os.path.exists(fpath)

    # Test export route
    res = auth_client_manager.get('/advances/export-no-invoice?month=11&year=2026')
    assert res.status_code == 200
    assert 'spreadsheet' in res.content_type or 'excel' in res.content_type or 'octet-stream' in res.content_type

    # Test preview API
    res = auth_client_manager.get('/advances/reconciliation/preview/11/2026')
    assert res.status_code == 200
    assert res.json['success'] is True

    # Test reset month
    with auth_client_manager.session_transaction() as sess:
        sess['_csrf_token'] = 'test-token'
    res = auth_client_manager.post(
        '/advances/settlement/reset-month/11/2026',
        json={'csrf_token': 'test-token'},
        headers={'X-CSRF-Token': 'test-token'}
    )
    assert res.status_code == 200
    assert res.json['success'] is True

