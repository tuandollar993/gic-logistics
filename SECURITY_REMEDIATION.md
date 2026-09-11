# SECURITY REMEDIATION REPORT & CREDENTIAL ROTATION GUIDE

Tài liệu này tổng hợp toàn bộ các hành động khắc phục lỗ hổng bảo mật đã thực hiện trên mã nguồn và hướng dẫn các thao tác người dùng cần thực hiện thủ công để bảo vệ an toàn tuyệt đối cho hệ thống.

---

## 1. Các Lỗ Hổng Bảo Mật Đã Khắc Phục Trong Mã Nguồn

| Mục | Mô tả lỗ hổng cũ | Trạng thái khắc phục |
|---|---|---|
| **Hardcoded Secret Key** | `SECRET_KEY` có fallback tĩnh `gic-secret-key-2026-secure` trong `app/config.py`. | **ĐÃ XÓA**. Yêu cầu bắt buộc biến môi trường `SECRET_KEY`. Trên Production, hệ thống fail-fast (dừng khởi động ngay) nếu thiếu. |
| **Hardcoded Bot Tokens** | Token bot Telegram fallback trực tiếp trong `cashflow_bot_service.py` và `advance_service.py`. | **ĐÃ XÓA**. Đọc 100% từ biến môi trường `CASHFLOW_BOT_TOKEN`. Báo lỗi rõ ràng nếu thiếu. |
| **Hardcoded Gemini API Key** | API Key Google Gemini fallback trong `cashflow_bot_service.py`. | **ĐÃ XÓA**. Đọc 100% từ biến môi trường `GEMINI_API_KEY`. |
| **Hardcoded Webhook Secret** | `WEBHOOK_SECRET` có fallback tĩnh `gic-secret-2026` và ghi lộ trong URL query string tại `google_sheet_sync.gs`. | **ĐÃ KHẮC PHỤC**. Đổi sang gửi secret qua HTTP Header `X-Webhook-Secret`. Xóa secret khỏi URL query param và log URL. |
| **Telegram Webhook Fail-Closed** | `/advances/bot-webhook` chỉ kiểm tra nếu có cấu hình token, nếu thiếu token vẫn cho qua request. | **FAIL-CLOSED**. Webhook luôn từ chối 401 nếu thiếu hoặc sai token (`hmac.compare_digest`). Trên Production, fail-fast nếu thiếu `TELEGRAM_SECRET_TOKEN`. |
| **Set Webhook Hardening** | Route thiết lập webhook Telegram có thể bị gọi trái phép hoặc bypass kiểm tra host. | **ĐÃ KHẮC PHỤC**. Giới hạn Admin (`@admin_required`), ép buộc HTTPS, chặn localhost/private IP, kiểm tra whitelist host (`RENDER_EXTERNAL_HOSTNAME`), gửi qua POST JSON body (không lộ query string), log audit không lưu token. |
| **Public Bill Storage URLs** | File hóa đơn lưu URL public trên Supabase Storage `/object/public/` có thể bị rò rỉ hoặc duyệt trái phép. | **ĐÃ LOẠI BỎ**. Chuyển toàn bộ sang đường dẫn nội bộ riêng tư `advance-bills/<object_name>`. Phục vụ file qua `/advances/bill/<id>` với xác thực đăng nhập, header `X-Content-Type-Options: nosniff` và `Cache-Control: private, no-store`. |
| **Bill RBAC & Chống IDOR** | Quyền xem bill kiểm tra lỏng lẻo bằng chuỗi `ilike` trên ghi chú, nhân viên có thể xem chéo hóa đơn của nhau. | **ĐÃ KHẮC PHỤC**. Bổ sung Foreign Keys tường minh (`transaction_id`, `operating_cost_id`, `lot_id`, `uploaded_by`) vào `CashAdvanceBillMedia`. Nhân viên chỉ được xem bill nếu là người upload hoặc được phân công quản lý lô/chi phí/giao dịch tương ứng. Từ chối 403 đối với người không liên quan. |
| **Atomic Audit Logs** | `log_audit()` tự commit độc lập, dẫn đến rủi ro ghi audit thành công dù thao tác dữ liệu chính thất bại hoặc bị rollback. | **ATOMIC TRANSACTION**. Bỏ tự động commit trong `log_audit()`. Audit log tham gia trực tiếp vào transaction của nghiệp vụ chính. Tự động thanh lọc `[REDACTED]` các trường nhạy cảm (`password`, `secret`, `token`). |
| **Mật khẩu mặc định công khai** | `admin123` và `123456` in ra console ở `run.py`, ghi trong `README.md`, `seed_users.py` và `login.html`. | **ĐÃ LOẠI BỎ TOÀN BỘ**. Xóa bỏ logic in password ra console và giao diện; `seed_users.py` không còn reset đè mật khẩu của người dùng đã tồn tại. |
| **Bảo vệ Cookie & Phiên làm việc** | Thiếu cờ `HttpOnly`, `SameSite`, `Secure` trên Session Cookie. | **ĐÃ CẤU HÌNH**. `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`, `SESSION_COOKIE_SECURE = True` trên môi trường Production/HTTPS. |
| **Database Exposure** | `docker-compose.yml` mở port 5432 ra toàn mạng với password tĩnh `yourpassword`. | **ĐÃ KHẮC PHỤC**. Ràng buộc port 5432 về `127.0.0.1`, sử dụng biến `${POSTGRES_PASSWORD}` và bổ sung PostgreSQL container healthcheck. |
| **Đồng bộ Google Sheet bất đồng bộ & Xung đột** | Quá trình sync nhiều người bấm đồng thời gây race condition; nhận diện dòng bằng `row_index` bị lệch khi chèn/xóa dòng. | **LOCK & UUID**. Áp dụng PostgreSQL Advisory Lock (`pg_try_advisory_lock` / threading fallback) ngăn sync đồng thời. Sử dụng Cột R làm External ID (UUID); gắn cờ `pending_identity` cho dòng thiếu UUID và `missing_source` cho dòng bị xóa trên sheet; bảo vệ trạng thái xóa mềm của người dùng. |

---

## 2. Hướng Dẫn Thao Tác Thủ Công Người Dùng Cần Thực Hiện (Action Items)

Do nguyên tắc an toàn, hệ thống không tự ý thu hồi (revoke) các token bên ngoài hệ thống. Người quản trị cần thực hiện các bước sau trên các dịch vụ bên ngoài:

### 1. Thu hồi và tạo mới Bot Token Telegram (`CASHFLOW_BOT_TOKEN`)
1. Mở Telegram, truy cập `@BotFather`.
2. Gõ `/mybots`, chọn bot dòng tiền (`@gidotien_bot`).
3. Chọn **API Token** -> Chọn **Revoke current token**.
4. Sao chép Token mới và cập nhật vào biến môi trường `CASHFLOW_BOT_TOKEN` trên Render và file `.env`.

### 2. Thu hồi và tạo mới Google Gemini API Key (`GEMINI_API_KEY`)
1. Truy cập [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Tìm API Key đã dùng trước đây và nhấn nút **Delete / Revoke**.
3. Bấm **Create API Key** mới.
4. Cập nhật API Key mới vào biến môi trường `GEMINI_API_KEY` trên Render và file `.env`.

### 3. Sinh mới `SECRET_KEY`, `WEBHOOK_SECRET`, `TELEGRAM_SECRET_TOKEN` & `BOT_UPLOAD_SECRET`
Chạy lệnh sau trên terminal để sinh các khóa ngẫu nhiên chuẩn mã hóa an toàn:
```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32)); print('WEBHOOK_SECRET=' + secrets.token_hex(24)); print('TELEGRAM_SECRET_TOKEN=' + secrets.token_hex(24)); print('BOT_UPLOAD_SECRET=' + secrets.token_hex(24))"
```
- Cập nhật các biến vào mục **Environment Variables** trên Dashboard Render.
- Trên Google Apps Script (`google_sheet_sync.gs`): Vào **Project Settings** -> **Script Properties**, thêm property:
  - Property: `WEBHOOK_SECRET`
  - Value: `<chuỗi secret vừa sinh>`

### 4. Đổi mật khẩu tài khoản `admin` hiện tại
1. Đăng nhập vào hệ thống web với tài khoản `admin`.
2. Vào trang Quản Lý Người Dùng hoặc chạy lệnh cập nhật mật khẩu trực tiếp bằng script bảo mật:
```bash
python -c "from app import create_app; from app.extensions import db; from app.models import User; app = create_app();
with app.app_context():
    u = User.query.filter_by(username='admin').first()
    if u:
        u.set_password('MatKhauMoiCucKyAnToan@2026')
        db.session.commit()
        print('Đã đổi mật khẩu admin thành công.')
"
```

### 5. Chuẩn hóa dữ liệu Bill cũ và UUID Google Sheet
- Để chuyển đổi các URL public cũ trong database về định dạng private:
```bash
python scripts/backfill_private_bills.py --dry-run
python scripts/backfill_private_bills.py --execute
```
- Để sinh UUID trên Google Sheet cho các dòng chưa có External ID:
```bash
python scripts/backfill_sheet_uuids.py --dry-run
python scripts/backfill_sheet_uuids.py --execute
```
