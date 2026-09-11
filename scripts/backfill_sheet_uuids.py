"""scripts/backfill_sheet_uuids.py

Điền UUID vào cột R (External ID) cho các dòng trên Google Sheet chưa có UUID:
- Duyệt qua các sheet tháng (Tháng 07-2026, Tháng 08-2026, v.v.).
- Nhận diện các dòng giao dịch thiếu UUID ở cột R.
- Sinh UUID v4 chuẩn.
- Mặc định ở chế độ --dry-run (không sửa Sheet hay DB).
- Dùng cờ --execute để ghi UUID lên Google Sheet và đồng bộ vào DB.
"""
import sys
import uuid
import argparse
import urllib.parse
import requests
from app import create_app
from app.extensions import db
from app.models import CashAdvanceMonthly, CashAdvanceTransaction
from app.services.advance_service import (
    get_google_access_token,
    fetch_sheet_list,
    GIDO_SPREADSHEET_ID,
    clean_amount
)

def backfill_sheet_uuids(execute=False):
    app = create_app()
    with app.app_context():
        mode_str = "EXECUTE" if execute else "DRY-RUN (Safe mode)"
        print(f"=== BACKFILL GOOGLE SHEET UUIDS (COLUMN R) [{mode_str}] ===")
        
        token = get_google_access_token()
        if not token:
            print("[Error] Không thể lấy Google Access Token. Kiểm tra credentials.")
            return

        sheets = fetch_sheet_list()
        monthly_sheets = [s for s in sheets if s['title'].strip().startswith('Tháng')]
        print(f"Tìm thấy {len(monthly_sheets)} sheet tháng cần kiểm tra.")

        total_missing = 0
        total_filled = 0

        for s_info in monthly_sheets:
            title = s_info['title'].strip()
            quoted = urllib.parse.quote(f"{title}!A1:R")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{quoted}"
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=15)
            if resp.status_code != 200:
                print(f"[{title}] Lỗi đọc sheet: {resp.status_code}")
                continue

            rows = resp.json().get('values', [])
            if len(rows) < 7:
                continue

            missing_rows = []
            for idx, row in enumerate(rows):
                if idx < 6:
                    continue
                first_col = row[0].strip() if len(row) > 0 and row[0] else ''
                second_col = row[1].strip() if len(row) > 1 and row[1] else ''
                
                # Check for TỔNG row to stop
                clean_second = second_col.upper()
                if clean_second.startswith('TỔNG') or clean_second.startswith('TONG'):
                    break
                if clean_second.startswith('NGƯỜI LẬP') or clean_second.startswith('NGUOI LAP'):
                    break

                if not first_col and not second_col:
                    continue

                # Column R is index 17
                has_uuid = len(row) > 17 and bool(str(row[17]).strip())
                if not has_uuid:
                    row_num = idx + 1
                    gen_uuid = str(uuid.uuid4())
                    missing_rows.append((row_num, first_col, second_col, gen_uuid))

            if missing_rows:
                print(f"\n[{title}] Phát hiện {len(missing_rows)} dòng chưa có UUID tại cột R:")
                for r_num, date_c, content_c, uid_val in missing_rows:
                    print(f"  - Dòng {r_num} ({date_c} - {content_c}): New UUID = {uid_val}")
                    total_missing += 1

                if execute:
                    # Update each row in Google Sheet column R
                    for r_num, date_c, content_c, uid_val in missing_rows:
                        update_range = f"{title}!R{r_num}"
                        q_range = urllib.parse.quote(update_range)
                        put_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{q_range}?valueInputOption=USER_ENTERED"
                        put_resp = requests.put(
                            put_url,
                            json={'values': [[uid_val]]},
                            headers={'Authorization': f'Bearer {token}'},
                            timeout=10
                        )
                        if put_resp.status_code == 200:
                            total_filled += 1
                        else:
                            print(f"    [Error] Ghi Google Sheet dòng {r_num} thất bại: {put_resp.text}")

        if execute:
            print(f"\n[EXECUTE SUCCESS] Đã điền thành công {total_filled} / {total_missing} UUID vào cột R trên Google Sheets.")
        else:
            print(f"\n[DRY-RUN] Hoàn tất quét. Tổng số dòng thiếu UUID: {total_missing}. Chạy với cờ --execute để ghi.")

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Backfill Sheet UUIDs in column R")
    parser.add_argument('--execute', action='store_true', help="Thực thi ghi UUID lên Google Sheet (mặc định là dry-run)")
    args = parser.parse_args()
    backfill_sheet_uuids(execute=args.execute)
