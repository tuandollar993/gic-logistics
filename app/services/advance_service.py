import os
import json
import time
import base64
import urllib.parse
from datetime import datetime
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from app.extensions import db
from app.models import CashAdvanceMonthly, CashAdvanceTransaction, CashAdvanceBillMedia

GIDO_SPREADSHEET_ID = os.environ.get('GIDO_SPREADSHEET_ID', '1ZZC5hnoRRo93Fc3AH-mcKCu692xRhX6Zy04ENhiz6p8')
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'google-credentials.json')

_token_cache = {
    'token': None,
    'expires_at': 0
}

def clean_amount(val):
    """Chuyển đổi chuỗi tiền mặt Google Sheet sang float"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s == '-' or s == '–':
        return 0.0
    # Xử lý dấu âm dạng "- 57.472.000" hoặc "(57.472.000)" hoặc "-57472000"
    is_neg = False
    if s.startswith('(') and s.endswith(')'):
        is_neg = True
        s = s[1:-1].strip()
    elif s.startswith('-'):
        is_neg = True
        s = s[1:].strip()
    
    s = s.replace('.', '').replace(',', '').replace(' ', '').replace('₫', '').replace('VND', '')
    try:
        num = float(s)
        return -num if is_neg else num
    except Exception:
        return 0.0

def get_credentials_data():
    """Lấy thông tin Google credentials từ file hoặc biến môi trường (Render/Vercel)"""
    env_creds = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if env_creds:
        try:
            return json.loads(env_creds)
        except Exception:
            pass

    env_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
    if env_b64:
        try:
            decoded = base64.b64decode(env_b64).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            pass

    client_email = os.environ.get('GOOGLE_CLIENT_EMAIL')
    private_key = os.environ.get('GOOGLE_PRIVATE_KEY')
    if client_email and private_key:
        return {
            'client_email': client_email.strip(),
            'private_key': private_key.replace('\\n', '\n').strip()
        }

    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return None

def get_google_access_token():
    """Lấy JWT Access Token từ Google Service Account"""
    now = int(time.time())
    if _token_cache['token'] and _token_cache['expires_at'] > now + 120:
        return _token_cache['token']

    key_data = get_credentials_data()
    if not key_data:
        return None

    try:
        header = base64.urlsafe_b64encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
        payload_data = {
            'iss': key_data['client_email'],
            'scope': 'https://www.googleapis.com/auth/spreadsheets',
            'aud': 'https://oauth2.googleapis.com/token',
            'exp': now + 3600,
            'iat': now
        }
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b'=').decode()
        unsigned_token = f'{header}.{payload}'.encode()

        private_key = serialization.load_pem_private_key(key_data['private_key'].encode(), password=None)
        signature = private_key.sign(unsigned_token, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        signed_jwt = f'{header}.{payload}.{sig_b64}'

        resp = requests.post('https://oauth2.googleapis.com/token', data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': signed_jwt
        }, timeout=15)
        
        data = resp.json()
        token = data.get('access_token')
        if token:
            _token_cache['token'] = token
            _token_cache['expires_at'] = now + 3500
            return token
    except Exception as e:
        print(f"[AdvanceService] Error getting Google access token: {e}")
    return None

def fetch_sheet_list():
    """Lấy danh sách các sheet trong file Google Sheet"""
    token = get_google_access_token()
    if not token:
        return []
    try:
        url = f'https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}?fields=sheets.properties'
        resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=15)
        if resp.status_code == 200:
            sheets = resp.json().get('sheets', [])
            result = []
            for s in sheets:
                p = s.get('properties', {})
                result.append({
                    'title': p.get('title'),
                    'sheetId': p.get('sheetId')
                })
            return result
    except Exception as e:
        print(f"[AdvanceService] Error fetching sheet list: {e}")
    return []

def get_sheet_title_for_month(month, year):
    """Tìm tên sheet tương ứng với Tháng/Năm, e.g. Tháng 08-2026"""
    formatted_target = f"Tháng {month:02d}-{year}"
    formatted_short = f"Tháng {month}-{year}"
    sheet_list = fetch_sheet_list()
    for s in sheet_list:
        title = s['title'].strip()
        if title == formatted_target or title == formatted_short:
            return title, str(s['sheetId'])
    # fallback
    return formatted_target, None

def sync_month_from_google(month, year):
    """
    Đồng bộ dữ liệu bảng kê tạm ứng của Tháng/Năm từ Google Sheet vào SQLite
    """
    token = get_google_access_token()
    if not token:
        return None, "Không tìm thấy token kết nối Google Service Account"

    sheet_title, sheet_gid = get_sheet_title_for_month(month, year)
    quoted_title = urllib.parse.quote(f"{sheet_title}!A1:Q50")
    url = f'https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{quoted_title}'

    try:
        resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=20)
        if resp.status_code != 200:
            return None, f"Lỗi Google API ({resp.status_code}): {resp.text}"

        rows = resp.json().get('values', [])
        if not rows or len(rows) < 6:
            return None, f"Sheet '{sheet_title}' không có dữ liệu giao dịch hoặc chưa đúng cấu trúc."

        # Bắt đầu duyệt dữ liệu từ dòng 7 (index 6) trở đi
        # Tìm dòng tiêu đề 'TỔNG' để dừng
        transactions_data = []
        totals_row = None
        creator = "Trần Xuân Trường"

        import unicodedata

        for idx, row in enumerate(rows):
            if idx < 6:
                continue
            
            first_col = unicodedata.normalize('NFC', row[0].strip()) if len(row) > 0 and row[0] else ''
            second_col = unicodedata.normalize('NFC', row[1].strip()) if len(row) > 1 and row[1] else ''
            
            # Kiểm tra dòng TỔNG (chuẩn hóa NFC)
            clean_second = second_col.upper()
            if clean_second.startswith('TỔNG') or clean_second.startswith('TONG'):
                totals_row = row
                break
            if clean_second.startswith('NGƯỜI LẬP') or clean_second.startswith('NGUOI LAP'):
                break
            if idx >= len(rows) - 3 and not first_col and second_col:
                creator = second_col
                continue

            # Bỏ qua dòng trống hoàn toàn
            if not any(bool(str(c).strip()) for c in row):
                continue

            # Nếu có nội dung hoặc có ngày
            if first_col or second_col:
                trans = {
                    'row_index': idx + 1,
                    'trans_date': first_col,
                    'content': second_col,
                    'tuan_ton': clean_amount(row[2]) if len(row) > 2 else 0.0,
                    'tuan_thu_cty': clean_amount(row[3]) if len(row) > 3 else 0.0,
                    'tuan_thu_haiban': clean_amount(row[4]) if len(row) > 4 else 0.0,
                    'tuan_thu_khac': clean_amount(row[5]) if len(row) > 5 else 0.0,
                    'tuan_chi_haiban_cty': clean_amount(row[6]) if len(row) > 6 else 0.0,
                    'tuan_chi': clean_amount(row[7]) if len(row) > 7 else 0.0,
                    'xuyen_amount': clean_amount(row[8]) if len(row) > 8 else 0.0,
                    'luong_thu': clean_amount(row[9]) if len(row) > 9 else 0.0,
                    'luong_chi': clean_amount(row[10]) if len(row) > 10 else 0.0,
                    'truong_amount': clean_amount(row[11]) if len(row) > 11 else 0.0,
                    'partner_amount': clean_amount(row[12]) if len(row) > 12 else 0.0,
                    'partner_invoice': str(row[13]).strip() if len(row) > 13 and row[13] else '',
                    'bill_link': str(row[14]).strip() if len(row) > 14 and row[14] else '',
                    'advance_refund': str(row[15]).strip() if len(row) > 15 and row[15] else '',
                    'accounting_status': str(row[16]).strip() if len(row) > 16 and row[16] else ''
                }
                transactions_data.append(trans)

        # Tính toán hoặc lấy tổng
        opening_bal = 0.0
        closing_bal = 0.0
        tot_cty = sum(t['tuan_thu_cty'] for t in transactions_data)
        tot_haiban = sum(t['tuan_thu_haiban'] for t in transactions_data)
        tot_khac = sum(t['tuan_thu_khac'] for t in transactions_data)
        tot_hb_cty = sum(t['tuan_chi_haiban_cty'] for t in transactions_data)
        tot_spent = sum(abs(t['tuan_chi']) for t in transactions_data if t['tuan_chi'] < 0) or sum(t['tuan_chi'] for t in transactions_data)
        tot_xuyen = sum(t['xuyen_amount'] for t in transactions_data)
        tot_luong_thu = sum(t['luong_thu'] for t in transactions_data)
        tot_luong_chi = sum(t['luong_chi'] for t in transactions_data)
        tot_truong = sum(t['truong_amount'] for t in transactions_data)
        tot_partner = sum(t['partner_amount'] for t in transactions_data)

        if totals_row:
            closing_bal = clean_amount(totals_row[2]) if len(totals_row) > 2 else 0.0
            if len(totals_row) > 3 and clean_amount(totals_row[3]):
                tot_cty = clean_amount(totals_row[3])
            if len(totals_row) > 4 and clean_amount(totals_row[4]):
                tot_haiban = clean_amount(totals_row[4])
            if len(totals_row) > 5 and clean_amount(totals_row[5]):
                tot_khac = clean_amount(totals_row[5])
            if len(totals_row) > 6 and clean_amount(totals_row[6]):
                tot_hb_cty = clean_amount(totals_row[6])
            if len(totals_row) > 7 and clean_amount(totals_row[7]):
                tot_spent = clean_amount(totals_row[7])
            if len(totals_row) > 8 and clean_amount(totals_row[8]):
                tot_xuyen = clean_amount(totals_row[8])
            if len(totals_row) > 9 and clean_amount(totals_row[9]):
                tot_luong_thu = clean_amount(totals_row[9])
            if len(totals_row) > 10 and clean_amount(totals_row[10]):
                tot_luong_chi = clean_amount(totals_row[10])
            if len(totals_row) > 11 and clean_amount(totals_row[11]):
                tot_truong = clean_amount(totals_row[11])
            if len(totals_row) > 12 and clean_amount(totals_row[12]):
                tot_partner = clean_amount(totals_row[12])

        # Lấy tồn tháng trước nếu có để làm opening balance
        prev_month = 12 if month == 1 else month - 1
        prev_year = year - 1 if month == 1 else year
        prev_record = CashAdvanceMonthly.query.filter_by(month=prev_month, year=prev_year).first()
        if prev_record and prev_record.closing_balance:
            opening_bal = prev_record.closing_balance

        # Upsert CashAdvanceMonthly
        monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
        if not monthly:
            monthly = CashAdvanceMonthly(month=month, year=year)
            db.session.add(monthly)

        monthly.sheet_name = sheet_title
        monthly.sheet_gid = sheet_gid
        monthly.opening_balance = opening_bal
        monthly.total_company_receipts = tot_cty
        monthly.total_haiban_receipts = tot_haiban
        monthly.total_other_receipts = tot_khac
        monthly.total_haiban_to_company = tot_hb_cty
        monthly.total_advances_spent = tot_spent
        monthly.total_xuyen = tot_xuyen
        monthly.total_luong_thu = tot_luong_thu
        monthly.total_luong_chi = tot_luong_chi
        monthly.total_truong = tot_truong
        monthly.total_partner = tot_partner
        monthly.closing_balance = closing_bal
        monthly.creator_name = creator
        monthly.last_synced_at = datetime.utcnow()
        
        db.session.flush()

        # Xóa các dòng sync cũ (giữ lại dòng tạo manual nếu có)
        CashAdvanceTransaction.query.filter_by(month=month, year=year, is_manual=False).delete()

        for item in transactions_data:
            trans = CashAdvanceTransaction(
                monthly_id=monthly.id,
                month=month,
                year=year,
                row_index=item['row_index'],
                trans_date=item['trans_date'],
                content=item['content'],
                tuan_ton=item['tuan_ton'],
                tuan_thu_cty=item['tuan_thu_cty'],
                tuan_thu_haiban=item['tuan_thu_haiban'],
                tuan_thu_khac=item['tuan_thu_khac'],
                tuan_chi_haiban_cty=item['tuan_chi_haiban_cty'],
                tuan_chi=item['tuan_chi'],
                xuyen_amount=item['xuyen_amount'],
                luong_thu=item['luong_thu'],
                luong_chi=item['luong_chi'],
                truong_amount=item['truong_amount'],
                partner_amount=item['partner_amount'],
                partner_invoice=item['partner_invoice'],
                bill_link=item['bill_link'],
                advance_refund=item['advance_refund'],
                accounting_status=item['accounting_status'],
                is_manual=False
            )
            db.session.add(trans)

        db.session.commit()
        return monthly, None

    except Exception as e:
        db.session.rollback()
        print(f"[AdvanceService] Error syncing sheet: {e}")
        return None, str(e)

def get_monthly_advances_data(month, year):
    """
    Lấy dữ liệu bảng kê tạm ứng cho giao diện web.
    Nếu trong DB chưa có, tự động kích hoạt sync từ Google Sheets.
    """
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    
    # Nếu chưa có trong DB hoặc chưa có transaction nào, thử sync ngay
    if not monthly or monthly.transactions.count() == 0:
        synced, err = sync_month_from_google(month, year)
        if synced:
            monthly = synced

    transactions = []
    if monthly:
        transactions = monthly.transactions.order_by(CashAdvanceTransaction.row_index.asc(), CashAdvanceTransaction.id.asc()).all()

    # Tính toán các chỉ số tóm tắt (KPIs)
    total_in = (monthly.total_company_receipts if monthly else 0.0) + \
               (monthly.total_haiban_receipts if monthly else 0.0) + \
               (monthly.total_other_receipts if monthly else 0.0)
    
    total_out = abs(monthly.total_advances_spent if monthly else 0.0)
    
    # Dư nợ/tạm ứng các bộ phận
    personnel_summary = {
        'tuan_chi': abs(monthly.total_advances_spent if monthly else 0.0),
        'xuyen': monthly.total_xuyen if monthly else 0.0,
        'luong': (monthly.total_luong_thu if monthly else 0.0) - (monthly.total_luong_chi if monthly else 0.0),
        'truong': monthly.total_truong if monthly else 0.0,
        'partner': monthly.total_partner if monthly else 0.0
    }

    # Thống kê chứng từ
    has_invoice_count = sum(1 for t in transactions if t.partner_invoice and t.partner_invoice.strip() and 'không có' not in t.partner_invoice.lower() and 'không hđ' not in t.partner_invoice.lower())
    no_invoice_count = sum(1 for t in transactions if 'không có' in (t.partner_invoice or '').lower() or 'không hđ' in (t.partner_invoice or '').lower())
    has_bill_count = sum(1 for t in transactions if t.bill_link and t.bill_link.strip())

    metrics = {
        'month': month,
        'year': year,
        'opening_balance': monthly.opening_balance if monthly else 0.0,
        'closing_balance': monthly.closing_balance if monthly else 0.0,
        'total_company_receipts': monthly.total_company_receipts if monthly else 0.0,
        'total_haiban_receipts': monthly.total_haiban_receipts if monthly else 0.0,
        'total_other_receipts': monthly.total_other_receipts if monthly else 0.0,
        'total_in': total_in,
        'total_out': total_out,
        'personnel_summary': personnel_summary,
        'creator_name': monthly.creator_name if monthly else 'Trần Xuân Trường',
        'last_synced_at': monthly.last_synced_at.strftime('%d/%m/%Y %H:%M') if (monthly and monthly.last_synced_at) else 'Chưa đồng bộ',
        'trans_count': len(transactions),
        'has_invoice_count': has_invoice_count,
        'no_invoice_count': no_invoice_count,
        'has_bill_count': has_bill_count
    }

    return {
        'monthly': monthly,
        'metrics': metrics,
        'transactions': transactions
    }

def get_all_available_months():
    """Lấy danh sách các tháng có sẵn trong năm 2026"""
    # Các tháng cố định 1 đến 12 năm 2026
    return [(2026, m) for m in range(1, 13)]

def export_advances_excel(month, year):
    """
    Tạo file Excel (.xlsx) xuất báo cáo dòng tiền tạm ứng chuẩn định dạng
    """
    data = get_monthly_advances_data(month, year)
    transactions = data['transactions']
    monthly = data['monthly']

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Tháng {month:02d}-{year}"

    # Định dạng Font & Style
    font_title = Font(name="Arial", size=14, bold=True, color="1E3A8A")
    font_sub = Font(name="Arial", size=10, italic=True, color="475569")
    font_header = Font(name="Arial", size=9, bold=True, color="FFFFFF")
    font_sub_header = Font(name="Arial", size=8, bold=True, color="1E293B")
    font_data = Font(name="Arial", size=9)
    font_total = Font(name="Arial", size=9, bold=True, color="0F172A")
    
    fill_header_main = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_header_tuan = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
    fill_sub_header = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    fill_total = PatternFill(start_color="FEF08A", end_color="FEF08A", fill_type="solid")
    fill_even = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color="CBD5E1"),
        right=Side(style='thin', color="CBD5E1"),
        top=Side(style='thin', color="CBD5E1"),
        bottom=Side(style='thin', color="CBD5E1")
    )

    # Tiêu đề
    ws.merge_cells("C2:I2")
    ws["C2"] = f"BẢNG KÊ TẠM ỨNG TIỀN MẶT GIDO - THÁNG {month:02d}/{year}"
    ws["C2"].font = font_title
    ws["C2"].alignment = Alignment(horizontal="center", vertical="center")

    ws["C3"] = f"01/{month:02d}/{year}"
    ws["C3"].font = font_sub
    ws["C3"].alignment = Alignment(horizontal="center")

    # Header Row 5
    headers_row5 = [
        ("A5", "NGÀY"),
        ("B5", "NỘI DUNG"),
        ("C5", "TUẤN (THU & CHI)"),
        ("I5", "XUYÊN"),
        ("J5", "LƯƠNG"),
        ("L5", "TRƯỜNG"),
        ("M5", "ĐỐI TÁC"),
        ("N5", "HÓA ĐƠN ĐỐI TÁC"),
        ("O5", "LINK BILL CK"),
        ("P5", "HOÀN ỨNG"),
        ("Q5", "KẾ TOÁN DUYỆT")
    ]
    
    ws.merge_cells("C5:H5")
    ws.merge_cells("J5:K5")
    
    for pos, text in headers_row5:
        cell = ws[pos]
        cell.value = text
        cell.font = font_header
        cell.fill = fill_header_main if not pos.startswith('C') else fill_header_tuan
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Sub-header Row 6
    sub_headers = [
        ("A6", ""), ("B6", ""),
        ("C6", "Tồn"), ("D6", "Thu Cty"), ("E6", "Thu Hải Bân"), 
        ("F6", "Thu khác"), ("G6", "Chi HB về Cty"), ("H6", "Chi"),
        ("I6", "Chi"),
        ("J6", "Thu"), ("K6", "Chi"),
        ("L6", "Chi"),
        ("M6", "Số tiền"),
        ("N6", "Chứng từ / HĐ"),
        ("O6", "Link UNC / Telegram"),
        ("P6", "Trạng thái"),
        ("Q6", "Trạng thái")
    ]

    for pos, text in sub_headers:
        cell = ws[pos]
        cell.value = text
        cell.font = font_sub_header
        cell.fill = fill_sub_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Ghi từng dòng dữ liệu
    current_row = 7
    for idx, t in enumerate(transactions):
        r = current_row + idx
        ws[f"A{r}"] = t.trans_date or ""
        ws[f"B{r}"] = t.content or ""
        ws[f"C{r}"] = t.tuan_ton if t.tuan_ton else ""
        ws[f"D{r}"] = t.tuan_thu_cty if t.tuan_thu_cty else ""
        ws[f"E{r}"] = t.tuan_thu_haiban if t.tuan_thu_haiban else ""
        ws[f"F{r}"] = t.tuan_thu_khac if t.tuan_thu_khac else ""
        ws[f"G{r}"] = t.tuan_chi_haiban_cty if t.tuan_chi_haiban_cty else ""
        ws[f"H{r}"] = t.tuan_chi if t.tuan_chi else ""
        ws[f"I{r}"] = t.xuyen_amount if t.xuyen_amount else ""
        ws[f"J{r}"] = t.luong_thu if t.luong_thu else ""
        ws[f"K{r}"] = t.luong_chi if t.luong_chi else ""
        ws[f"L{r}"] = t.truong_amount if t.truong_amount else ""
        ws[f"M{r}"] = t.partner_amount if t.partner_amount else ""
        ws[f"N{r}"] = t.partner_invoice or ""
        ws[f"O{r}"] = t.bill_link or ""
        ws[f"P{r}"] = t.advance_refund or ""
        ws[f"Q{r}"] = t.accounting_status or ""

        # Format số tiền và border
        for col_letter in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"]:
            c = ws[f"{col_letter}{r}"]
            c.font = font_data
            c.border = thin_border
            if idx % 2 == 1:
                c.fill = fill_even
            if col_letter in ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]:
                c.number_format = "#,##0"
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif col_letter in ["A", "P", "Q"]:
                c.alignment = Alignment(horizontal="center", vertical="center")

    # Dòng TỔNG CỘNG
    tot_row = current_row + len(transactions)
    ws[f"B{tot_row}"] = "TỔNG CỘNG"
    ws[f"C{tot_row}"] = monthly.closing_balance if monthly else ""
    ws[f"D{tot_row}"] = monthly.total_company_receipts if monthly else ""
    ws[f"E{tot_row}"] = monthly.total_haiban_receipts if monthly else ""
    ws[f"F{tot_row}"] = monthly.total_other_receipts if monthly else ""
    ws[f"G{tot_row}"] = monthly.total_haiban_to_company if monthly else ""
    ws[f"H{tot_row}"] = monthly.total_advances_spent if monthly else ""
    ws[f"I{tot_row}"] = monthly.total_xuyen if monthly else ""
    ws[f"J{tot_row}"] = monthly.total_luong_thu if monthly else ""
    ws[f"K{tot_row}"] = monthly.total_luong_chi if monthly else ""
    ws[f"L{tot_row}"] = monthly.total_truong if monthly else ""
    ws[f"M{tot_row}"] = monthly.total_partner if monthly else ""

    for col_letter in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"]:
        c = ws[f"{col_letter}{tot_row}"]
        c.font = font_total
        c.fill = fill_total
        c.border = thin_border
        if col_letter in ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]:
            c.number_format = "#,##0"
            c.alignment = Alignment(horizontal="right", vertical="center")

    # Ký tên
    sign_row = tot_row + 3
    ws[f"B{sign_row}"] = "Người lập biểu"
    ws[f"B{sign_row}"].font = Font(name="Arial", size=10, bold=True)
    ws[f"B{sign_row+3}"] = monthly.creator_name if monthly else "Trần Xuân Trường"
    ws[f"B{sign_row+3}"].font = Font(name="Arial", size=10, bold=True)

    # Chỉnh độ rộng cột
    col_widths = {
        'A': 14, 'B': 45, 'C': 15, 'D': 15, 'E': 15, 'F': 15, 'G': 16, 'H': 16,
        'I': 14, 'J': 14, 'K': 14, 'L': 14, 'M': 15, 'N': 25, 'O': 30, 'P': 16, 'Q': 20
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    # Lưu file vào thư mục tạm
    export_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'exports')
    os.makedirs(export_dir, exist_ok=True)
    filename = f"Bang_Ke_Tam_Ung_GIDO_T{month:02d}_{year}.xlsx"
    file_path = os.path.join(export_dir, filename)
    wb.save(file_path)
    return file_path, filename


def add_transaction(data):
    """Thêm một bút toán tạm ứng mới từ web"""
    month = int(data.get('month', 8))
    year = int(data.get('year', 2026))
    
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    if not monthly:
        monthly = CashAdvanceMonthly(month=month, year=year)
        db.session.add(monthly)
        db.session.flush()

    max_idx = db.session.query(db.func.max(CashAdvanceTransaction.row_index)).filter_by(month=month, year=year).scalar() or 0

    trans = CashAdvanceTransaction(
        monthly_id=monthly.id,
        month=month,
        year=year,
        row_index=max_idx + 1,
        trans_date=data.get('trans_date', datetime.utcnow().strftime('%d/%m/%Y')),
        content=data.get('content', '').strip(),
        tuan_ton=clean_amount(data.get('tuan_ton')),
        tuan_thu_cty=clean_amount(data.get('tuan_thu_cty')),
        tuan_thu_haiban=clean_amount(data.get('tuan_thu_haiban')),
        tuan_thu_khac=clean_amount(data.get('tuan_thu_khac')),
        tuan_chi_haiban_cty=clean_amount(data.get('tuan_chi_haiban_cty')),
        tuan_chi=clean_amount(data.get('tuan_chi')),
        xuyen_amount=clean_amount(data.get('xuyen_amount')),
        luong_thu=clean_amount(data.get('luong_thu')),
        luong_chi=clean_amount(data.get('luong_chi')),
        truong_amount=clean_amount(data.get('truong_amount')),
        partner_amount=clean_amount(data.get('partner_amount')),
        partner_invoice=data.get('partner_invoice', '').strip(),
        bill_link=data.get('bill_link', '').strip(),
        advance_refund=data.get('advance_refund', '').strip(),
        accounting_status=data.get('accounting_status', 'Chờ duyệt').strip(),
        is_manual=True
    )
    db.session.add(trans)
    
    # Recalculate totals
    _recalculate_monthly_totals(monthly)
    db.session.commit()
    return trans


def update_transaction(trans_id, data):
    """Cập nhật bút toán tạm ứng"""
    trans = CashAdvanceTransaction.query.get(trans_id)
    if not trans:
        return None
    
    if 'trans_date' in data:
        trans.trans_date = data['trans_date']
    if 'content' in data:
        trans.content = data['content'].strip()
    if 'tuan_thu_cty' in data:
        trans.tuan_thu_cty = clean_amount(data['tuan_thu_cty'])
    if 'tuan_thu_haiban' in data:
        trans.tuan_thu_haiban = clean_amount(data['tuan_thu_haiban'])
    if 'tuan_thu_khac' in data:
        trans.tuan_thu_khac = clean_amount(data['tuan_thu_khac'])
    if 'tuan_chi_haiban_cty' in data:
        trans.tuan_chi_haiban_cty = clean_amount(data['tuan_chi_haiban_cty'])
    if 'tuan_chi' in data:
        trans.tuan_chi = clean_amount(data['tuan_chi'])
    if 'xuyen_amount' in data:
        trans.xuyen_amount = clean_amount(data['xuyen_amount'])
    if 'luong_thu' in data:
        trans.luong_thu = clean_amount(data['luong_thu'])
    if 'luong_chi' in data:
        trans.luong_chi = clean_amount(data['luong_chi'])
    if 'truong_amount' in data:
        trans.truong_amount = clean_amount(data['truong_amount'])
    if 'partner_amount' in data:
        trans.partner_amount = clean_amount(data['partner_amount'])
    if 'partner_invoice' in data:
        trans.partner_invoice = data['partner_invoice'].strip()
    if 'bill_link' in data:
        trans.bill_link = data['bill_link'].strip()
    if 'advance_refund' in data:
        trans.advance_refund = data['advance_refund'].strip()
    if 'accounting_status' in data:
        trans.accounting_status = data['accounting_status'].strip()

    trans.updated_at = datetime.utcnow()
    
    monthly = CashAdvanceMonthly.query.filter_by(month=trans.month, year=trans.year).first()
    if monthly:
        _recalculate_monthly_totals(monthly)

    db.session.commit()
    return trans


def delete_transaction(trans_id):
    """Xóa bút toán tạm ứng"""
    trans = CashAdvanceTransaction.query.get(trans_id)
    if not trans:
        return False
    
    month = trans.month
    year = trans.year
    db.session.delete(trans)
    
    monthly = CashAdvanceMonthly.query.filter_by(month=month, year=year).first()
    if monthly:
        _recalculate_monthly_totals(monthly)

    db.session.commit()
    return True


def _recalculate_monthly_totals(monthly):
    """Tính toán lại các chỉ số tổng hợp trong tháng"""
    all_trans = CashAdvanceTransaction.query.filter_by(month=monthly.month, year=monthly.year).all()
    monthly.total_company_receipts = sum(t.tuan_thu_cty or 0 for t in all_trans)
    monthly.total_haiban_receipts = sum(t.tuan_thu_haiban or 0 for t in all_trans)
    monthly.total_other_receipts = sum(t.tuan_thu_khac or 0 for t in all_trans)
    monthly.total_haiban_to_company = sum(t.tuan_chi_haiban_cty or 0 for t in all_trans)
    monthly.total_advances_spent = sum(t.tuan_chi or 0 for t in all_trans)
    monthly.total_xuyen = sum(t.xuyen_amount or 0 for t in all_trans)
    monthly.total_luong_thu = sum(t.luong_thu or 0 for t in all_trans)
    monthly.total_luong_chi = sum(t.luong_chi or 0 for t in all_trans)
    monthly.total_truong = sum(t.truong_amount or 0 for t in all_trans)
    monthly.total_partner = sum(t.partner_amount or 0 for t in all_trans)
    
    # closing = opening + in - out
    total_in = monthly.total_company_receipts + monthly.total_haiban_receipts + monthly.total_other_receipts
    total_out = abs(monthly.total_advances_spent) + abs(monthly.total_haiban_to_company)
    monthly.closing_balance = monthly.opening_balance + total_in - total_out


def auto_sync_active_months():
    """Tự động đồng bộ các tháng đang hoạt động từ Google Sheets"""
    now = datetime.now()
    cur_month = now.month
    cur_year = now.year
    
    # Đồng bộ tháng hiện tại
    sync_month_from_google(cur_month, cur_year)
    
    # Đồng bộ Tháng 08/2026 nếu dữ liệu chính đang ở tháng 8
    if (cur_month, cur_year) != (8, 2026):
        sync_month_from_google(8, 2026)
    
    # Đồng bộ tháng trước nếu cần
    prev_month = 12 if cur_month == 1 else cur_month - 1
    prev_year = cur_year - 1 if cur_month == 1 else cur_year
    if (prev_month, prev_year) != (8, 2026):
        sync_month_from_google(prev_month, prev_year)


def save_bill_media(media_id, file_bytes, filename='receipt.jpg', mime_type='image/jpeg', tg_file_id=None):
    """
    Lưu trữ file bill vào Supabase:
    1. Nếu có SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY, upload lên Supabase Storage bucket 'advance-bills'
    2. Lưu trực tiếp nội dung base64 vào bảng 'cash_advance_bill_media' trên Supabase PostgreSQL
    3. Trả về public URL truy cập ảnh
    """
    if not media_id:
        media_id = 'gido_' + hex(int(time.time() * 1000))[2:]

    supabase_url = os.environ.get('SUPABASE_URL', 'https://ogkjbdratmgasjtrgjnm.supabase.co').rstrip('/')
    supabase_key = os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_ANON_KEY')
    storage_url = None

    if supabase_key:
        try:
            object_name = f"{media_id}_{filename}"
            upload_url = f"{supabase_url}/storage/v1/object/advance-bills/{urllib.parse.quote(object_name)}"
            headers = {
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}',
                'Content-Type': mime_type or 'image/jpeg',
                'x-upsert': 'true'
            }
            resp = requests.post(upload_url, data=file_bytes, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                storage_url = f"{supabase_url}/storage/v1/object/public/advance-bills/{urllib.parse.quote(object_name)}"
                print(f"[AdvanceService] Uploaded bill to Supabase Storage: {storage_url}")
            else:
                print(f"[AdvanceService] Supabase Storage upload response {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[AdvanceService] Error uploading to Supabase Storage: {e}")

    # Nếu chưa có storage_url từ Supabase Storage, dùng URL trực tiếp của route web
    if not storage_url:
        storage_url = f"/advances/bill/{media_id}"

    # Lưu trữ bản sao dữ liệu trong Supabase PostgreSQL
    b64_data = base64.b64encode(file_bytes).decode('utf-8')
    media = CashAdvanceBillMedia.query.get(media_id)
    if not media:
        media = CashAdvanceBillMedia(
            id=media_id,
            file_id=tg_file_id,
            filename=filename,
            mime_type=mime_type or 'image/jpeg',
            file_size=len(file_bytes),
            data_base64=b64_data,
            storage_url=storage_url
        )
        db.session.add(media)
    else:
        media.filename = filename
        media.mime_type = mime_type or 'image/jpeg'
        media.file_size = len(file_bytes)
        media.data_base64 = b64_data
        if storage_url:
            media.storage_url = storage_url
        if tg_file_id:
            media.file_id = tg_file_id

    db.session.commit()
    return media


def get_bill_media(media_id):
    """
    Lấy thông tin bill từ Supabase.
    Nếu chưa có trong cache DB, tự động đối soát với Google Sheet FileDB và Telegram API.
    """
    if not media_id:
        return None

    # Bỏ tiền tố URL nếu truyền vào cả URL
    if 'start=' in media_id:
        media_id = media_id.split('start=')[-1].split('&')[0]
    elif '/bill/' in media_id:
        media_id = media_id.split('/bill/')[-1].split('?')[0]

    media = CashAdvanceBillMedia.query.get(media_id)
    if media and media.data_base64:
        return media

    # Fallback: Quét tìm trong Google Sheet FileDB
    try:
        token = get_google_access_token()
        if token:
            quoted_title = urllib.parse.quote("FileDB!A2:C100")
            url = f'https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{quoted_title}'
            resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
            if resp.status_code == 200:
                rows = resp.json().get('values', [])
                for row in rows:
                    if len(row) >= 2 and row[0].strip() == media_id:
                        tg_file_id = row[1].strip()
                        file_name = row[2].strip() if len(row) > 2 else 'receipt.jpg'
                        
                        tg_token = os.environ.get('TELEGRAM_BOT_TOKEN') or '8728564714:AAG0UektNi_8qtk1M7Z92iR7INC584J5Sq0'
                        tg_res = requests.get(f'https://api.telegram.org/bot{tg_token}/getFile?file_id={tg_file_id}', timeout=10).json()
                        if tg_res.get('ok'):
                            file_path = tg_res['result']['file_path']
                            file_url = f'https://api.telegram.org/file/bot{tg_token}/{file_path}'
                            dl_res = requests.get(file_url, timeout=15)
                            if dl_res.status_code == 200:
                                mime_type = 'image/jpeg'
                                if file_name.lower().endswith('.png'):
                                    mime_type = 'image/png'
                                elif file_name.lower().endswith('.pdf'):
                                    mime_type = 'application/pdf'
                                return save_bill_media(media_id, dl_res.content, file_name, mime_type, tg_file_id)
    except Exception as e:
        print(f"[AdvanceService] Error lazy-loading bill media {media_id}: {e}")

    return media


def sync_all_bills_from_filedb():
    """Đồng bộ toàn bộ hóa đơn từ tab FileDB của Google Sheet về Supabase"""
    token = get_google_access_token()
    if not token:
        return 0, "Không tìm thấy token Google Sheet"

    try:
        quoted_title = urllib.parse.quote("FileDB!A2:C200")
        url = f'https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{quoted_title}'
        resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=15)
        if resp.status_code != 200:
            return 0, f"Lỗi đọc FileDB: {resp.text}"

        rows = resp.json().get('values', [])
        tg_token = os.environ.get('TELEGRAM_BOT_TOKEN') or '8728564714:AAG0UektNi_8qtk1M7Z92iR7INC584J5Sq0'
        count = 0

        for row in rows:
            if len(row) < 2:
                continue
            short_id = row[0].strip()
            tg_file_id = row[1].strip()
            file_name = row[2].strip() if len(row) > 2 else 'receipt.jpg'

            existing = CashAdvanceBillMedia.query.get(short_id)
            if existing and existing.data_base64:
                continue

            try:
                tg_res = requests.get(f'https://api.telegram.org/bot{tg_token}/getFile?file_id={tg_file_id}', timeout=10).json()
                if tg_res.get('ok'):
                    file_path = tg_res['result']['file_path']
                    file_url = f'https://api.telegram.org/file/bot{tg_token}/{file_path}'
                    dl = requests.get(file_url, timeout=15)
                    if dl.status_code == 200:
                        mime_type = 'image/jpeg'
                        if file_name.lower().endswith('.png'):
                            mime_type = 'image/png'
                        elif file_name.lower().endswith('.pdf'):
                            mime_type = 'application/pdf'
                        save_bill_media(short_id, dl.content, file_name, mime_type, tg_file_id)
                        count += 1
            except Exception as item_err:
                print(f"[AdvanceService] Error migrating {short_id}: {item_err}")

        return count, None
    except Exception as e:
        return 0, str(e)


