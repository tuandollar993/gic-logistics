# GIC Logistics - Dashboard Báo Cáo Doanh Thu & Quản Lý Chi Phí Vận Hành

Hệ thống quản trị báo cáo doanh thu bán hàng, tự động đối soát chi phí vận hành thực tế theo từng lô hàng, quản lý deadline và gửi thông báo nhắc nhở qua Telegram cho nhân viên.

---

## 1. Tính Năng Nổi Bật

1. **Dashboard Điều Hành (Báo Cáo Bán Hàng)**:
   - Thể hiện doanh thu các tháng từ 09/2025 đến 09/2026.
   - Doanh thu bán ra (chưa VAT), chi phí mua vào (đã có VAT), chi phí vận hành thực tế và lợi nhuận ròng.
   - Tiến độ thực hiện chỉ tiêu Target năm 2026 (đơn vị: nghìn đồng).
   - Biểu đồ cột & đường kết hợp diễn biến 12 tháng (Doanh thu vs Chi phí vs Target).
   - Biểu đồ tròn cơ cấu doanh thu theo khách hàng.
   - **Hệ thống sinh nhận xét tự động (Executive Commentary)** chuẩn báo cáo gửi Sếp với nút sao chép 1-click.

2. **Luồng Liên Kết Dữ Liệu Hai Chiều**:
   - Tự động liên kết giữa *Báo cáo bán hàng.xlsx* và *Bảng tổng hợp chi phí vận hành 2026.xlsx*.
   - Đối soát chi phí thực tế theo từng lô hàng (khóa liên kết: Số tờ khai HQ + Tên khách hàng + Kỳ báo cáo).

3. **Cơ Chế Ép & Đốc Thúc Nhân Viên Điền Đủ Chi Phí Từng Lô**:
   - Quản lý tạo lô hàng, đặt hạn chót (Deadline) và phân công cho 1 trong 10 nhân viên.
   - Tự động đếm ngược thời gian (còn X ngày, hôm nay là hạn chót, cảnh báo quá hạn đỏ).
   - **Ràng buộc hoàn thành (Validation)**: Nhân viên bắt buộc phải điền đủ thông tin chi phí, đơn giá, số tiền, loại hóa đơn/chứng từ, ngày chứng từ và thông tin nhà cung cấp (MST/Tên) trước khi được xác nhận hoàn tất.

4. **Tích Hợp Telegram Bot Thông Báo**:
   - Giao việc tự động: Gửi thông báo chi tiết khi quản lý phân công lô mới.
   - Nhắc nhở định kỳ theo 5 cấp độ (còn 5 ngày, còn 3 ngày, còn 1 ngày, quá hạn).
   - Quản lý có thể ấn nút "Nhắc nhở Telegram ngay" bất kỳ lúc nào.
   - Nhân viên có thể gõ `/mytasks` trong bot để xem hạn nộp.

5. **Phân Quyền Rõ Ràng**:
   - **Quản lý (Manager)**: Xem toàn bộ báo cáo tài chính, quản lý tất cả lô hàng, tạo lô, đặt deadline, phân công và giám sát deadline toàn hệ thống.
   - **Nhân viên (Staff)**: Chỉ thao tác và điền chi phí đối với các lô hàng được phân công.

---

## 2. Hướng Dẫn Chạy Hệ Thống

### Bước 1: Khởi động Web Server
Chạy lệnh sau trong thư mục dự án:
```powershell
python run.py
```

Truy cập hệ thống trên trình duyệt:
- **Địa chỉ:** [http://localhost:5000](http://localhost:5000)

### Bước 2: Đăng nhập hệ thống

Hệ thống đã tạo sẵn tài khoản quản lý và 10 nhân viên:

| Vai trò | Tên đăng nhập | Mật khẩu | Chức năng |
|---|---|---|---|
| **Quản lý (Admin)** | `admin` | `admin123` | Toàn quyền quản trị, xem Dashboard, phân công lô, đặt deadline |
| **Nhân viên 01** | `nv_ngocan` | `123456` | Nguyễn Ngọc An - Điền CPVH các lô được giao |
| **Nhân viên 02** | `nv_haidang` | `123456` | Trần Hải Đăng - Điền CPVH các lô được giao |
| **Nhân viên 03** | `nv_cuongtrang` | `123456` | Đặng Cường Tráng - Điền CPVH các lô được giao |
| ... | `nv_phuongthao`, `nv_hoangdung`, `nv_thuanphat`, `nv_maianh`, `nv_minhtri`, `nv_thanhxuyen`, `nv_phuonguyen` | `123456` | Các nhân viên còn lại |

---

## 3. Kích Hoạt Telegram Bot (Tùy chọn)

1. Mở file `.env` và điền Token bot Telegram được cấp từ `@BotFather`:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRstuVWXyz
TELEGRAM_MANAGER_CHAT_ID=123456789
```
2. Chạy bot bằng lệnh:
```powershell
python bot/telegram_bot.py
```
3. Nhân viên chỉ cần chat `/link <tên_đăng_nhập>` với bot để liên kết tài khoản.

---

## 4. Cấu Trúc Thư Mục Dự Án

```
├── app/
│   ├── routes/              # Các route API & điều hướng (auth, dashboard, lots, costs, tasks)
│   ├── services/            # Xử lý logic Excel, tính toán KPI, sinh nhận xét, nhắc nhở
│   ├── templates/           # Giao diện HTML (Bootstrap 5, Responsive, Tiếng Việt)
│   ├── static/              # CSS tùy chỉnh, icons, Chart.js
│   ├── models.py            # SQLAlchemy models (Lots, Costs, Targets, Suppliers, Tasks)
│   ├── config.py            # Cấu hình hệ thống
│   └── __init__.py          # Flask app factory & Jinja filters
├── bot/
│   └── telegram_bot.py      # Bot Telegram nhận lệnh /mytasks, /overview, /link
├── scripts/
│   ├── seed_users.py        # Tạo tài khoản ban đầu
│   ├── import_all.py        # Import lại dữ liệu từ 2 file Excel bất kỳ lúc nào
│   └── assign_sample_tasks.py # Tạo dữ liệu phân công & deadline mẫu
├── data/
│   └── gic.db               # Cơ sở dữ liệu SQLite
├── run.py                   # Điểm chạy chính của hệ thống kèm lịch kiểm tra hàng ngày (09:00 AM)
└── requirements.txt         # Thư viện phụ thuộc
```

---

## 5. Hướng Dẫn Đẩy Lên Vercel & Supabase (Phase 2)

Hệ thống được thiết kế hoàn toàn tương thích với PostgreSQL:
1. Tạo project trên **Supabase**, lấy chuỗi kết nối `postgresql://...`
2. Đổi `DATABASE_URL` trong file `.env` sang chuỗi kết nối Supabase.
3. Chạy `python scripts/seed_users.py` và `python scripts/import_all.py` để đồng bộ toàn bộ dữ liệu lên cloud Supabase.
4. Đẩy mã nguồn lên GitHub và kết nối với **Vercel** để triển khai miễn phí 24/7.
