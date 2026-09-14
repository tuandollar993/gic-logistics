import os
import pytest
from app.services.advance_service import clean_date_vn
from app.services.excel_parser import parse_month_year, ExcelParserService
from app.models import Lot
from collections import defaultdict

def test_clean_date_vn():
    assert clean_date_vn('20.8', default_year=2026) == '20/08/2026'
    assert clean_date_vn('05/09', default_year=2026) == '05/09/2026'
    assert clean_date_vn('2026-09-15') == '15/09/2026'
    assert clean_date_vn('15/09/2026') == '15/09/2026'

def test_parse_month_year():
    assert parse_month_year('09.2026') == (9, 2026)
    assert parse_month_year('T07.2026') == (7, 2026)
    assert parse_month_year('9/2026') == (9, 2026)

def test_excel_reconciliation(app):
    sales_file = 'Báo cáo bán hàng.xlsx'
    cost_file = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
    if not os.path.exists(sales_file) or not os.path.exists(cost_file):
        pytest.skip('Excel files not found for integration reconciliation test')

    with app.app_context():
        res = ExcelParserService.import_all(sales_file, cost_file, reset_excel_data=False)
        assert len(res.get('errors', [])) == 0

        all_lots = Lot.query.all()
        monthly_rev = defaultdict(float)
        monthly_cost = defaultdict(float)
        for l in all_lots:
            key = (l.month, l.year)
            monthly_rev[key] += l.total_sell_revenue
            monthly_cost[key] += l.total_operating_cost

        expected_rev = {
            (9, 2025): 678500000.0,
            (10, 2025): 213694000.0,
            (11, 2025): 67000000.0,
            (12, 2025): 598852683.0,
            (1, 2026): 540877273.0,
            (2, 2026): 236334993.0,
            (3, 2026): 370535615.0,
            (4, 2026): 405341441.5,
            (5, 2026): 997912360.1,
            (6, 2026): 112114708.3,
            (7, 2026): 162167139.3,
            (8, 2026): 231570694.0,
            (9, 2026): 800000.0
        }

        expected_cost = {
            (11, 2025): 92095601.0,
            (7, 2026): 68464436.0,
            (8, 2026): 63960002.0
        }

        for k, exp in expected_rev.items():
            actual = monthly_rev.get(k, 0.0)
            assert abs(actual - exp) < 0.1, f'Revenue mismatch in {k}: actual={actual} exp={exp}'

        for k, exp in expected_cost.items():
            actual = monthly_cost.get(k, 0.0)
            assert abs(actual - exp) < 0.1, f'Cost mismatch in {k}: actual={actual} exp={exp}'


def test_fixtures_reconciliation(app):
    sales_file = 'Báo cáo bán hàng.xlsx'
    cost_file = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
    if not os.path.exists(sales_file) or not os.path.exists(cost_file):
        pytest.skip('[SOURCE_MISSING] Excel files not found for fixture reconciliation test')

    import json
    from app.models import OperatingCost

    with app.app_context():
        ExcelParserService.import_all(sales_file, cost_file, reset_excel_data=False)

        for f_name in ['T07', 'T08']:
            f_path = f'tests/fixtures/{f_name}_expected.json'
            if not os.path.exists(f_path):
                pytest.skip(f'[SOURCE_MISSING] Fixture file {f_path} not found')

            with open(f_path, 'r', encoding='utf-8') as f:
                f_data = json.load(f)

            m = f_data['month']
            y = f_data['year']
            costs = OperatingCost.query.join(Lot).filter(Lot.month == m, Lot.year == y).all()
            assert len(costs) == f_data['total_detail_rows'], f"Row count mismatch in {f_name}"
            total_cost = sum(c.total_amount or 0.0 for c in costs)
            assert abs(total_cost - f_data['total_cost_amount']) < 0.1, f"Total amount mismatch in {f_name}"

