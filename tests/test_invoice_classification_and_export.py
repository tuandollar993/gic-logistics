import pytest
from app.extensions import db
from app.models import Lot, OperatingCost, RevenueItem, Customer
from app.services.excel_exporter import ExcelExporterService

def test_invoice_classification(app):
    with app.app_context():
        lot = Lot(lot_label="Test Lot Classification", month=7, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        c1 = OperatingCost(lot_id=lot.id, description="Cước vận chuyển", total_amount=1000000,
                           invoice_type="Hóa đơn GTGT", invoice_number="0012345")
        c2 = OperatingCost(lot_id=lot.id, description="Bốc xếp Lạng Sơn", total_amount=500000,
                           invoice_type="Không HĐ", invoice_number="")
        c3 = OperatingCost(lot_id=lot.id, description="Phí lưu ca", total_amount=300000,
                           invoice_type="Phiếu chi", invoice_number="PC001")
        c4 = OperatingCost(lot_id=lot.id, description="Vé xe bến bãi", total_amount=50000,
                           invoice_type="Vé xe", invoice_number="VX123")
        c5 = OperatingCost(lot_id=lot.id, description="Hóa đơn chưa số", total_amount=200000,
                           invoice_type="Hóa đơn GTGT", invoice_number="")

        db.session.add_all([c1, c2, c3, c4, c5])
        db.session.commit()

        assert c1.invoice_classification == 'has_invoice'
        assert c1.invoice_classification_label == 'Có HĐ'

        assert c2.invoice_classification == 'no_invoice'
        assert c2.invoice_classification_label == 'Không HĐ'

        assert c3.invoice_classification == 'unpayable_invoice'
        assert c3.invoice_classification_label == 'HĐ không TT được'

        assert c4.invoice_classification == 'unpayable_invoice'
        assert c5.invoice_classification == 'no_invoice'

        stats = lot.invoice_stats
        assert stats['has_invoice']['count'] == 1
        assert stats['has_invoice']['total'] == 1000000

        assert stats['no_invoice']['count'] == 2
        assert stats['no_invoice']['total'] == 700000

        assert stats['unpayable_invoice']['count'] == 2
        assert stats['unpayable_invoice']['total'] == 350000

        assert stats['problematic']['count'] == 4
        assert stats['problematic']['total'] == 1050000

def test_export_problematic_costs_excel(app):
    with app.app_context():
        lot = Lot(lot_label="Test Export Lot", month=7, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        c1 = OperatingCost(lot_id=lot.id, description="Chi phí sang tải", total_amount=800000,
                           invoice_type="Không HĐ")
        c2 = OperatingCost(lot_id=lot.id, description="Phiếu chi bốc xếp", total_amount=400000,
                           invoice_type="Phiếu chi", invoice_number="PC999")
        c3 = OperatingCost(lot_id=lot.id, description="Cước chính hãng", total_amount=5000000,
                           invoice_type="Hóa đơn GTGT", invoice_number="123456")

        db.session.add_all([c1, c2, c3])
        db.session.commit()

        buf = ExcelExporterService.export_problematic_costs(lot_id=lot.id)
        assert buf is not None
        assert len(buf.getvalue()) > 1000

        buf_monthly = ExcelExporterService.export_problematic_costs(month=7, year=2026)
        assert buf_monthly is not None
        assert len(buf_monthly.getvalue()) > 1000

def test_distinct_vehicles_plate_normalization(app):
    with app.app_context():
        lot = Lot(lot_label="Test Normalize Plates", month=7, year=2026, source_type='gido')
        db.session.add(lot)
        db.session.flush()

        r1 = RevenueItem(lot_id=lot.id, vehicle_plate_vn="20E00164", weight_class="8T",
                         service_description="Chuyến 1")
        r2 = RevenueItem(lot_id=lot.id, vehicle_plate_vn="98H07613", weight_class="3,5T",
                         service_description="Chuyến 2 3,5T")
        db_session = db.session
        db_session.add_all([r1, r2])

        c1 = OperatingCost(lot_id=lot.id, vehicle_plate="20E-00164", description="Phí cầu đường")
        c2 = OperatingCost(lot_id=lot.id, vehicle_plate="98H 07613", description="Phí bốc xếp")
        db_session.add_all([c1, c2])
        db_session.commit()

        veh = lot.distinct_vehicles
        assert len(veh) == 2
        plates = [v['plate'] for v in veh]
        assert "20E00164" in plates
        assert "98H07613" in plates

        labels = [v['label'] for v in veh]
        assert any("3,5T" in l for l in labels)
