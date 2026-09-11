# TỪ ĐIỂN DỮ LIỆU TÀI CHÍNH (FINANCE DATA DICTIONARY) - GIC LOGISTICS

Tài liệu này định nghĩa cấu trúc dữ liệu, quy chuẩn kiểu số, quy ước dấu (+/-), và quy tắc nghiệp vụ tài chính trong toàn bộ hệ thống GIC Logistics.

---

## 1. Quy ước dấu và Nguyên tắc kế toán (Sign & Calculation Conventions)

1. **Doanh thu bán hàng (Revenue):**
   - Luôn mang giá trị dương (> 0).
   - Tổng doanh thu = Doanh thu mua hộ/cước chính + các khoản phụ phí bán (surcharges).
2. **Chi phí đầu vào (Cost / Expense):**
   - Trong bảng OperatingCost và RevenueItem, đơn giá (unit_price) và tổng tiền (	otal_amount, cost_amount, at_amount) luôn được lưu trữ là **số dương (>= 0)**.
   - Khi tính toán lợi nhuận:
     - **Lợi nhuận gộp (Gross Profit)** = Doanh thu bán (	otal_sell) - Giá vốn mua (	otal_buy).
     - **Lợi nhuận thuần (Net Profit)** = Lợi nhuận gộp - Chi phí vận hành (operating_cost).
3. **Dòng tiền Tạm ứng / Chi nhánh (Cash Advances & Cashflow):**
   - **Tiền thu vào (Inflows):** Công ty cấp vốn (	uan_thu_cty), Hải Bân trả (	uan_thu_haiban), Thu khác (	uan_thu_khac) -> Giá trị dương (> 0).
   - **Tiền chi ra (Outflows):** Chi tạm ứng chuyến (	uan_chi), Chi trả Hải Bân (	uan_chi_haiban_cty), Lương chi (luong_chi), Chi đối tác (partner_amount) -> Giá trị xuất hiển thị là chi phí / số âm.
   - **Tồn quỹ (Balance):** Tồn cuối kỳ = Tồn đầu kỳ + Tổng thu - Tổng chi.
4. **Phân loại Lương (Payroll Outflow vs Inflow):**
   - Các khoản tiền mang nội dung chi lương hoặc chi ra về cho... bắt buộc được ghi nhận vào cột luong_chi (Chi phí lương), không được để ở luong_thu.

---

## 2. Danh mục Bảng dữ liệu (Database Schema Dictionary)

### 2.1. Bảng lots (Lô hàng)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc |
| :--- | :--- | :--- |
| id | INTEGER | Khóa chính tự tăng |
| lot_label | VARCHAR(100) | Ký hiệu lô (vd: Lô 1, Lô 2, Lô CP 1) |
| customer_id | INTEGER | FK liên kết customers.id |
| company | VARCHAR(100) | Tên pháp nhân công ty / doanh nghiệp |
| customs_declaration | VARCHAR(100) | Số tờ khai hải quan (TKHQ) |
| month | INTEGER | Kỳ tháng (1 - 12) |
| year | INTEGER | Kỳ năm (vd: 2025, 2026) |
| start_date / end_date | DATE | Ngày bắt đầu / kết thúc chuyến |
| status | VARCHAR(20) | Trạng thái: pending, ssigned, in_progress, completed |
| cost_deadline | DATE | Hạn chót nhân viên phải hoàn tất nhập chi phí |
| ssigned_to | INTEGER | FK liên kết users.id (nhân viên phụ trách) |
| created_by | INTEGER | FK liên kết users.id (người tạo lô) |
| source_type | VARCHAR(20) | Nguồn: gido, ghnlog, cpvh, manual |
| source_sheet | VARCHAR(100) | Tên sheet Excel nguồn nếu được import |

### 2.2. Bảng operating_costs (Chi phí vận hành chi tiết)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc |
| :--- | :--- | :--- |
| id | INTEGER | Khóa chính |
| lot_id | INTEGER | FK liên kết lots.id |
| cost_type | VARCHAR(100) | Phân loại chi phí (Phí thông quan, Phí cửa khẩu, Bến bãi, v.v.) |
| description | TEXT | Nội dung chi tiết (bắt buộc) |
| ehicle_plate | VARCHAR(50) | Biển kiểm soát xe (BKS) |
| ehicle_count | FLOAT | Số lượng xe (>= 0) |
| unit_price | FLOAT | Đơn giá (>= 0) |
| 	otal_amount | FLOAT | Tổng tiền = Đơn giá * Số lượng |
| cost_amount | FLOAT | Số tiền trước VAT |
| at_amount | FLOAT | Tiền thuế VAT (>= 0) |
| invoice_type | VARCHAR(50) | Loại chứng từ: Hóa đơn GTGT, Phiếu thu, Vé xe, Không HĐ |
| invoice_symbol | VARCHAR(50) | Ký hiệu hóa đơn |
| invoice_number | VARCHAR(100) | Số hóa đơn / Số phiếu thu |
| document_date | DATE | Ngày trên chứng từ (bắt buộc khi hoàn thành lô) |
| supplier_tax_code| VARCHAR(50) | Mã số thuế / CCCD nhà cung cấp |
| supplier_name | VARCHAR(255) | Tên nhà cung cấp / đối tác |
| payment_method | VARCHAR(50) | Hình thức thanh toán: Tiền mặt, Chuyển khoản (UNC) |
| illed_by | INTEGER | FK liên kết users.id (nhân sự kê khai) |

### 2.3. Bảng cash_advance_monthly (Sổ quỹ & Dòng tiền theo tháng)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc |
| :--- | :--- | :--- |
| id | INTEGER | Khóa chính |
| month | INTEGER | Tháng (1 - 12) |
| year | INTEGER | Năm |
| opening_balance | FLOAT | Tồn quỹ đầu kỳ |
| 	otal_company_receipts | FLOAT | Tổng tiền nhận từ công ty |
| 	otal_haiban_receipts | FLOAT | Tổng thu từ Hải Bân |
| 	otal_advances_spent | FLOAT | Tổng tiền đã chi tạm ứng |
| closing_balance | FLOAT | Tồn quỹ cuối kỳ |
| is_locked | BOOLEAN | Cờ khóa sổ (True: cấm đồng bộ và cấm sửa đổi) |
| locked_at | DATETIME | Thời điểm khóa sổ |
| locked_by | INTEGER | FK users.id người thực hiện khóa |
| last_synced_at | DATETIME | Thời gian đồng bộ Google Sheets gần nhất |

### 2.4. Bảng cash_advance_transactions (Giao dịch dòng tiền tạm ứng)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc |
| :--- | :--- | :--- |
| id | INTEGER | Khóa chính |
| monthly_id | INTEGER | FK cash_advance_monthly.id |
| row_index | INTEGER | Vị trí dòng tương ứng trên bảng tính Google Sheet |
| external_id | VARCHAR(128) | Khóa định danh UUID duy nhất từ Cột R Google Sheet (chống nhảy dòng) |
| sync_status | VARCHAR(20) | Trạng thái: `synced`, `manual`, `pending_identity`, `missing_source` |
| sync_hash | VARCHAR(64) | Hash SHA-256 kiểm tra thay đổi nội dung dòng |
| trans_date | VARCHAR(50) | Ngày giao dịch (Được chuẩn hóa format DD/MM/YYYY) |
| content | TEXT | Nội dung chi tiết thu / chi |
| tuan_ton / tuan_chi | FLOAT | Số dư / Khoản chi |
| luong_thu / luong_chi| FLOAT | Khoản lương thu / chi |
| partner_amount | FLOAT | Số tiền thanh toán đối tác |
| partner_invoice | VARCHAR(500) | Số hóa đơn / chứng từ thanh toán |
| bill_link | VARCHAR(500) | Khóa / ID liên kết ảnh hóa đơn |
| is_manual | BOOLEAN | Đánh dấu bản ghi tạo thủ công trên web (không bị đè bởi sync) |
| is_deleted | BOOLEAN | Trạng thái xóa mềm bởi người dùng (không bao giờ bị un-delete bởi sync) |

### 2.5. Bảng cash_advance_bill_media (Quản lý File & Ảnh Chứng Từ Dòng Tiền)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc RBAC |
| :--- | :--- | :--- |
| id | VARCHAR(64) | Khóa chính (UUID / short ID ngẫu nhiên) |
| filename | VARCHAR(255) | Tên file gốc |
| mime_type | VARCHAR(100) | MIME type an toàn (image/jpeg, image/png, application/pdf...) |
| storage_url | VARCHAR(500) | Đường dẫn lưu trữ nội bộ riêng tư: `advance-bills/<id>` |
| file_size | INTEGER | Dung lượng file (bytes) |
| transaction_id | INTEGER | FK cash_advance_transactions.id (Liên kết giao dịch tạm ứng) |
| operating_cost_id | INTEGER | FK operating_costs.id (Liên kết chi phí vận hành) |
| lot_id | INTEGER | FK lots.id (Liên kết lô hàng) |
| uploaded_by | INTEGER | FK users.id (Nhân viên upload) |
| created_at | DATETIME | Thời điểm upload |

> **Quy tắc phân quyền (RBAC) xem bill qua `/advances/bill/<id>`:**
> - **Admin / Manager:** Có quyền xem tất cả hóa đơn / chứng từ trong hệ thống.
> - **Staff:** Chỉ được xem bill nếu: (1) là người tải lên (`uploaded_by == current_user.id`), hoặc (2) được phân công quản lý lô hàng (`lot.assigned_to == current_user.id`), hoặc (3) chi phí / giao dịch liên kết với lô được phân công. Người không liên quan bị từ chối 403 Forbidden.

### 2.6. Bảng audit_logs (Nhật ký kiểm toán an toàn)
| Tên cột | Kiểu dữ liệu | Mô tả & Quy tắc |
| :--- | :--- | :--- |
| id | INTEGER | Khóa chính |
| user_id | INTEGER | FK users.id người thực hiện thao tác |
| actor | VARCHAR(100) | Tên người thao tác hoặc dịch vụ tự động |
| action | VARCHAR(50) | Thao tác: delete_lot, delete_cost, lock_month, create_user... |
| target_type | VARCHAR(50) | Đối tượng: lot, cost, user, cash_advance, bill |
| target_id | VARCHAR(64) | ID của đối tượng bị tác động |
| before_state | TEXT | JSON snapshot trạng thái trước đột biến (đã làm sạch bí mật) |
| after_state | TEXT | JSON snapshot trạng thái sau đột biến (đã làm sạch bí mật) |
| details | TEXT | Nội dung mô tả chi tiết thao tác |
| ip_address | VARCHAR(45) | Địa chỉ IP của máy khách |
| created_at | DATETIME | Dấu thời gian ghi nhận (UTC) |
