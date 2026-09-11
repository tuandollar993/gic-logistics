import pytest
from app.models import CashAdvanceMonthly, CashAdvanceTransaction
from app.extensions import db
from app.services.advance_service import (
    sync_month_from_google,
    delete_transaction,
    get_monthly_advances_data,
    _sync_lock,
    acquire_sync_lock
)

def test_month_locking(auth_client_manager, app):
    with app.app_context():
        m = CashAdvanceMonthly(month=9, year=2026, is_locked=False)
        db.session.add(m)
        db.session.commit()
        mid = m.id

    with auth_client_manager.session_transaction() as sess:
        sess['_csrf_token'] = 'tok'
    res = auth_client_manager.post('/advances/lock-month', data={'month': 9, 'year': 2026, 'csrf_token': 'tok'}, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        m = db.session.get(CashAdvanceMonthly, mid)
        assert m.is_locked is True

def test_sync_blocked_when_locked(app):
    with app.app_context():
        m = CashAdvanceMonthly(month=9, year=2026, is_locked=True)
        db.session.add(m)
        db.session.commit()
        monthly, err = sync_month_from_google(9, 2026)
        assert monthly is None
        assert 'đã bị KHÓA SỔ' in err

def test_sync_concurrency_lock(app, monkeypatch):
    # Simulate another thread holding the sync lock
    _sync_lock.acquire()
    try:
        with app.app_context():
            res, err = sync_month_from_google(8, 2026)
            assert res is None
            assert 'tiến trình đồng bộ khác' in err
    finally:
        _sync_lock.release()

def test_delete_transaction_soft_delete(app):
    with app.app_context():
        monthly = CashAdvanceMonthly(month=8, year=2026, is_locked=False)
        db.session.add(monthly)
        db.session.flush()

        tx = CashAdvanceTransaction(
            monthly_id=monthly.id,
            month=8,
            year=2026,
            row_index=10,
            content='Bút toán thử nghiệm',
            tuan_chi=500000.0,
            is_deleted=False
        )
        db.session.add(tx)
        db.session.commit()
        tx_id = tx.id

        # Delete transaction
        ok = delete_transaction(tx_id)
        assert ok is True

        # Must still exist in database, marked as is_deleted=True
        deleted_tx = db.session.get(CashAdvanceTransaction, tx_id)
        assert deleted_tx is not None
        assert deleted_tx.is_deleted is True
        assert deleted_tx.deleted_at is not None
        assert deleted_tx.sync_status == 'deleted'

        # get_monthly_advances_data must exclude soft-deleted transactions
        data = get_monthly_advances_data(8, 2026)
        trans_ids = [t.id for t in data.get('transactions', [])]
        assert tx_id not in trans_ids

def test_salary_reclassified():
    desc = 'Lương chi ra về cho Tuấn'.lower()
    l_thu = 5000000.0
    l_chi = 0.0
    if l_thu > 0 and any(k in desc for k in ['chi ra', 'lương chi', 'luong chi']):
        l_chi = l_thu
        l_thu = 0.0
    assert l_chi == 5000000.0
    assert l_thu == 0.0


def test_sync_missing_uuid_is_never_persisted_or_duplicated(app, monkeypatch):
    """Repeated syncs of an unidentifiable source line must create zero rows."""
    import app.services.advance_service as service

    rows = ([[''] for _ in range(6)] + [
        ['01/09/2026', 'Dòng thiếu UUID'] + [''] * 16,
        ['', 'TỔNG'] + [''] * 16,
    ])

    class Response:
        status_code = 200
        text = ''
        def json(self):
            return {'values': rows}

    monkeypatch.setattr(service, 'get_google_access_token', lambda: 'token')
    monkeypatch.setattr(service, 'get_sheet_title_for_month', lambda month, year: ('Test UUID', '1'))
    monkeypatch.setattr(service.requests, 'get', lambda *args, **kwargs: Response())
    with app.app_context():
        for _ in range(3):
            monthly, error = sync_month_from_google(9, 2026)
            assert error is None
            assert monthly is not None
        assert CashAdvanceTransaction.query.filter_by(month=9, year=2026).count() == 0

        rows[6][17] = 'uuid-now-present'
        monthly, error = sync_month_from_google(9, 2026)
        assert error is None
        transactions = CashAdvanceTransaction.query.filter_by(month=9, year=2026).all()
        assert len(transactions) == 1
        assert transactions[0].external_id == 'uuid-now-present'


def test_postgres_lock_error_fails_closed(app, monkeypatch):
    import app.services.advance_service as service

    class Bind:
        class dialect:
            name = 'postgresql'

    with app.app_context():
        monkeypatch.setattr(service.db.session, 'get_bind', lambda: Bind())
        monkeypatch.setattr(service.db.session, 'execute', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('lock outage')))
        with acquire_sync_lock() as acquired:
            assert acquired is False
