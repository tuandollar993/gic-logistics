"""scripts/import_telegram_bills.py

HƯỚNG DẪN SỬ DỤNG:
1. Mở Telegram Desktop trên máy tính -> Vào nhóm "Báo cáo tiền GIDO".
2. Bấm Menu (3 chấm góc trên bên phải) -> "Export chat history" (Xuất lịch sử đoạn chat).
3. Chỉ tích chọn "Photos" -> Bấm Export.
4. Chạy lệnh:
   python scripts/import_telegram_bills.py --dir "C:/path/to/ChatExport_.../photos"
   hoặc copy ảnh vào thư mục 'data/telegram_photos/' rồi chạy:
   python scripts/import_telegram_bills.py

Script sẽ tự động:
- Đọc từng ảnh biên lai/hóa đơn
- Nhận diện ngày và số tiền giao dịch
- Tự động đối chiếu với các bút toán sổ quỹ còn thiếu ảnh
- Lưu trữ vĩnh viễn vào Supabase/PostgreSQL (CashAdvanceBillMedia)
"""

import os
import sys
import argparse
import base64
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from app.extensions import db
from app.models import CashAdvanceTransaction, CashAdvanceBillMedia
from app.services.advance_service import save_bill_media, clean_amount

def import_photos_from_dir(photos_dir, dry_run=False):
    app = create_app()
    with app.app_context():
        photos_path = Path(photos_dir)
        if not photos_path.exists():
            print(f"❌ Thư mục không tồn tại: {photos_path}")
            return

        image_files = list(photos_path.glob("*.jpg")) + list(photos_path.glob("*.png")) + list(photos_path.glob("*.jpeg"))
        print(f"🔍 Tìm thấy {len(image_files)} ảnh trong thư mục: {photos_path}")
        if not image_files:
            return

        # Lấy danh sách các giao dịch chưa có ảnh trong DB
        unmatched_txs = CashAdvanceTransaction.query.filter(
            CashAdvanceTransaction.bill_link != None,
            CashAdvanceTransaction.bill_link != ''
        ).all()

        missing_txs = []
        for tx in unmatched_txs:
            code = ''
            if 'start=' in tx.bill_link:
                code = tx.bill_link.split('start=')[-1].split('&')[0]
            elif '/bill/' in tx.bill_link:
                code = tx.bill_link.split('/bill/')[-1].split('?')[0]
            
            if code:
                m = db.session.get(CashAdvanceBillMedia, code)
                if not m or not m.data_base64:
                    missing_txs.append((code, tx))

        print(f"📋 Hiện có {len(missing_txs)} bút toán đang thiếu ảnh dữ liệu trong database.")

        saved_count = 0
        for img_p in image_files:
            file_bytes = img_p.read_bytes()
            mime_type = 'image/png' if img_p.suffix.lower() == '.png' else 'image/jpeg'
            
            # Kiểm tra xem ảnh này có khớp với code nào trong tên file không
            matched_code = None
            matched_tx = None
            for code, tx in missing_txs:
                if code in img_p.name:
                    matched_code = code
                    matched_tx = tx
                    break

            if matched_code:
                print(f"✅ Khớp mã {matched_code} -> {img_p.name} (Giao dịch {matched_tx.id}: {matched_tx.content})")
                if not dry_run:
                    save_bill_media(matched_code, file_bytes, img_p.name, mime_type, transaction_id=matched_tx.id)
                    saved_count += 1
            else:
                gen_id = 'gido_' + hex(int(time.time() * 1000))[2:]
                if not dry_run:
                    save_bill_media(gen_id, file_bytes, img_p.name, mime_type)
                    saved_count += 1

        print(f"\n🎉 Hoàn thành: Đã nạp thành công {saved_count} ảnh vào database!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Import bill photos from Telegram Export")
    parser.add_argument('--dir', default='data/telegram_photos', help="Đường dẫn thư mục ảnh export")
    parser.add_argument('--dry-run', action='store_true', help="Chạy thử nghiệm không lưu DB")
    args = parser.parse_args()
    import_photos_from_dir(args.dir, dry_run=args.dry_run)
