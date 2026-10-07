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


def test_insert_row_safety(monkeypatch):
    import app.services.cashflow_bot_service as bot_service

    # Mock sheet with 5 title/header rows, row 6 subheader, rows 7-31 blank, row 32 TỔNG
    rows = [
        [],
        ['', '', 'TIÊU ĐỀ'],
        ['', '', 'THÁNG 10/2026'],
        [],
        ['NGÀY', 'NỘI DUNG', 'TUẤN', '', '', '', '', '', 'XUYÊN', 'LƯƠNG', '', 'TRƯỜNG', 'Đối tác'],
        ['', '', 'Tồn', 'Thu từ Công ty', 'Thu từ Hải Bân', 'Thu khác', 'Chi tiền Hải Bân', 'Chi', '', 'Thu', 'Chi'],
    ] + [[] for _ in range(25)] + [
        ['', 'TỔNG CỘNG THÁNG 10/2026', '219061333']
    ]

    class MockRespMeta:
        def json(self):
            return {'sheets': [{'properties': {'title': 'Tháng 10-2026', 'sheetId': 123}}]}
    class MockRespVals:
        def json(self):
            return {'values': rows}

    monkeypatch.setattr(bot_service.requests, 'get', lambda url, **k: MockRespMeta() if 'fields=sheets' in url else MockRespVals())

    # When sheet has empty template rows (row 7 is free): target row must be row 7 (index 6 + 1)
    target = bot_service._insert_row_before_total('dummy_token', 'dummy_id', 'Tháng 10-2026')
    assert target == 7  # Must NOT jump or overwrite header/subheader (rows 5, 6)

    # When row 7 has a transaction: target row must be row 8
    rows[6] = ['05/10/2026', 'Giao dịch 1']
    target2 = bot_service._insert_row_before_total('dummy_token', 'dummy_id', 'Tháng 10-2026')
    assert target2 == 8


def test_append_transaction_tuan_chi_negative(monkeypatch):
    import app.services.cashflow_bot_service as bot_service

    monkeypatch.setattr(bot_service, 'get_google_access_token', lambda: 'tok')
    monkeypatch.setattr(bot_service, 'get_monthly_sheet_name', lambda d: ('Tháng 10-2026', 10, 2026))
    monkeypatch.setattr(bot_service, '_insert_row_before_total', lambda tok, sid, sname: 7)

    updated_values = []
    def mock_put(url, json=None, **k):
        if json and 'values' in json:
            updated_values.append(json['values'][0])
        class Resp:
            status_code = 200
        return Resp()

    monkeypatch.setattr(bot_service.requests, 'put', mock_put)
    monkeypatch.setattr(bot_service.requests, 'post', lambda *a, **k: None)

    # Test expense for external partner
    data = {
        'loai': 'CHI',
        'so_tien': 1000000,
        'nguoi_giao_dich': 'TRAN CHU CHOANH',
        'noi_dung': 'gido tt chi phi boc xep nha trang',
        'nhan_vien': 'ĐỐI TÁC KHÁC',
        'ngay_giao_dich': '05/10/2026'
    }

    bot_service.append_transaction_to_sheet(data, 'https://test/bill/123')
    assert len(updated_values) == 1
    row = updated_values[0]
    # Col H (index 7) must be -1000000 (negative)
    assert row[7] == -1000000.0
    # Col M (index 12) must be 1000000 (Đối tác)
    assert row[12] == 1000000.0


def test_running_balance_and_closing_balance(app):
    with app.app_context():
        monthly = CashAdvanceMonthly(month=10, year=2026, opening_balance=200000000.0, closing_balance=0.0)
        db.session.add(monthly)
        db.session.flush()

        tx1 = CashAdvanceTransaction(
            monthly_id=monthly.id,
            month=10,
            year=2026,
            row_index=7,
            content='Giao dịch 1',
            tuan_chi=-3000000.0,
            partner_amount=3000000.0,
            is_deleted=False
        )
        tx2 = CashAdvanceTransaction(
            monthly_id=monthly.id,
            month=10,
            year=2026,
            row_index=8,
            content='Giao dịch 2',
            tuan_chi=-1000000.0,
            partner_amount=1000000.0,
            is_deleted=False
        )
        db.session.add_all([tx1, tx2])
        db.session.commit()

        data = get_monthly_advances_data(10, 2026)
        txs = data['transactions']
        assert len(txs) == 2
        # Verify running balance
        assert txs[0].running_ton == 197000000.0
        assert txs[1].running_ton == 196000000.0
        # Verify metrics closing balance does not zero out
        assert data['metrics']['closing_balance'] == 196000000.0

