import os
import re
import json
import time
import html
import requests
import unicodedata
from datetime import datetime

from app.extensions import db
from app.models import CashAdvanceMonthly, CashAdvanceTransaction, CashAdvanceBillMedia
from app.services.advance_service import (
    GIDO_SPREADSHEET_ID,
    get_google_access_token,
    save_bill_media,
    sync_month_from_google,
    clean_amount
)

CASHFLOW_BOT_TOKEN = os.environ.get('CASHFLOW_BOT_TOKEN') or '8728564714:AAG0UektNi_8qtk1M7Z92iR7INC584J5Sq0'
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

def get_gemini_api_key():
    key = os.environ.get('GEMINI_API_KEY') or GEMINI_API_KEY
    if not key:
        from flask import current_app
        try:
            key = current_app.config.get('GEMINI_API_KEY', '')
        except Exception:
            pass
    return key

ALLOWED_CHAT_IDS = [
    cid.strip() for cid in (os.environ.get('ALLOWED_CHAT_IDS') or os.environ.get('ALLOWED_CHAT_ID', '')).split(',')
    if cid.strip()
]

def get_allowed_chat_ids():
    import app.services.cashflow_bot_service as cbs
    if getattr(cbs, 'ALLOWED_CHAT_IDS', None):
        return [str(c).strip() for c in cbs.ALLOWED_CHAT_IDS if str(c).strip()]
    raw = os.environ.get('ALLOWED_CHAT_IDS') or os.environ.get('ALLOWED_CHAT_ID', '')
    if not raw:
        from flask import current_app
        try:
            raw = current_app.config.get('ALLOWED_CHAT_IDS', '') or current_app.config.get('ALLOWED_CHAT_ID', '')
        except Exception:
            pass
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()]
    return [c.strip() for c in str(raw).split(',') if c.strip()]

# Cache lưu trữ các giao dịch đang chờ bấm nút Xác nhận
_pending_confirmations = {}

def normalize_string(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFD', str(text))
    text = re.sub(r'[\u0300-\u036f]', '', text)
    return text.replace('đ', 'd').replace('Đ', 'D').lower().strip()

def is_total_label(text):
    norm = normalize_string(text).rstrip(':-').strip()
    return norm in ('tong', 'tong cong', 'tong tam tinh')

def format_money_vn(val):
    try:
        n = float(val)
        return f"{n:,.0f}".replace(',', '.')
    except Exception:
        return '0'

def send_telegram_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    url = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': str(chat_id),
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if reply_to_message_id:
        payload['reply_to_message_id'] = reply_to_message_id
    try:
        r = requests.post(url, json=payload, timeout=10)
        res = r.json()
        if not res.get('ok'):
            print(f"[CashflowBot] HTML send failed: {res}, retrying with plain text...")
            payload.pop('parse_mode', None)
            clean_text = re.sub(r'<[^>]+>', '', text)
            payload['text'] = clean_text
            r2 = requests.post(url, json=payload, timeout=10)
            return r2.json()
        return res
    except Exception as e:
        print(f"[CashflowBot] Error sending Telegram message: {e}")
        return None

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/answerCallbackQuery"
    payload = {'callback_query_id': callback_query_id}
    if text:
        payload['text'] = text
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception:
        pass

def delete_telegram_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/deleteMessage"
    try:
        requests.post(url, json={'chat_id': str(chat_id), 'message_id': message_id}, timeout=8)
    except Exception:
        pass

def edit_message_reply_markup(chat_id, message_id):
    url = f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/editMessageReplyMarkup"
    try:
        requests.post(url, json={'chat_id': str(chat_id), 'message_id': message_id, 'reply_markup': {'inline_keyboard': []}}, timeout=8)
    except Exception:
        pass

def get_monthly_sheet_name(date_text=None, now=None):
    if now is None:
        now = datetime.now()
    month_aliases = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    month = now.month
    year = now.year
    text = (date_text or '').strip().lower()
    named_m = re.search(r'(?:^|[-\/\s])(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:[-\/\s]|$)', text)
    num_m = re.search(r'\b\d{1,2}[\/-](\d{1,2})(?:[\/-](\d{4}))?\b', text)
    if named_m:
        month = month_aliases.get(named_m.group(1), month)
    elif num_m:
        try:
            month = int(num_m.group(1))
            if num_m.group(2):
                year = int(num_m.group(2))
        except Exception:
            pass
    explicit_year = re.search(r'\b(20\d{2})\b', text)
    if explicit_year:
        year = int(explicit_year.group(1))

    return f"Tháng {month:02d}-{year}", month, year

def extract_receipt_with_gemini(image_b64, mime_type='image/jpeg'):
    """Gọi Gemini 2.5 Flash để bóc tách thông tin biên lai chuyển khoản"""
    prompt = """
Bạn là Kế toán AI của GIDO Logistics. Phân tích biên lai ngân hàng hoặc tài liệu này.
Trích xuất thông tin trả về CHUẨN JSON như sau:
{
  "loai": "THU" hoặc "CHI",
  "so_tien": <số tiền nguyên dương, ví dụ: 15000000>,
  "nguoi_giao_dich": "<tên người gửi nếu THU, nhận nếu CHI>",
  "noi_dung": "<nội dung chuyển khoản>",
  "nhan_vien": "<LƯƠNG hoặc XUYÊN hoặc TRƯỜNG hoặc ĐỐI TÁC KHÁC hoặc null>",
  "nguon_thu": "<CÔNG TY hoặc HẢI BÂN hoặc THU KHÁC>",
  "ngay_giao_dich": "<ngày giao dịch trên bill, format d-MMM ví dụ: 17-May. Nếu không đọc được thì null>"
}
Lưu ý RẤT QUAN TRỌNG:
- Báo cáo này là dòng tiền của sếp NGUYỄN SƠN TUẤN.
- Nếu người NHẬN tiền là Nguyễn Sơn Tuấn (hoặc Tuấn), thì loại giao dịch bắt buộc là "THU".
- Nếu người GỬI tiền là Nguyễn Sơn Tuấn, thì loại giao dịch là "CHI".
- Về "nhan_vien": Nếu nhắc tới "Lương", "Xuyên", "Trường", điền tên tương ứng IN HOA. Nếu nhắc tới đối tác ngoài (nhà xe, mua đồ...), điền "ĐỐI TÁC KHÁC".
- Về "nguon_thu": (Chỉ dùng nếu là THU). Xác định tiền từ CÔNG TY, hay HẢI BÂN. (Nếu người gửi là "CTY CP DVTM XUYEN BIEN GIOI GIC" hoặc có chữ "GIC", đó chính là CÔNG TY).
- Về "ngay_giao_dich": Đọc ngày giao dịch trên bill (thường là ngày chuyển khoản). Format: d-MMM (ví dụ: 5-May, 31-Aug).
- KHÔNG BAO GỒM mã markdown, chỉ trả về JSON thuần.
"""
    api_key = get_gemini_api_key()
    if not api_key:
        raise Exception("GEMINI_API_KEY chưa được cấu hình")

    models_to_try = ['gemini-flash-latest', 'gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.0-flash']
    last_err = None

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": image_b64
                    }
                }
            ]
        }]
    }

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                raw_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                cleaned = raw_text.replace('```json', '').replace('```', '').strip()
                return json.loads(cleaned)
            else:
                last_err = f"{resp.status_code} - {resp.text}"
                print(f"[CashflowBot] Model {model} failed: {last_err}, trying next...")
        except Exception as e:
            last_err = str(e)
            print(f"[CashflowBot] Model {model} error: {e}, trying next...")

    raise Exception(f"Gemini API lỗi trên tất cả các models: {last_err}")

def detect_columns(token, sheet_name):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{sheet_name}!A4:O6"
    resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    rows = resp.json().get('values', [])
    if len(rows) < 2:
        return None
    header = rows[0]
    sub_header = rows[1] if len(rows) > 1 else []
    if 'luong' not in normalize_string(''.join(header)) and len(rows) > 2:
        header = rows[1]
        sub_header = rows[2]

    cols = {'max_col': max(len(header), len(sub_header), 15)}
    xuyen_idx = -1
    for j, h in enumerate(header):
        nh = normalize_string(h)
        if 'ngay' in nh: cols['ngay'] = j
        if 'thang' in nh: cols['thang'] = j
        if 'noi dung' in nh: cols['noi_dung'] = j
        if 'tuan' in nh and 'tuan_start' not in cols: cols['tuan_start'] = j
        if 'xuyen' in nh: cols['xuyen'] = j; xuyen_idx = j
        if 'luong' in nh: cols['luong_start'] = j
        if 'truong' in nh: cols['truong'] = j
        if ('doi tac' in nh or 'doi tac khac' in nh) and 'hoa don' not in nh: cols['doi_tac'] = j
        if 'hoa don' in nh: cols['hoa_don'] = j
        if 'link bill' in nh or 'bill' in nh: cols['link_bill'] = j

    tuan_end = xuyen_idx if xuyen_idx != -1 else len(sub_header)
    for j in range(cols.get('tuan_start', 0), tuan_end):
        if j >= len(sub_header): break
        nsh = normalize_string(sub_header[j])
        if 'thu' in nsh and 'cong ty' in nsh: cols['thu_cty'] = j
        elif 'thu' in nsh and 'hai ban' in nsh: cols['thu_hb'] = j
        elif 'thu khac' in nsh: cols['thu_khac'] = j
        elif 'chi' in nsh and 'hai ban' in nsh: cols['chi_hb'] = j
        elif nsh == 'chi': cols['tuan_chi'] = j

    if 'luong_start' in cols:
        luong_end = cols.get('truong', cols.get('doi_tac', len(sub_header)))
        for j in range(cols['luong_start'], luong_end):
            if j >= len(sub_header): break
            nsh = normalize_string(sub_header[j])
            if 'thu' in nsh: cols['luong_thu'] = j
            if nsh == 'chi': cols['luong_chi'] = j

    return cols

def append_transaction_to_sheet(data, public_img_url):
    """Chèn dòng mới vào Google Sheet và cập nhật giá trị"""
    token = get_google_access_token()
    if not token:
        raise Exception("Không thể kết nối Google Sheets (Thiếu token)")

    sheet_name, month, year = get_monthly_sheet_name(data.get('ngay_giao_dich'))

    # 1. Lấy sheet metadata để tìm sheetId
    meta_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}?fields=sheets.properties"
    m_resp = requests.get(meta_url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    sheets_list = m_resp.json().get('sheets', [])
    target_sheet = next((s['properties'] for s in sheets_list if s['properties']['title'] == sheet_name), None)
    if not target_sheet:
        raise Exception(f"Không tìm thấy sheet '{sheet_name}' trong Google Sheet.")
    sheet_id = target_sheet['sheetId']

    # 2. Tìm dòng TỔNG
    val_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{sheet_name}!A:B"
    v_resp = requests.get(val_url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    rows = v_resp.json().get('values', [])
    
    tong_index = -1
    for i, r in enumerate(rows):
        cA = normalize_string(r[0] if len(r) > 0 else '')
        cB = normalize_string(r[1] if len(r) > 1 else '')
        if is_total_label(cA) or is_total_label(cB):
            tong_index = i
            break
            
    if tong_index == -1:
        raise Exception(f"Không tìm thấy dòng TỔNG trong sheet {sheet_name} để chèn dữ liệu.")

    # Tìm dòng có dữ liệu cuối cùng trước dòng TỔNG
    last_filled = tong_index - 1
    while last_filled >= 0:
        cA = (rows[last_filled][0] if len(rows[last_filled]) > 0 else '').strip()
        cB = (rows[last_filled][1] if len(rows[last_filled]) > 1 else '').strip()
        if cA != '' or cB != '':
            break
        last_filled -= 1
    insert_index = last_filled + 1

    # 3. Chèn dòng trống trước dòng TỔNG
    batch_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}:batchUpdate"
    insert_body = {
        "requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": insert_index,
                    "endIndex": insert_index + 1
                },
                "inheritFromBefore": True
            }
        }]
    }
    requests.post(batch_url, json=insert_body, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    row_a1 = insert_index + 1

    # 4. Xác định các cột và chuẩn bị dữ liệu
    cols = detect_columns(token, sheet_name) or {}
    max_c = max(cols.get('max_col', 15), 15)
    row_data = [""] * max_c

    now = datetime.now()
    fallback_date = now.strftime('%d-%b')
    date_str = data.get('ngay_giao_dich') or fallback_date
    thang_str = f"Tháng {month:02d}/{year}"

    idx_ngay = cols.get('ngay', 0)
    idx_thang = cols.get('thang', -1)
    idx_noi_dung = cols.get('noi_dung', 1)

    row_data[idx_ngay] = date_str
    if idx_thang != -1:
        row_data[idx_thang] = thang_str
    row_data[idx_noi_dung] = f"{data.get('noi_dung', '')} - {data.get('nguoi_giao_dich', '')}"

    so_tien = float(data.get('so_tien', 0))
    loai = data.get('loai', 'CHI')
    nhan_vien = data.get('nhan_vien')
    nguon_thu = data.get('nguon_thu')

    if loai == 'THU':
        if nguon_thu == 'CÔNG TY' and 'thu_cty' in cols: row_data[cols['thu_cty']] = so_tien
        elif nguon_thu == 'HẢI BÂN' and 'thu_hb' in cols: row_data[cols['thu_hb']] = so_tien
        elif 'thu_khac' in cols: row_data[cols['thu_khac']] = so_tien
        
        if nhan_vien == 'LƯƠNG' and 'luong_thu' in cols: row_data[cols['luong_thu']] = -so_tien
        elif nhan_vien == 'XUYÊN' and 'xuyen' in cols: row_data[cols['xuyen']] = -so_tien
        elif nhan_vien == 'TRƯỜNG' and 'truong' in cols: row_data[cols['truong']] = -so_tien
        elif nhan_vien == 'ĐỐI TÁC KHÁC' and 'doi_tac' in cols: row_data[cols['doi_tac']] = -so_tien
    else:
        if 'tuan_chi' in cols: row_data[cols['tuan_chi']] = -so_tien
        if nhan_vien == 'LƯƠNG' and 'luong_thu' in cols: row_data[cols['luong_thu']] = so_tien
        elif nhan_vien == 'XUYÊN' and 'xuyen' in cols: row_data[cols['xuyen']] = so_tien
        elif nhan_vien == 'TRƯỜNG' and 'truong' in cols: row_data[cols['truong']] = so_tien
        elif nhan_vien == 'ĐỐI TÁC KHÁC' and 'doi_tac' in cols: row_data[cols['doi_tac']] = so_tien

    idx_bill = cols.get('link_bill', 14)
    if idx_bill < len(row_data):
        row_data[idx_bill] = public_img_url

    # 5. Ghi dòng dữ liệu
    col_letter = chr(64 + len(row_data))
    update_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{sheet_name}!A{row_a1}:{col_letter}{row_a1}?valueInputOption=USER_ENTERED"
    requests.put(update_url, json={'values': [row_data]}, headers={'Authorization': f'Bearer {token}'}, timeout=10)

    # 6. Ghi Audit Log vào sheet Nhật ký
    try:
        log_time = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
        log_row = [log_time, 'Thêm Giao Dịch', loai, str(int(so_tien)), data.get('nguoi_giao_dich', ''), public_img_url]
        requests.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/Nhật ký!A:F:append?valueInputOption=USER_ENTERED",
            json={'values': [log_row]},
            headers={'Authorization': f'Bearer {token}'},
            timeout=8
        )
    except Exception as e:
        print(f"[CashflowBot] Error writing audit log: {e}")

    # Đồng bộ sang Sổ Lương nếu nhân viên là LƯƠNG và loại CHI
    if nhan_vien == 'LƯƠNG' and loai == 'CHI':
        try:
            append_transaction_to_luong_sheet(token, data, public_img_url, date_str)
        except Exception as e:
            print(f"[CashflowBot] Error syncing to Luong sheet: {e}")

    return sheet_name, row_a1, month, year

def append_transaction_to_luong_sheet(token, data, public_img_url, date_str):
    spreadsheet_id = '1u4mYe_3vWDXlNPABZpy9doLmWX06r1dHNSnXXbKbwNA'
    meta_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=sheets.properties"
    m_resp = requests.get(meta_url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    sheets_list = m_resp.json().get('sheets', [])
    target_sheet = next((s['properties'] for s in sheets_list if s['properties']['title'] == 'Lương'), None)
    if not target_sheet:
        return
    sheet_id = target_sheet['sheetId']

    val_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Lương!A:B"
    v_resp = requests.get(val_url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    rows = v_resp.json().get('values', [])
    
    tong_index = -1
    for i, r in enumerate(rows):
        cA = normalize_string(r[0] if len(r) > 0 else '')
        cB = normalize_string(r[1] if len(r) > 1 else '')
        if is_total_label(cA) or is_total_label(cB):
            tong_index = i
            break
            
    if tong_index == -1:
        tong_index = len(rows)

    last_filled = tong_index - 1
    while last_filled >= 0:
        cA = (rows[last_filled][0] if len(rows[last_filled]) > 0 else '').strip()
        cB = (rows[last_filled][1] if len(rows[last_filled]) > 1 else '').strip()
        if cA != '' or cB != '':
            break
        last_filled -= 1
    insert_index = last_filled + 1

    batch_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
    insert_body = {
        "requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": insert_index,
                    "endIndex": insert_index + 1
                },
                "inheritFromBefore": True
            }
        }]
    }
    requests.post(batch_url, json=insert_body, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    row_a1 = insert_index + 1

    row_data = [""] * 11
    row_data[0] = date_str
    row_data[1] = f"{data.get('noi_dung', '')} - {data.get('nguoi_giao_dich', '')}"
    row_data[3] = float(data.get('so_tien', 0))
    row_data[5] = float(data.get('so_tien', 0))
    row_data[10] = public_img_url

    update_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Lương!A{row_a1}:K{row_a1}?valueInputOption=USER_ENTERED"
    requests.put(update_url, json={'values': [row_data]}, headers={'Authorization': f'Bearer {token}'}, timeout=10)

def handle_telegram_update(update):
    """
    Xử lý webhook update gửi tới từ Telegram:
    - Nhận diện tin nhắn gửi ảnh/file biên lai
    - Phân tích bằng Gemini AI
    - Xử lý các callback nút bấm xác nhận/hủy bỏ
    """
    if not update:
        return {'ok': True}

    # 1. Xử lý Callback Query (khi người dùng bấm nút Xác nhận / Hủy)
    if 'callback_query' in update:
        cq = update['callback_query']
        cq_id = cq['id']
        chat_id = str(cq['message']['chat']['id'])
        msg_id = cq['message']['message_id']
        cb_data = cq.get('data', '')

        # Kiểm tra danh sách chat được phép
        allowed_chats = get_allowed_chat_ids()
        is_prod = os.getenv('FLASK_ENV') == 'production' or os.getenv('ENVIRONMENT') == 'production' or bool(os.getenv('RENDER'))
        if is_prod and not allowed_chats:
            answer_callback_query(cq_id, "Lỗi bảo mật: ALLOWED_CHAT_IDS chưa được cấu hình.")
            return {'ok': True}
        if allowed_chats and chat_id not in allowed_chats:
            answer_callback_query(cq_id, "Bạn không có quyền thực hiện thao tác này.")
            return {'ok': True}

        answer_callback_query(cq_id)
        edit_message_reply_markup(chat_id, msg_id)

        if cb_data.startswith('confirmtx_'):
            confirm_id = cb_data.split('confirmtx_')[1]
            pending = _pending_confirmations.get(confirm_id)
            if not pending:
                send_telegram_message(chat_id, "⏳ Phiên xác nhận đã hết hạn. Vui lòng gửi lại ảnh hóa đơn.")
                return {'ok': True}

            # Xác thực người bấm nút phải thuộc cùng chat_id khởi tạo giao dịch
            if str(pending.get('chat_id')) != str(chat_id):
                send_telegram_message(chat_id, "❌ Lỗi bảo mật: Bạn không có quyền xác nhận giao dịch khởi tạo từ cuộc trò chuyện khác.")
                return {'ok': True}

            load_msg = send_telegram_message(chat_id, "⏳ Đang lưu ảnh lên Supabase và ghi vào Sổ quỹ...")
            try:
                # Ghi vào Google Sheet
                sheet_name, row_a1, month, year = append_transaction_to_sheet(pending['data'], pending['public_url'])

                # Tự động đồng bộ tháng vừa cập nhật vào cơ sở dữ liệu Supabase của Render
                try:
                    sync_month_from_google(month, year)
                except Exception as sync_err:
                    print(f"[CashflowBot] Auto-sync error: {sync_err}")

                d = pending['data']
                text_ok = (
                    f"✅ <b>ĐÃ GHI THÀNH CÔNG VÀO SỔ QUỸ & SUPABASE!</b>\n\n"
                    f"💳 <b>Loại:</b> {html.escape(str(d.get('loai') or ''))}\n"
                    f"💰 <b>Số tiền:</b> {format_money_vn(d.get('so_tien'))} VNĐ\n"
                    f"👤 <b>Giao dịch:</b> {html.escape(str(d.get('nguoi_giao_dich') or ''))}\n"
                    f"📂 <b>Sheet:</b> {html.escape(str(sheet_name))} (Dòng {row_a1})\n"
                    f"📸 <b>Ảnh bill:</b> Đã lưu an toàn lên Supabase"
                )
                send_telegram_message(chat_id, text_ok)
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Lỗi ghi sổ: {html.escape(str(e))}")
            finally:
                _pending_confirmations.pop(confirm_id, None)
                if load_msg and 'result' in load_msg:
                    delete_telegram_message(chat_id, load_msg['result']['message_id'])

        elif cb_data.startswith('canceltx_'):
            confirm_id = cb_data.split('canceltx_')[1]
            pending = _pending_confirmations.get(confirm_id)
            if pending and str(pending.get('chat_id')) != str(chat_id):
                send_telegram_message(chat_id, "❌ Lỗi bảo mật: Bạn không có quyền hủy giao dịch từ cuộc trò chuyện khác.")
                return {'ok': True}
            _pending_confirmations.pop(confirm_id, None)
            send_telegram_message(chat_id, "🚫 Đã hủy. Giao dịch KHÔNG được ghi vào Sổ quỹ.")

        return {'ok': True}

    # 2. Xử lý Message
    if 'message' in update:
        msg = update['message']
        chat_id = str(msg['chat']['id'])
        msg_id = msg['message_id']
        text = (msg.get('text') or '').strip()
        chat_type = msg.get('chat', {}).get('type', 'private')
        print(f"[CashflowBot] Nhận tin nhắn từ chat_id={chat_id} ({chat_type}), text={text[:50] if text else ''}")

        # /id is a safe discovery command and must remain available before
        # whitelist enforcement, so an administrator can add a new chat ID.
        # It only returns Telegram metadata and performs no financial action.
        command = text.split(maxsplit=1)[0].lower() if text else ''
        if command == '/id' or command.startswith('/id@'):
            send_telegram_message(
                chat_id,
                f"Chat ID hiện tại: <code>{html.escape(chat_id)}</code>\n"
                f"Chat type: <code>{html.escape(str(chat_type))}</code>",
                reply_to_message_id=msg_id
            )
            return {'ok': True}

        # Kiểm tra phân quyền chat: Bắt buộc trong production hoặc khi ALLOWED_CHAT_IDS được cấu hình
        allowed_chats = get_allowed_chat_ids()
        is_prod = os.getenv('FLASK_ENV') == 'production' or os.getenv('ENVIRONMENT') == 'production' or bool(os.getenv('RENDER'))
        if is_prod and not allowed_chats:
            print("[CashflowBot Security] Bỏ qua: Production yêu cầu ALLOWED_CHAT_IDS nhưng danh sách đang rỗng.")
            return {'ok': True}

        def _is_chat_authorized(c_id):
            if not allowed_chats:
                return True
            s = str(c_id).strip()
            if s in allowed_chats:
                return True
            if s.startswith('-100') and ('-' + s[4:]) in allowed_chats:
                return True
            if s.startswith('-') and not s.startswith('-100') and ('-100' + s[1:]) in allowed_chats:
                return True
            return False

        if allowed_chats and not _is_chat_authorized(chat_id) and not _is_chat_authorized(msg.get('chat', {}).get('id')):
            print(f"[CashflowBot Security] Bỏ qua tin nhắn từ chat không nằm trong ALLOWED_CHAT_IDS: {chat_id}")
            return {'ok': True}

        # Nếu là lệnh báo cáo
        if text.lower() in ('/bc', 'báo cáo', 'bc', '📊 nhận báo cáo tiền gido'):
            now = datetime.now()
            sheet_name, m, y = get_monthly_sheet_name()
            # Đọc dòng tổng từ Google Sheet hoặc database
            monthly = CashAdvanceMonthly.query.filter_by(month=m, year=y).first()
            if monthly:
                report_text = (
                    f"📊 <b>BÁO CÁO DÒNG TIỀN GIDO ({html.escape(str(sheet_name))})</b>\n"
                    f"📅 Ngày: {now.strftime('%d/%m/%Y %H:%M')}\n\n"
                    f"💰 <b>TỒN QUỸ HIỆN TẠI:</b> {format_money_vn(monthly.closing_balance)} VNĐ\n\n"
                    f"📥 <b>Tổng thu:</b> +{format_money_vn(monthly.total_company_receipts + monthly.total_haiban_receipts + monthly.total_other_receipts)} VNĐ\n"
                    f"📤 <b>Tổng chi:</b> -{format_money_vn(monthly.total_advances_spent + monthly.total_haiban_to_company)} VNĐ\n\n"
                    f"👥 <b>TIỀN NHÂN VIÊN ĐANG GIỮ:</b>\n"
                    f"• Lương: {format_money_vn(monthly.total_luong_thu - monthly.total_luong_chi)} VNĐ\n"
                    f"• Xuyên: {format_money_vn(monthly.total_xuyen)} VNĐ\n"
                    f"• Trường: {format_money_vn(monthly.total_truong)} VNĐ\n"
                    f"• Đối tác khác: {format_money_vn(monthly.total_partner)} VNĐ\n\n"
                    f"👉 <i>Xem chi tiết và ảnh biên lai tại Dashboard GIC Logistics</i>"
                )
            else:
                report_text = f"📊 Chưa có dữ liệu tổng kết cho {html.escape(str(sheet_name))}. Vui lòng đồng bộ trên Dashboard."
            send_telegram_message(chat_id, report_text, reply_to_message_id=msg_id)
            return {'ok': True}

        # Nếu là gửi ảnh hoặc file tài liệu (biên lai chuyển khoản)
        file_id = None
        file_name = 'receipt.jpg'
        mime_type = 'image/jpeg'

        if msg.get('photo'):
            # Lấy ảnh độ phân giải cao nhất
            photo_arr = msg['photo']
            file_id = photo_arr[-1]['file_id']
        elif msg.get('document'):
            doc = msg['document']
            doc_mime = doc.get('mime_type', '')
            doc_name = doc.get('file_name', '')
            if doc_mime.startswith('image/') or doc_name.lower().endswith(('.jpg', '.jpeg', '.png', '.pdf')):
                file_id = doc['file_id']
                file_name = doc_name or 'receipt.pdf'
                mime_type = doc_mime or ('application/pdf' if file_name.endswith('.pdf') else 'image/jpeg')

        if file_id:
            load_msg = send_telegram_message(chat_id, "⏳ Mắt thần AI đang đọc biên lai ngân hàng, sếp đợi 5 giây...", reply_to_message_id=msg_id)
            try:
                # 1. Tải file từ Telegram API
                get_f_res = requests.get(f"https://api.telegram.org/bot{CASHFLOW_BOT_TOKEN}/getFile?file_id={file_id}", timeout=10).json()
                if not get_f_res.get('ok'):
                    raise Exception("Không thể lấy đường dẫn file từ Telegram.")

                f_path = get_f_res['result']['file_path']
                f_url = f"https://api.telegram.org/file/bot{CASHFLOW_BOT_TOKEN}/{f_path}"
                dl_res = requests.get(f_url, timeout=20)
                if dl_res.status_code != 200:
                    raise Exception("Không thể tải file nhị phân từ Telegram.")

                image_bytes = dl_res.content
                import base64
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')

                # 2. Phân tích với Gemini AI
                ai_data = extract_receipt_with_gemini(image_b64, mime_type)

                # 3. Tạo mã định danh và lưu trữ ảnh ngay lập tức vào Supabase
                short_id = 'gido_' + hex(int(time.time() * 1000))[2:]
                media = save_bill_media(short_id, image_bytes, file_name, mime_type, file_id)

                # 4. Xác định URL nội bộ cho bill (tuyệt đối không dùng public bucket link)
                render_host = os.environ.get('RENDER_EXTERNAL_URL') or 'https://gic-logistics.onrender.com'
                internal_bill_url = f"{render_host.rstrip('/')}/advances/bill/{short_id}"

                confirm_id = short_id
                _pending_confirmations[confirm_id] = {
                    'data': ai_data,
                    'media_id': short_id,
                    'public_url': internal_bill_url,
                    'chat_id': chat_id
                }

                date_label = html.escape(str(ai_data.get('ngay_giao_dich') or 'Hôm nay'))
                so_tien_label = format_money_vn(ai_data.get('so_tien', 0))
                loai_label = html.escape(str(ai_data.get('loai') or 'CHI'))
                nguoi_label = html.escape(str(ai_data.get('nguoi_giao_dich') or 'Không rõ'))
                category_label = html.escape(str(ai_data.get('nhan_vien') or ai_data.get('nguon_thu') or 'Chi phí ngoài'))
                noi_dung_label = html.escape(str(ai_data.get('noi_dung') or ''))

                summary_text = (
                    f"🔍 <b>AI đã đọc biên lai:</b>\n\n"
                    f"📅 <b>Ngày:</b> {date_label}\n"
                    f"💳 <b>Loại:</b> {loai_label}\n"
                    f"💰 <b>Số tiền:</b> {so_tien_label} VNĐ\n"
                    f"👤 <b>Giao dịch:</b> {nguoi_label}\n"
                    f"🕵️ <b>Phân loại:</b> {category_label}\n"
                    f"📝 <b>Nội dung:</b> {noi_dung_label}\n\n"
                    f"👇 <i>Xác nhận ghi vào Sổ quỹ & Google Sheet?</i>"
                )

                reply_markup = {
                    'inline_keyboard': [
                        [{'text': '✅ Xác nhận ghi sổ', 'callback_data': f'confirmtx_{confirm_id}'}],
                        [{'text': '❌ Hủy bỏ', 'callback_data': f'canceltx_{confirm_id}'}]
                    ]
                }

                send_telegram_message(chat_id, summary_text, reply_markup=reply_markup, reply_to_message_id=msg_id)

            except Exception as err:
                print(f"[CashflowBot] Error processing receipt: {err}")
                send_telegram_message(chat_id, f"❌ Lỗi xử lý hóa đơn: {html.escape(str(err))}", reply_to_message_id=msg_id)
            finally:
                if load_msg and 'result' in load_msg:
                    delete_telegram_message(chat_id, load_msg['result']['message_id'])

        elif text in ('/start', '/help', 'menu', '/bd'):
            welcome = (
                f"👋 Chào sếp! Em là <b>Bot Theo Dõi Dòng Tiền GIDO</b>.\n\n"
                f"📸 Sếp chỉ cần <b>gửi ảnh bill chuyển khoản ngân hàng</b> vào đây, AI sẽ tự động đọc tiền, phân loại và lưu ảnh lên <b>Supabase</b>!\n\n"
                f"👉 Gõ <code>/bc</code> để xem tổng quan tồn quỹ và tiền nhân viên đang giữ."
            )
            send_telegram_message(chat_id, welcome, reply_to_message_id=msg_id)

    return {'ok': True}
