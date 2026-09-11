import os
import sys
import json
from collections import defaultdict

def run_reconciliation():
    sys.stdout.reconfigure(encoding='utf-8')

    sales_file = 'Báo cáo bán hàng.xlsx'
    cost_file = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'

    # Check file availability
    sales_exists = os.path.exists(sales_file)
    cost_exists = os.path.exists(cost_file)

    if not sales_exists or not cost_exists:
        print("[SOURCE_MISSING] Thiếu file nguồn Excel đối soát:")
        if not sales_exists:
            print(f"  - Thiếu: {sales_file}")
        if not cost_exists:
            print(f"  - Thiếu: {cost_file}")
        return False

    # Strictly enforce isolated temporary in-memory database to protect production
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['SECRET_KEY'] = 'temp-test-key-32-chars-strictly-temp!'
    os.environ['FLASK_ENV'] = 'testing'

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from app import create_app
    from app.extensions import db
    from app.services.excel_parser import ExcelParserService
    from app.models import Lot, OperatingCost

    app = create_app()
    with app.app_context():
        db.create_all()
        print('Starting import_all on temporary isolated in-memory DB...')
        res = ExcelParserService.import_all(sales_file, cost_file, reset_excel_data=True)
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
            if not is_match:
                rev_ok = False
            status = 'MATCH' if is_match else 'FAIL'
            print(f'{k[0]:02d}/{k[1]}: Actual = {actual:14,.2f} | Exp = {exp:14,.2f} | Diff = {diff:8.2f} | [{status}]')

        print('\n=== CHI PHÍ VẬN HÀNH ĐỐI SOÁT ===')
        cost_ok = True
        for k in sorted(expected_cost.keys(), key=lambda x: (x[1], x[0])):
            actual = monthly_cost.get(k, 0.0)
            exp = expected_cost[k]
            diff = actual - exp
            is_match = abs(diff) < 0.1
            if not is_match:
                cost_ok = False
            status = 'MATCH' if is_match else 'FAIL'
            print(f'{k[0]:02d}/{k[1]}: Actual = {actual:14,.2f} | Exp = {exp:14,.2f} | Diff = {diff:8.2f} | [{status}]')

        print('\n=== ĐỐI SOÁT TỪNG DÒNG / 16 TRƯỜNG NGHIỆP VỤ ===')
        fixtures_ok = True
        for f_name in ['T07', 'T08', 'T09']:
            f_path = f'tests/fixtures/{f_name}_expected.json'
            if not os.path.exists(f_path):
                print(f"[SOURCE_MISSING] Fixture không tồn tại: {f_path}")
                fixtures_ok = False
                continue

            with open(f_path, 'r', encoding='utf-8') as f:
                f_data = json.load(f)

            m = f_data['month']
            y = f_data['year']
            costs = OperatingCost.query.join(Lot).filter(
                Lot.month == m, Lot.year == y, OperatingCost.source_sheet == f_name
            ).all()
            total_db_cost = sum(c.total_amount or 0.0 for c in costs)
            exp_cost = f_data['total_cost_amount']

            # `stt` is the source detail sequence produced from the immutable
            # spreadsheet row order. It is a stable business key inside one
            # source sheet; duplicate/missing keys are reported explicitly.
            expected_by_key = {str(row['stt']): row for row in f_data['rows']}
            actual_by_key, duplicate, source_missing = {}, [], []
            for cost in costs:
                if not cost.source_payload:
                    source_missing.append(str(cost.id))
                    continue
                try:
                    payload = json.loads(cost.source_payload)
                    key = str(payload['stt'])
                except (ValueError, TypeError, KeyError):
                    source_missing.append(str(cost.id))
                    continue
                if key in actual_by_key:
                    duplicate.append(key)
                else:
                    actual_by_key[key] = payload

            db_missing = sorted(set(expected_by_key) - set(actual_by_key), key=int)
            source_extra = sorted(set(actual_by_key) - set(expected_by_key), key=int)
            mismatched = []
            numeric_fields = {'gia_chua_vat', 'co_vat', 'tong_tien', 'cong_no', 'da_thanh_toan'}
            fields = [
                'stt', 'ngay_thang', 'ma_chi_phi', 'nha_cung_cap', 'chi_tiet',
                'gia_chua_vat', 'co_vat', 'tong_tien', 'thanh_toan', 'cong_no',
                'da_thanh_toan', 'lo_hang', 'ma_ho_so', 'invoice_status',
                'payment_status', 'ghi_chu'
            ]
            for key in sorted(set(expected_by_key) & set(actual_by_key), key=int):
                expected, actual = expected_by_key[key], actual_by_key[key]
                differences = []
                for field in fields:
                    if field in numeric_fields:
                        if abs(float(expected.get(field, 0) or 0) - float(actual.get(field, 0) or 0)) >= 0.1:
                            differences.append(field)
                    elif str(expected.get(field, '') or '').strip() != str(actual.get(field, '') or '').strip():
                        differences.append(field)
                if differences:
                    mismatched.append({'key': key, 'fields': differences})

            amount_match = abs(total_db_cost - exp_cost) < 0.1
            is_match = not (duplicate or source_missing or db_missing or source_extra or mismatched) and amount_match
            fixtures_ok = fixtures_ok and is_match
            print(
                f"Fixture {f_name}: rows={len(costs)}/{f_data['total_detail_rows']}, "
                f"sum={total_db_cost:,.2f}/{exp_cost:,.2f}, matched={len(expected_by_key) - len(db_missing) - len(mismatched)}, "
                f"mismatched={len(mismatched)}, duplicate={len(duplicate)}, "
                f"source_missing={len(source_missing) + len(source_extra)}, db_missing={len(db_missing)} "
                f"[{'MATCH' if is_match else 'FAIL'}]"
            )
            if mismatched:
                print(f"  Sample mismatches: {mismatched[:5]}")

        all_ok = rev_ok and cost_ok and fixtures_ok
        if all_ok:
            print('\n>>> 100%: mọi dòng và đủ 16 trường nghiệp vụ đều khớp trong T07/T08/T09. <<<')
        else:
            print('\n>>> CÓ LỆCH DỮ LIỆU! CẦN KIỂM TRA LẠI <<<')
        return all_ok

if __name__ == '__main__':
    ok = run_reconciliation()
    sys.exit(0 if ok else 1)
