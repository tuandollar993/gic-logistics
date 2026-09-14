import os
import pytest
from app.extensions import db
from app.models import Lot, Customer, OperatingCost
from app.services.excel_parser import ExcelParserService
from app.services.calculator import CalculatorService
from app.services.excel_exporter import ExcelExporterService


def test_t08_reconciliation_and_kpi_integrity(app):
    sales_file = 'Báo cáo bán hàng.xlsx'
    cost_file = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
    if not os.path.exists(sales_file) or not os.path.exists(cost_file):
        pytest.skip('Excel files not found for integration test')

    with app.app_context():
        # Import data
        res = ExcelParserService.import_all(sales_file, cost_file, reset_excel_data=True)
        assert len(res.get('errors', [])) == 0

        # 1. Sales Lots verification for T08/2026
        sales_lots = Lot.sales_lots_query().filter_by(month=8, year=2026).all()
        assert len(sales_lots) == 4, f"Expected exactly 4 Sales Lots in T08/2026, got {len(sales_lots)}"

        lots_by_label = {l.lot_label: l for l in sales_lots}
        assert 'Lô 1' in lots_by_label
        assert 'Lô 2' in lots_by_label
        assert 'Lô 3' in lots_by_label
        assert 'Lô 4' in lots_by_label

        lo1 = lots_by_label['Lô 1']
        lo2 = lots_by_label['Lô 2']
        lo3 = lots_by_label['Lô 3']
        lo4 = lots_by_label['Lô 4']

        # Sunluxe Lô 1 gets Group 3 (3,766,546)
        assert abs(lo1.total_operating_cost - 3766546.0) < 1.0, f"Lô 1 expected 3,766,546, got {lo1.total_operating_cost}"
        # Sunluxe Lô 2 gets Group 4 (4,594,001)
        assert abs(lo2.total_operating_cost - 4594001.0) < 1.0, f"Lô 2 expected 4,594,001, got {lo2.total_operating_cost}"
        # Huy Hoàng Lô 3 gets 0
        assert abs(lo3.total_operating_cost - 0.0) < 1.0, f"Lô 3 expected 0, got {lo3.total_operating_cost}"
        # Keep Rise Lô 4 gets Group 2 (1,066,000) + Group 5 (48,500,000) = 49,566,000
        assert abs(lo4.total_operating_cost - 49566000.0) < 1.0, f"Lô 4 expected 49,566,000, got {lo4.total_operating_cost}"

        # 2. Unresolved CPVH Group verification for T08/2026
        unresolved_lots = Lot.unresolved_cpvh_query().filter_by(month=8, year=2026).all()
        assert len(unresolved_lots) == 1, f"Expected exactly 1 Unresolved Group in T08/2026, got {len(unresolved_lots)}"
        unres = unresolved_lots[0]
        # Group 1 Ginhung (6,033,455 VND, 14 detail rows)
        assert 'ginhung' in (unres.company or '').lower()
        assert abs(unres.total_operating_cost - 6033455.0) < 1.0
        assert len(unres.operating_costs) == 14

        # 3. Overall Costs & Revenue Integrity
        all_t08_costs = OperatingCost.query.join(Lot).filter(Lot.month == 8, Lot.year == 2026, OperatingCost.is_deleted.is_(False)).all()
        assert len(all_t08_costs) == 66, f"Expected 66 detail cost rows, got {len(all_t08_costs)}"
        total_costs_sum = sum(c.total_amount or 0.0 for c in all_t08_costs)
        assert abs(total_costs_sum - 63960002.0) < 1.0, f"Expected 63,960,002 VND total costs, got {total_costs_sum}"

        # 4. CalculatorService KPI verification
        kpi = CalculatorService.get_monthly_kpi(8, 2026)
        assert kpi['lot_count'] == 4, f"KPI lot_count expected 4, got {kpi['lot_count']}"
        assert abs(kpi['revenue'] - 230328694.0) < 1.0, f"KPI revenue expected 230,328,694, got {kpi['revenue']}"
        assert abs(kpi['operating_cost'] - 63960002.0) < 1.0, f"KPI operating_cost expected 63,960,002, got {kpi['operating_cost']}"
        assert kpi['unresolved_group_count'] == 1
        assert abs(kpi['unresolved_cost_amount'] - 6033455.0) < 1.0

        # Net profit = Revenue - Buy Cost - Operating Cost
        expected_profit = kpi['revenue'] - kpi['buy_cost'] - kpi['operating_cost']
        assert abs(kpi['net_profit'] - expected_profit) < 1.0

        # 5. Customer Profile KPI Isolation
        # Sunluxe customer should NOT be burdened by Ginhung unresolved cost
        sunluxe = Customer.query.filter(Customer.name.ilike('%sunluxe%')).first()
        if sunluxe:
            sunluxe_lots = sunluxe.active_lots
            # Only Sales Lots should be present
            assert all(l.source_type != 'cpvh' for l in sunluxe_lots)
            # Cost should be Lô 1 + Lô 2, without Ginhung's 6,033,455
            sunluxe_ops = sum(l.total_operating_cost for l in sunluxe_lots if l.month == 8 and l.year == 2026)
            assert abs(sunluxe_ops - (3766546.0 + 4594001.0)) < 1.0

        # 6. Excel Exporter Verification
        bio = ExcelExporterService.export_monthly_report(8, 2026)
        assert bio.getbuffer().nbytes > 0


def test_t07_t09_sales_lots_counts(app):
    sales_file = 'Báo cáo bán hàng.xlsx'
    cost_file = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
    if not os.path.exists(sales_file) or not os.path.exists(cost_file):
        pytest.skip('Excel files not found for integration test')

    with app.app_context():
        ExcelParserService.import_all(sales_file, cost_file, reset_excel_data=True)

        # T07: exactly 5 sales lots
        t07_sales = Lot.sales_lots_query().filter_by(month=7, year=2026).all()
        assert len(t07_sales) == 5, f"Expected 5 Sales Lots in T07/2026, got {len(t07_sales)}"

        # T09: exactly 2 sales lots (Lô 1, Lô 2 have data; Lô 3+ are blank templates)
        t09_sales = Lot.sales_lots_query().filter_by(month=9, year=2026).all()
        assert len(t09_sales) == 2, f"Expected 2 Sales Lots in T09/2026, got {len(t09_sales)}"

