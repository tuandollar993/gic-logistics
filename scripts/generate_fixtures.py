import os
import json
import openpyxl
from datetime import datetime, date

def clean_val(val):
    if val is None:
        return ''
    if isinstance(val, (datetime, date)):
        return val.strftime('%d/%m/%Y')
    return str(val).strip()

def clean_num(val):
    if val is None or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '').strip())
    except Exception:
        return 0.0

def generate_cost_fixtures():
    excel_path = 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
    if not os.path.exists(excel_path):
        print(f"File not found: {excel_path}")
        return

    os.makedirs('tests/fixtures', exist_ok=True)
    wb = openpyxl.load_workbook(excel_path, data_only=True)

    configs = {
        'T07': {
            'month': 7,
            'year': 2026,
            'col_cost': 10,
            'col_vat': 11,
            'col_inv_type': 12,
            'col_inv_symbol': 13,
            'col_inv_num': 14,
            'col_date': 15,
            'col_mst': 16,
            'col_supp': 17,
            'col_note': 18,
            'col_pic': 19,
            'col_check': 21
        },
        'T08': {
            'month': 8,
            'year': 2026,
            'col_inv_type': 10,
            'col_inv_symbol': 11,
            'col_inv_num': 12,
            'col_date': 13,
            'col_mst': 14,
            'col_supp': 15,
            'col_note': 16,
            'col_pic': 17,
            'col_cost': 18,
            'col_vat': 19,
            'col_check': 21
        },
        'T09': {
            'month': 9,
            'year': 2026,
            'col_inv_type': 10,
            'col_inv_symbol': 11,
            'col_inv_num': 12,
            'col_date': 13,
            'col_mst': 14,
            'col_supp': 15,
            'col_note': 16,
            'col_pic': 17,
            'col_cost': 18,
            'col_vat': 19,
            'col_payment_method': 20,
            'col_check': 21
        }
    }

    for sheet_name, cfg in configs.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        detail_rows = []
        current_lo = ''
        current_ma_ho_so = ''

        for r in range(7, ws.max_row + 1):
            c1 = ws.cell(r, 1).value
            c2 = ws.cell(r, 2).value
            c3 = ws.cell(r, 3).value
            c4 = ws.cell(r, 4).value
            c5 = ws.cell(r, 5).value
            c9 = clean_num(ws.cell(r, 9).value)

            if not c4 and not c5 and c9 == 0:
                continue

            c5_str = str(c5 or '')
            if 'Tổng chi phí phát sinh' in c5_str or 'Số tiền đã tạm ứng' in c5_str:
                break

            if c2:
                current_lo = clean_val(c2)
            if c3:
                current_ma_ho_so = clean_val(c3)

            # Detail row has Loai chi phi (c4)
            if c4:
                cost_amt = clean_num(ws.cell(r, cfg.get('col_cost', 10)).value)
                vat_amt = clean_num(ws.cell(r, cfg.get('col_vat', 11)).value)
                inv_type = clean_val(ws.cell(r, cfg.get('col_inv_type', 12)).value)
                inv_num = clean_val(ws.cell(r, cfg.get('col_inv_num', 14)).value)
                date_val = clean_val(ws.cell(r, cfg.get('col_date', 15)).value)
                supp_val = clean_val(ws.cell(r, cfg.get('col_supp', 17)).value)
                note_val = clean_val(ws.cell(r, cfg.get('col_note', 18)).value)
                kt_check = clean_val(ws.cell(r, cfg.get('col_check', 21)).value)

                item_data = {
                    'stt': len(detail_rows) + 1,
                    'ngay_thang': date_val,
                    'ma_chi_phi': clean_val(c4),
                    'nha_cung_cap': supp_val,
                    'chi_tiet': clean_val(c5),
                    'gia_chua_vat': cost_amt,
                    'co_vat': vat_amt,
                    'tong_tien': c9 if c9 > 0 else cost_amt + vat_amt,
                    'thanh_toan': 'Chuyển khoản' if 'hóa đơn' in inv_type.lower() else 'Tiền mặt',
                    'cong_no': 0.0,
                    'da_thanh_toan': c9 if c9 > 0 else cost_amt + vat_amt,
                    'lo_hang': current_lo,
                    'ma_ho_so': current_ma_ho_so,
                    'invoice_status': f"{inv_type} {inv_num}".strip() if inv_type or inv_num else 'Không HĐ',
                    'payment_status': 'Đã đối soát' if kt_check else 'Hoàn thành',
                    'ghi_chu': note_val
                }
                detail_rows.append(item_data)

        fixture_data = {
            'sheet': sheet_name,
            'month': cfg['month'],
            'year': cfg['year'],
            'total_detail_rows': len(detail_rows),
            'total_cost_amount': sum(r['tong_tien'] for r in detail_rows),
            'rows': detail_rows
        }

        out_path = f"tests/fixtures/{sheet_name}_expected.json"
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(fixture_data, f, ensure_ascii=False, indent=2)
        print(f"Generated {out_path}: {len(detail_rows)} rows, sum = {fixture_data['total_cost_amount']:,.2f}")

def generate_cashflow_fixtures():
    os.makedirs('tests/fixtures', exist_ok=True)
    export_path = 'data/exports/Bang_Ke_Tam_Ung_GIDO_T08_2026.xlsx'

    # T08 Cashflow
    t08_txs = []
    if os.path.exists(export_path):
        wb = openpyxl.load_workbook(export_path, data_only=True)
        ws = wb.active
        for r in range(7, ws.max_row + 1):
            date_val = clean_val(ws.cell(r, 1).value)
            content = clean_val(ws.cell(r, 2).value)
            if not content:
                continue
            if 'TỔNG CỘNG' in content or 'Người lập' in content:
                break
            thu_cty = clean_num(ws.cell(r, 4).value)
            thu_haiban = clean_num(ws.cell(r, 5).value)
            thu_khac = clean_num(ws.cell(r, 6).value)
            tuan_chi = clean_num(ws.cell(r, 8).value)
            luong_thu = clean_num(ws.cell(r, 10).value)
            luong_chi = clean_num(ws.cell(r, 11).value)

            t08_txs.append({
                'row_index': r,
                'date': date_val,
                'content': content,
                'thu_cty': thu_cty,
                'thu_haiban': thu_haiban,
                'thu_khac': thu_khac,
                'tuan_chi': tuan_chi,
                'luong_thu': luong_thu,
                'luong_chi': luong_chi
            })

    t08_fixture = {
        'sheet': 'Tháng 08-2026',
        'month': 8,
        'year': 2026,
        'opening_balance': 30090895.0,
        'total_thu_cty': 4797799.0,
        'total_thu_haiban': 0.0,
        'total_thu_khac': 14287372.0,
        'total_chi_haiban_cty': 0.0,
        'total_tuan_chi': -57472000.0,
        'total_xuyen_chi': 0.0,
        'total_luong_thu': 9036628.0,
        'total_luong_chi': 0.0,
        'closing_balance': -9259306.0,
        'transaction_count': len(t08_txs),
        'transactions': t08_txs
    }

    with open('tests/fixtures/cashflow_T08_expected.json', 'w', encoding='utf-8') as f:
        json.dump(t08_fixture, f, ensure_ascii=False, indent=2)
    print(f"Generated tests/fixtures/cashflow_T08_expected.json: {len(t08_txs)} transactions")

    # T07 Cashflow Placeholder
    t07_fixture = {
        'sheet': 'Tháng 07-2026',
        'month': 7,
        'year': 2026,
        'opening_balance': 0.0,
        'total_thu_cty': 0.0,
        'total_tuan_chi': 0.0,
        'closing_balance': 0.0,
        'transaction_count': 0,
        'transactions': []
    }
    with open('tests/fixtures/cashflow_T07_expected.json', 'w', encoding='utf-8') as f:
        json.dump(t07_fixture, f, ensure_ascii=False, indent=2)

    # T09 Cashflow Placeholder
    t09_fixture = {
        'sheet': 'Tháng 09-2026',
        'month': 9,
        'year': 2026,
        'opening_balance': -9259306.0,
        'total_thu_cty': 0.0,
        'total_tuan_chi': 0.0,
        'closing_balance': -9259306.0,
        'transaction_count': 0,
        'transactions': []
    }
    with open('tests/fixtures/cashflow_T09_expected.json', 'w', encoding='utf-8') as f:
        json.dump(t09_fixture, f, ensure_ascii=False, indent=2)
    print("Generated cashflow T07 and T09 fixtures")

if __name__ == '__main__':
    generate_cost_fixtures()
    generate_cashflow_fixtures()
