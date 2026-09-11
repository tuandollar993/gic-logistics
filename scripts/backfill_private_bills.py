"""scripts/backfill_private_bills.py

Quét và chuẩn hoá các hóa đơn trong CashAdvanceBillMedia:
- Chuyển đổi các storage_url chứa public bucket link (ví dụ /object/public/...)
  về đường dẫn nội bộ an toàn (advance-bills/{object_name} hoặc /advances/bill/{id}).
- Mặc định chạy ở chế độ --dry-run an toàn.
- Dùng cờ --execute để thực thi cập nhật vào database.
"""
import sys
import argparse
import urllib.parse
from app import create_app
from app.extensions import db
from app.models import CashAdvanceBillMedia

def normalize_storage_url(media_id, old_url, filename='receipt.jpg'):
    if not old_url:
        return f"/advances/bill/{media_id}"
    
    # If it's a supabase public url
    if '/object/public/advance-bills/' in old_url:
        quoted_name = old_url.split('/object/public/advance-bills/')[-1]
        obj_name = urllib.parse.unquote(quoted_name)
        return f"advance-bills/{obj_name}"
    elif '/object/public/' in old_url:
        quoted_name = old_url.split('/object/public/')[-1]
        obj_name = urllib.parse.unquote(quoted_name)
        return obj_name
    elif old_url.startswith('http'):
        # Fallback to local authenticated endpoint
        return f"/advances/bill/{media_id}"
    return old_url

def backfill_bills(execute=False):
    app = create_app()
    with app.app_context():
        mode_str = "EXECUTE" if execute else "DRY-RUN (No changes applied)"
        print(f"=== BACKFILL PRIVATE BILLS [{mode_str}] ===")
        
        all_bills = CashAdvanceBillMedia.query.all()
        candidates = []
        for b in all_bills:
            url = b.storage_url or ''
            if '/object/public/' in url or url.startswith('http'):
                candidates.append(b)

        print(f"Tìm thấy {len(candidates)} / {len(all_bills)} hóa đơn có storage_url public/external.")
        
        updated_count = 0
        for b in candidates:
            new_url = normalize_storage_url(b.id, b.storage_url, b.filename)
            print(f"- Bill ID {b.id}:")
            print(f"  Old: {b.storage_url}")
            print(f"  New: {new_url}")
            if execute:
                b.storage_url = new_url
                updated_count += 1

        if execute:
            db.session.commit()
            print(f"\n[EXECUTE SUCCESS] Đã cập nhật thành công {updated_count} hóa đơn về path nội bộ an toàn.")
        else:
            print(f"\n[DRY-RUN] Hoàn tất quét. Chạy với cờ --execute để áp dụng thay đổi vào cơ sở dữ liệu.")

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Backfill private bill storage URLs")
    parser.add_argument('--execute', action='store_true', help="Thực thi cập nhật database (mặc định là dry-run)")
    args = parser.parse_args()
    backfill_bills(execute=args.execute)
