import io
import pytest
from app.extensions import db
from app.models import Lot, OperatingCost, CashAdvanceBillMedia

def test_manual_invoice_classification_model(app):
    with app.app_context():
        lot = Lot(lot_label="Test Lot Manual Inv", month=8, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description="Bảo hiểm xe Trung Quốc",
            total_amount=500000,
            invoice_type="HĐ GTGT"
        )
        db.session.add(cost)
        db.session.commit()

        # Ban đầu tự động hoặc fallback
        assert cost.invoice_classification in ('has_invoice', 'no_invoice', 'unpayable_invoice')

        # Nhân viên / Kế toán tự chọn thủ công 'unpayable_invoice'
        cost.invoice_classification = 'unpayable_invoice'
        db.session.commit()

        reloaded = db.session.get(OperatingCost, cost.id)
        assert reloaded.invoice_classification == 'unpayable_invoice'
        assert reloaded.invoice_classification_label == 'HĐ không TT được'

        # Nhân viên / Kế toán tự chọn thủ công 'has_invoice'
        reloaded.invoice_classification = 'has_invoice'
        db.session.commit()

        reloaded2 = db.session.get(OperatingCost, cost.id)
        assert reloaded2.invoice_classification == 'has_invoice'
        assert reloaded2.invoice_classification_label == 'Có HĐ'


def test_endpoint_requires_file_when_has_invoice(app, auth_client_manager):
    with app.app_context():
        lot = Lot(lot_label="Test Lot Require File", month=8, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description="Vé bến bãi",
            total_amount=200000,
            invoice_classification='no_invoice'
        )
        db.session.add(cost)
        db.session.commit()
        cost_id = cost.id
        lot_id = lot.id

    # POST to update invoice with 'has_invoice' but NO file
    resp = auth_client_manager.post(
        f'/lots/{lot_id}/costs/{cost_id}/invoice',
        data={
            'invoice_classification': 'has_invoice',
            'csrf_token': 'test_csrf_token'
        },
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['success'] is False
    assert 'bắt buộc phải tải lên file/ảnh hóa đơn' in data['error']

    with app.app_context():
        cost = db.session.get(OperatingCost, cost_id)
        # Không được đổi sang 'has_invoice'
        assert cost.invoice_classification != 'has_invoice'


def test_endpoint_succeeds_with_file_when_has_invoice(app, auth_client_manager):
    with app.app_context():
        lot = Lot(lot_label="Test Lot Upload File", month=8, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description="Mua phí xe Trung Quốc",
            total_amount=350000,
            invoice_classification='no_invoice'
        )
        db.session.add(cost)
        db.session.commit()
        cost_id = cost.id
        lot_id = lot.id

    # POST to update invoice with 'has_invoice' AND file
    fake_file = (io.BytesIO(b'%PDF-1.4 fake pdf invoice content'), 'hoa_don_vat.pdf')
    resp = auth_client_manager.post(
        f'/lots/{lot_id}/costs/{cost_id}/invoice',
        data={
            'invoice_classification': 'has_invoice',
            'invoice_type': 'HĐ GTGT',
            'invoice_number': '00998877',
            'invoice_symbol': '1C26TAA',
            'invoice_file': fake_file,
            'csrf_token': 'test_csrf_token'
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
        content_type='multipart/form-data'
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['invoice_classification'] == 'has_invoice'
    assert data['has_invoice_file'] is True
    assert data['media_id'] is not None

    with app.app_context():
        cost = db.session.get(OperatingCost, cost_id)
        assert cost.invoice_classification == 'has_invoice'
        assert cost.has_invoice_file is True
        assert cost.latest_invoice_media is not None
        assert cost.latest_invoice_media.filename == 'hoa_don_vat.pdf'
        assert cost.invoice_number == '00998877'


def test_endpoint_no_file_needed_for_no_invoice_and_unpayable(app, auth_client_manager):
    with app.app_context():
        lot = Lot(lot_label="Test Lot Optional File", month=8, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        cost = OperatingCost(
            lot_id=lot.id,
            description="Biên phòng xe Trung Quốc",
            total_amount=150000
        )
        db.session.add(cost)
        db.session.commit()
        cost_id = cost.id
        lot_id = lot.id

    # Set to 'unpayable_invoice' without file
    resp1 = auth_client_manager.post(
        f'/lots/{lot_id}/costs/{cost_id}/invoice',
        data={
            'invoice_classification': 'unpayable_invoice',
            'invoice_type': 'Biên lai',
            'csrf_token': 'test_csrf_token'
        },
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert resp1.status_code == 200
    assert resp1.get_json()['success'] is True

    with app.app_context():
        cost = db.session.get(OperatingCost, cost_id)
        assert cost.invoice_classification == 'unpayable_invoice'

    # Set to 'no_invoice' without file
    resp2 = auth_client_manager.post(
        f'/lots/{lot_id}/costs/{cost_id}/invoice',
        data={
            'invoice_classification': 'no_invoice',
            'csrf_token': 'test_csrf_token'
        },
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert resp2.status_code == 200
    assert resp2.get_json()['success'] is True

    with app.app_context():
        cost = db.session.get(OperatingCost, cost_id)
        assert cost.invoice_classification == 'no_invoice'
