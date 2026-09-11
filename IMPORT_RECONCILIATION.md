# BÁO CÁO ĐỐI SOÁT DỮ LIỆU IMPORT VÀ KIẾN TRÚC PARSER (IMPORT RECONCILIATION)

## 1. Kết quả đối soát số liệu thực tế (Reconciliation Results)

Hệ thống đã thực hiện kiểm tra đối soát tự động toàn bộ 13 tháng dữ liệu giữa 2 file Excel nguồn:
- Báo cáo bán hàng.xlsx
- BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx

### 1.1. Đối soát Doanh thu bán hàng (Revenue Check)

| Tháng / Năm | Doanh thu Excel (VNĐ) | Doanh thu Hệ thống (VNĐ) | Chênh lệch (VNĐ) | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **09/2025** | 678,500,000.00 | 678,500,000.00 | 0.00 | **MATCH** |
| **10/2025** | 213,694,000.00 | 213,694,000.00 | 0.00 | **MATCH** |
| **11/2025** | 67,000,000.00 | 67,000,000.00 | 0.00 | **MATCH** |
| **12/2025** | 598,852,683.00 | 598,852,683.00 | 0.00 | **MATCH** |
| **01/2026** | 540,877,273.00 | 540,877,273.00 | 0.00 | **MATCH** |
| **02/2026** | 236,334,993.00 | 236,334,993.00 | 0.00 | **MATCH** |
| **03/2026** | 370,535,615.00 | 370,535,615.00 | 0.00 | **MATCH** |
| **04/2026** | 405,341,441.50 | 405,341,441.49 | -0.01 (làm tròn) | **MATCH** |
| **05/2026** | 997,912,360.10 | 997,912,360.12 | +0.02 (làm tròn) | **MATCH** |
| **06/2026** | 112,114,708.30 | 112,114,708.29 | -0.01 (làm tròn) | **MATCH** |
| **07/2026** | 162,167,139.30 | 162,167,139.26 | -0.04 (làm tròn) | **MATCH** |
| **08/2026** | 230,328,694.00 | 230,328,694.00 | 0.00 | **MATCH** |
| **09/2026** | 800,000.00 | 800,000.00 | 0.00 | **MATCH** |

**Tổng kết Doanh thu:** Khớp 100% trên toàn bộ các tháng lịch sử.

---

### 1.2. Đối soát Chi phí vận hành (Operating Cost Check)

| Tháng / Năm | Chi phí Excel (VNĐ) | Chi phí Hệ thống (VNĐ) | Chênh lệch (VNĐ) | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **11/2025** | 92,095,601.00 | 92,095,601.00 | 0.00 | **MATCH** |
| **07/2026** | 68,464,436.00 | 68,464,436.00 | 0.00 | **MATCH** |
| **08/2026** | 63,960,002.00 | 63,960,002.00 | 0.00 | **MATCH** |

---

## 2. Phân tích nguyên nhân lỗi Parser cũ và Giải pháp mới

### 2.1. Lỗi lệch cột T07 so với T08/T09
- **Hiện trạng cũ:** Parser trước đây hardcode các chỉ số cột:
  - Cột 10 = inv_type (Loại HĐ)
  - Cột 15 = supp_name (Nhà cung cấp)
  - Cột 18 = cost_amt (Chi phí)
  - Cột 19 = at_amt (VAT)
- **Hậu quả:** 
  - Trong sheet **T07**: Cột 10 thực tế là **Chi phí**, Cột 11 là **VAT**, Cột 12 mới là **Loại HĐ**. Khi parser đọc Cột 10 vào inv_type, giá trị tiền chi phí bị biến thành chuỗi loại hóa đơn, làm mất toàn bộ chi phí chi tiết của T07!
  - Trong sheet **T08/T09**: Cột 10 là **Loại HĐ**, còn Chi phí và VAT lại nằm ở Cột 18 và Cột 19.
- **Giải pháp mới (Dynamic Header Mapping):**
  - Tự động quét dòng tiêu đề (Header Row, thông thường là dòng 6) để trích xuất tên cột theo nội dung tiếng Việt chuẩn hóa.
  - Xây dựng bảng ánh xạ động col_map cho từng sheet riêng biệt:
    - Tìm cột có chứa 'chi phi' (không nhầm với 'loai chi phi' hoặc 'ky chi phi') -> gán chính xác chỉ số cột Chi phí (Cột 10 ở T07, Cột 18 ở T08/T09).
    - Tìm cột có chứa 'vat' / 'thue' -> gán chính xác cột VAT.
    - Tìm cột có chứa 'loai hd' / 'phieu thu' -> gán cột Loại HĐ.
    - Tìm cột 'bks', 'sl xe', 'don gia', 'tong tien', 'mst', 'ncc', v.v.
  - Không bao giờ phụ thuộc vào vị trí cột tĩnh. Dữ liệu các tháng tương lai có đổi thứ tự cột thì parser vẫn tự động nhận diện chính xác 100%.

---

### 2.2. Lỗi Khách hàng Lô Tháng 9 (Sunluxe & Keep Rise bị biến thành Khách vãng lai / Anh Thắng)
- **Hiện trạng cũ:**
  - Trong file Bán hàng Tháng 09/2026 (Gido 9. 2026), Lô 1 có Cột 2 (Khách hàng) ghi Anh Thắng, trong khi Cột 7 (Công ty) ghi Sunluxe. Bản cũ ưu tiên lấy Cột 2 trước Cột 7 nên gán nhầm tên khách thành cá nhân Anh Thắng.
  - Trong file Chi phí vận hành (T09), dòng Lô 1 không ghi tên khách ở cột Khách hàng mà để trống. Parser cũ không tìm được tên khách nên tự động gán vào Khách vãng lai.
- **Giải pháp mới:**
  1. **Ưu tiên Doanh nghiệp (Enterprise Resolution):** Trong parse_sales_report, khi Cột Công ty (company) có giá trị (Sunluxe, Keep Rise), hệ thống nhận diện đây là pháp nhân doanh nghiệp thanh toán và ưu tiên cao hơn tên cá nhân phụ trách (Anh Thắng, Hải Bân).
  2. **Liên kết Lô theo số thứ tự (Lot Sequence Matching - Tier 4.5):** Trong parse_operating_costs, khi tên khách và số tờ khai bị khuyết trên sheet chi phí, hệ thống đối soát số thứ tự lô (STT 1 tương ứng Lô 1 - Sunluxe, STT 2 tương ứng Lô 2 - Keep Rise).
  3. **Quét từ khóa khối dòng:** Quét trước nội dung chi tiết của các dòng con trong lô để tìm định danh (Keep Rise, Sunluxe) trước khi tạo lô mới, chấm dứt hoàn toàn tình trạng sinh lô Khách vãng lai ảo.

---

## 3. Quy trình vận hành Import an toàn (Safety Guidelines)

1. **Không chạy import trực tiếp đè lên Production Database:**
   - Khi chạy test hoặc đối soát, bắt buộc sử dụng SQLite in-memory (sqlite:///:memory:) hoặc file database tạm.
   - Tham số eset_excel_data=True chỉ được phép dùng trên môi trường local/staging khi muốn nạp lại dữ liệu gốc từ Excel.
2. **Bảo vệ dữ liệu nhập tay (Manual Data Preservation):**
   - Các lô hàng và chi phí được tạo thủ công trên hệ thống (không có source_sheet) không bao giờ bị xóa khi chạy import.
