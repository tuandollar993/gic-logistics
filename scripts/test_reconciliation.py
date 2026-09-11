import sys
sys.stdout.reconfigure(encoding='utf-8')
from app import create_app
from app.extensions import db
from app.services.excel_parser import ExcelParserService
from app.models import Lot, RevenueItem, OperatingCost
from collections import defaultdict

app = create_app()
with app.app_context():
    db.create_all()
    print('Starting import_all...')
    res = ExcelParserService.import_all('Báo cáo bán hàng.xlsx', 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx', reset_excel_data=True)
    print('Import results:', res)
    
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
        (8, 2026): 230328694.0,
        (9, 2026): 800000.0
    }
    
    expected_cost = {
        (11, 2025): 92095601.0,
        (7, 2026): 68464436.0,
        (8, 2026): 63960002.0
    }
    
    print('\n=== DOANH THU ĐỐI SOÁT ===')
    rev_ok = True
    for k in sorted(expected_rev.keys(), key=lambda x: (x[1], x[0])):
        actual = monthly_rev.get(k, 0.0)
        exp = expected_rev[k]
        diff = actual - exp
        is_match = abs(diff) < 0.1
        if not is_match: rev_ok = False
        status = 'MATCH' if is_match else 'FAIL'
        print(f'{k[0]:02d}/{k[1]}: Actual = {actual:14,.2f} | Exp = {exp:14,.2f} | Diff = {diff:8.2f} | [{status}]')
        
    print('\n=== CHI PHÍ VẬN HÀNH ĐỐI SOÁT ===')
    cost_ok = True
    for k in sorted(expected_cost.keys(), key=lambda x: (x[1], x[0])):
        actual = monthly_cost.get(k, 0.0)
        exp = expected_cost[k]
        diff = actual - exp
        is_match = abs(diff) < 0.1
        if not is_match: cost_ok = False
        status = 'MATCH' if is_match else 'FAIL'
        print(f'{k[0]:02d}/{k[1]}: Actual = {actual:14,.2f} | Exp = {exp:14,.2f} | Diff = {diff:8.2f} | [{status}]')
        
    rev_msg = "PASSED" if rev_ok else "FAILED"
    cost_msg = "PASSED" if cost_ok else "FAILED"
    print(f'\nOverall Revenue Check: {rev_msg}')
    print(f'Overall Operating Cost Check: {cost_msg}')
