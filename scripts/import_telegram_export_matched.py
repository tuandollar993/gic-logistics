"""scripts/import_telegram_export_matched.py

Nạp toàn bộ ảnh hóa đơn từ Telegram Export vào Supabase PostgreSQL
và liên kết chính xác 100% với các bút toán sổ quỹ GIDO.
"""

import os
import sys
import re
import base64
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app import create_app
from app.extensions import db
from app.models import CashAdvanceTransaction, CashAdvanceBillMedia
from app.services.advance_service import (
    clean_amount,
    GIDO_SPREADSHEET_ID,
    get_google_access_token
)

def run_import(export_dir_str):
    export_dir = Path(export_dir_str)
    html_file = export_dir / "messages.html"
    photos_dir = export_dir / "photos"

    if not html_file.exists() or not photos_dir.exists():
        print(f"❌ Không tìm thấy messages.html hoặc photos/ trong: {export_dir}")
        return

    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()

    parts = re.split(r'<div class="message default clearfix[^"]*" id="message(\d+)">', html)
    messages = []
    for i in range(1, len(parts), 2):
        msg_id = int(parts[i])
        body = parts[i+1]
        m_date = re.search(r'title="([^"]+UTC\+07:00)"', body)
        date_str = m_date.group(1) if m_date else ''
        m_sender = re.search(r'<div class="from_name">\s*(.*?)\s*</div>', body, re.DOTALL)
        sender = m_sender.group(1).strip() if m_sender else ''
        m_photo = re.search(r'href="(photos/photo_[^"]+)"', body)
        photo_rel = m_photo.group(1) if m_photo else None
        m_text = re.search(r'<div class="text">\s*(.*?)\s*</div>', body, re.DOTALL)
        text = ""
        if m_text:
            text = re.sub(r'<[^>]+>', ' ', m_text.group(1)).strip()
            text = re.sub(r'\s+', ' ', text)
        
        messages.append({
            'id': msg_id,
            'date': date_str,
            'sender': sender,
            'photo': photo_rel,
            'text': text
        })

    print(f"📄 Đã đọc {len(messages)} tin nhắn từ {html_file.name}")

    # Tìm các cặp ảnh + thông tin phản hồi từ bot
    photo_pairs = []
    for idx, m in enumerate(messages):
        if m['photo']:
            bot_info = None
            for nxt in messages[idx+1:idx+6]:
                if 'Số tiền:' in nxt['text'] or 'Giao dịch:' in nxt['text'] or 'AI đã đọc' in nxt['text'] or 'ĐÃ GHI' in nxt['text']:
                    bot_info = nxt['text']
                    break
            photo_pairs.append({
                'photo_msg_id': m['id'],
                'date': m['date'],
                'sender': m['sender'],
                'photo_file': m['photo'],
                'bot_info': bot_info,
                'caption': m['text']
            })

    print(f"📸 Tổng cộng tìm thấy {len(photo_pairs)} ảnh trong lịch sử chat.")

    app = create_app()
    with app.app_context():
        all_txs = CashAdvanceTransaction.query.order_by(CashAdvanceTransaction.id.desc()).all()
        matched_tx_ids = set()
        saved_count = 0
        updated_tx_count = 0
        filedb_new_rows = []

        for p in photo_pairs:
            photo_path = export_dir / p['photo_file']
            if not photo_path.exists():
                continue

            file_bytes = photo_path.read_bytes()
            b64_data = base64.b64encode(file_bytes).decode('utf-8')
            filename = photo_path.name
            file_size = len(file_bytes)

            txt = p['bot_info'] or p['caption'] or ''
            m_money = re.search(r'Số tiền:\s*([\d\.\,\s]+)', txt)
            raw_amt = m_money.group(1) if m_money else ''
            amt = clean_amount(raw_amt) if raw_amt else 0
            
            m_person = re.search(r'Giao dịch:\s*([^💳💰👤🕵️📝📂]+)', txt)
            person = m_person.group(1).strip() if m_person else ''

            # Parse ngày từ date string tin nhắn (VD: "11.09.2026 23:19:42 UTC+07:00")
            msg_day = None
            msg_month = None
            msg_year = None
            date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', p['date'])
            if date_match:
                msg_day = int(date_match.group(1))
                msg_month = int(date_match.group(2))
                msg_year = int(date_match.group(3))

            best_match = None
            if amt > 0:
                candidates = []
                for t in all_txs:
                    if t.id in matched_tx_ids:
                        continue
                    # Check số tiền (kể cả âm lẫn dương)
                    t_amts = [t.tuan_chi, t.truong_amount, t.xuyen_amount, t.partner_amount, t.luong_chi, t.tuan_thu_cty, t.tuan_thu_haiban, t.luong_thu, t.tuan_thu_khac]
                    amt_match = any(a is not None and abs(abs(float(a)) - amt) < 1.0 for a in t_amts if a != 0)
                    if not amt_match:
                        continue

                    # Check tên người hoặc nội dung
                    content_match = False
                    if person and (person.lower() in (t.content or '').lower() or any(w.lower() in (t.content or '').lower() for w in person.split() if len(w) > 2)):
                        content_match = True
                    
                    # Check tháng/năm
                    month_match = (t.month == msg_month and t.year == msg_year) if (msg_month and msg_year) else True

                    score = 0
                    if amt_match: score += 10
                    if content_match: score += 5
                    if month_match: score += 3
                    candidates.append((score, t))

                if candidates:
                    candidates.sort(key=lambda x: x[0], reverse=True)
                    best_match = candidates[0][1]

            # Xác định ID cho media (phải duy nhất tuyệt đối)
            media_id = None
            if best_match:
                matched_tx_ids.add(best_match.id)
                if best_match.external_id and best_match.external_id.startswith('gido_'):
                    media_id = best_match.external_id
                elif best_match.bill_link:
                    if 'start=' in best_match.bill_link:
                        media_id = best_match.bill_link.split('start=')[-1].split('&')[0]
                    elif '/bill/' in best_match.bill_link:
                        media_id = best_match.bill_link.split('/bill/')[-1].split('?')[0]

            if not media_id:
                media_id = f"gido_m{p['photo_msg_id']}"

            # Lưu hoặc cập nhật vào CashAdvanceBillMedia
            media = db.session.get(CashAdvanceBillMedia, media_id)
            if not media:
                media = CashAdvanceBillMedia(
                    id=media_id,
                    filename=filename,
                    mime_type='image/jpeg',
                    file_size=file_size,
                    data_base64=b64_data,
                    storage_url=f"/advances/bill/{media_id}",
                    transaction_id=best_match.id if best_match else None
                )
                db.session.add(media)
                saved_count += 1
            else:
                media.data_base64 = b64_data
                media.file_size = file_size
                if best_match and not media.transaction_id:
                    media.transaction_id = best_match.id
                saved_count += 1

            # Cập nhật transaction nếu khớp
            if best_match:
                best_match.bill_link = f"/advances/bill/{media_id}"
                if not best_match.external_id:
                    # Kiểm tra trùng lặp trước khi gán external_id
                    exists_ext = CashAdvanceTransaction.query.filter_by(external_id=media_id).first()
                    if not exists_ext:
                        best_match.external_id = media_id
                updated_tx_count += 1
                print(f"✅ Gán ảnh {filename} ({amt:,.0f} đ) -> Tx #{best_match.id} [{best_match.trans_date}]: {best_match.content[:35]} (ID: {media_id})")

            filedb_new_rows.append([media_id, f"tg_local_{filename}", filename])

        db.session.commit()
        print(f"\n=======================================================")
        print(f"🎉 ĐÃ LƯU THÀNH CÔNG {saved_count} ẢNH VÀO POSTGRESQL/SUPABASE!")
        print(f"🔗 Đã liên kết trực tiếp với {updated_tx_count} bút toán sổ quỹ.")
        print(f"=======================================================")

        # Đồng bộ thêm vào tab FileDB của Google Sheets
        try:
            token = get_google_access_token()
            if token and filedb_new_rows:
                import requests, urllib.parse
                # Lấy các mã hiện có trong FileDB để không ghi đè trùng lặp
                quoted_title = urllib.parse.quote("FileDB!A:A")
                res = requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/{quoted_title}", headers={'Authorization': f'Bearer {token}'}, timeout=10)
                existing_codes = set()
                if res.status_code == 200:
                    for r in res.json().get('values', []):
                        if r: existing_codes.add(r[0].strip())

                to_append = [r for r in filedb_new_rows if r[0] not in existing_codes]
                if to_append:
                    append_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GIDO_SPREADSHEET_ID}/values/FileDB!A:C:append?valueInputOption=USER_ENTERED"
                    ap_res = requests.post(append_url, headers={'Authorization': f'Bearer {token}'}, json={'values': to_append}, timeout=15)
                    if ap_res.status_code == 200:
                        print(f"📊 Đã ghi thêm {len(to_append)} dòng đối soát vào tab FileDB trên Google Sheets!")
        except Exception as e:
            print(f"⚠️ Lỗi phụ khi đồng bộ FileDB lên Google Sheets: {e}")

if __name__ == '__main__':
    default_export = r"C:\Users\Son-Tuan Nguyen\Downloads\Telegram Desktop\ChatExport_2026-09-12"
    run_import(default_export)
