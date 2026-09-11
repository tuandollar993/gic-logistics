# MIGRATION RUNBOOK - GIC LOGISTICS

Quy trình vận hành, nâng cấp và phục hồi cơ sở dữ liệu an toàn cho GIC Logistics trên môi trường Local (SQLite) và Cloud/Production (PostgreSQL - Render / Supabase).

---

## 1. Nguyên Tắc An Toàn Bắt Buộc

1. **KHÔNG BAO GIỜ** chạy lệnh migration (`flask db upgrade`) trên production mà chưa sao lưu DB trước đó.
2. **KHÔNG DÙNG** `db.drop_all()` hoặc các câu lệnh DDL phá hủy (`DROP TABLE`, `DROP COLUMN`) trong các phiên bản cập nhật thông thường.
3. Tất cả migrations phải hỗ trợ `render_as_batch=True` để tương thích cả SQLite và PostgreSQL.
4. Kiểm tra biến môi trường `DATABASE_URL` trước khi thực thi để tránh nhầm lẫn giữa môi trường Staging và Production.

---

## 2. Bước 1: Sao Lưu Cơ Sở Dữ Liệu (Backup)

Trước khi áp dụng bất kỳ migration nào, chạy kịch bản sao lưu:

```bash
# Tự động nhận diện SQLite hoặc PostgreSQL từ DATABASE_URL trong .env
python scripts/backup_db.py

# Tuỳ chọn thư mục lưu và số bản backup tối đa cần giữ (mặc định 7)
python scripts/backup_db.py --dest-dir ./backups --max-backups 10
```

- Kịch bản sẽ:
  - Kiểm tra kết nối DB trước.
  - Sử dụng SQLite Online Backup API đối với SQLite hoặc `pg_dump` / SQLAlchemy reflection đối với PostgreSQL.
  - Tự động xoay vòng file (rotate), chỉ lưu giữ số bản sao lưu mới nhất.
  - Đảm bảo **không** in lộ mật khẩu hay connection string ra màn hình console.

---

## 3. Bước 2: Kiểm Tra Trạng Thái Migration Hiện Tại

Kiểm tra revision hiện tại của database so với codebase:

```bash
# Xem revision hiện tại trên DB
flask db current

# Xem revision mới nhất có trong mã nguồn (HEAD)
flask db heads

# Xem lịch sử migrations
flask db history
```

Nếu `current` trùng với `heads`, database đã ở trạng thái mới nhất.

---

## 4. Bước 3: Áp Dụng Migration (Upgrade)

```bash
flask db upgrade
```

Sau khi hoàn tất, kiểm tra lại:
```bash
flask db current
```

---

## 5. Bước 4: Quy Trình Rollback Khi Xảy Ra Lỗi

Nếu lệnh `upgrade` gặp sự cố hoặc nghiệp vụ sau khi deploy phát hiện sai sót, thực hiện rollback:

### 5.1. Rollback về phiên bản trước (1 step)
```bash
flask db downgrade
```

### 5.2. Rollback về phiên bản cụ thể (Revision ID)
```bash
# Ví dụ quay về phiên bản initial schema
flask db downgrade 0001_initial
```

### 5.3. Khôi phục hoàn toàn từ bản backup nếu DDL bị gián đoạn

- **Đối với SQLite:**
  ```bash
  # Dừng ứng dụng
  cp backups/gic_backup_YYYYMMDD_HHMMSS.sqlite3 data/gic.db
  # Khởi động lại ứng dụng
  ```

- **Đối với PostgreSQL:**
  ```bash
  # Sử dụng file SQL dump đã tạo ở Bước 1
  psql -h <HOST> -U <USER> -d <DBNAME> -f backups/gic_pg_backup_YYYYMMDD_HHMMSS.sql
  ```

---

## 6. Bước 5: Kiểm Tra Sau Migration (Verification)

Sau khi hoàn tất migration:
1. Chạy suite test kiểm tra tính tương thích schema:
   ```bash
   pytest tests/test_schema_compatibility.py -v
   ```
2. Chạy toàn bộ test nghiệp vụ:
   ```bash
   pytest -q
   ```
3. Khởi động ứng dụng kiểm tra dashboard và danh sách tạm ứng / chi phí lô hàng:
   - Truy cập `/lots`
   - Truy cập `/advances`
   - Kiểm tra log kiểm toán (`audit_logs`)

---

## 7. Chi Tiết Migration 0003: `0003_bill_foreign_keys`

- **Mục đích:** Bổ sung các khóa ngoại Foreign Keys tường minh cho bảng `cash_advance_bill_media`:
  - `transaction_id` -> `cash_advance_transactions.id`
  - `operating_cost_id` -> `operating_costs.id`
  - `lot_id` -> `lots.id`
  - `uploaded_by` -> `users.id`
- **Khả năng tương thích:** Migration định nghĩa đầy đủ named foreign keys (`fk_cabm_...`) để hỗ trợ hoàn hảo chế độ batch mode trên SQLite (`render_as_batch=True`) và PostgreSQL.
- **Quy trình áp dụng trên Production (khi được phép):**
  1. Sao lưu database: `python scripts/backup_db.py`
  2. Kiểm tra revision hiện tại: `flask db current` (kết quả mong đợi: `0002_lock_audit`)
  3. Áp dụng nâng cấp: `flask db upgrade`
  4. Chuẩn hóa đường dẫn private: `python scripts/backfill_private_bills.py --execute`
  5. Lệnh hoàn tác nếu cần: `flask db downgrade 0002_lock_audit`

