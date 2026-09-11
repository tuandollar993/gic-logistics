"""
Module sinh file Excel Báo Giá Logistics Chuẩn Hóa
Dựa trên Mẫu báo giá.xlsx và hệ thống định mức toàn diện các dịch vụ logistics của GIC Logistics
"""

import io
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ==============================================================================
# DỮ LIỆU MA TRẬN CƯỚC VẬN CHUYỂN CHUẨN (THEO MẪU BÁO GIÁ & LỊCH SỬ THỰC TẾ)
# ==============================================================================
TRANSPORT_COLUMNS = [
    ('diem_di', '起运地\n(Điểm đi)', 28),
    ('diem_den', '目的地\n(Điểm đến)', 34),
    ('xe_1_9t', '1.9T\n4380*1850*1900m', 16),
    ('xe_2_5t', '2.5T\n4.2x1.7x1.75m', 16),
    ('xe_3_5t', '3.5T\n3.1x1.6x1.6m', 16),
    ('xe_5t', '5T\n5.8x2.1x2.1m', 16),
    ('xe_8t', '8T\n7.3x2.3x2.3m', 16),
    ('xe_10t', '10T\n9.5x2.35x2.3m', 16),
    ('cont_20', 'CONT 20\n20ft DC', 15),
    ('cont_40', 'CONT 40\n40ft HC', 15),
    ('cont_45', 'CONT 45\n45ft HC', 15),
    ('xe_rao_14m', '高栏车 high-sided truck\nXe rào 14M', 18),
    ('xe_san_14m', '平坦车 flatbed truck\nXe sàn 14.3M', 18),
    ('xe_fooc_18m', '超地版 xe FOOC lùn\nFooc lùn 18M', 18),
    ('thoi_hieu', '时效(H)\n(Thời hiệu)', 14),
]

TRANSPORT_MATRIX_DATA = [
    {
        'diem_di': '春運貨場/Vietel物流园 Xuân Cương',
        'diem_den': '北歌尔工厂 Goertek Bắc Ninh - KCN Quế Võ/Nam Sơn Hạp Linh',
        'xe_1_9t': 2306000, 'xe_2_5t': 2622200, 'xe_3_5t': 3035800, 'xe_5t': 3455900,
        'xe_8t': 4110900, 'xe_10t': 4357600, 'cont_20': 4600000, 'cont_40': 5830000,
        'cont_45': 5830000, 'xe_rao_14m': 7579000, 'xe_san_14m': 7579000, 'xe_fooc_18m': 12826000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '新清 Tân Thanh',
        'diem_den': '北歌尔工厂 Goertek Bắc Ninh - KCN Quế Võ/Nam Sơn Hạp Linh',
        'xe_1_9t': 2407300, 'xe_2_5t': 2739400, 'xe_3_5t': 3174300, 'xe_5t': 3605100,
        'xe_8t': 4302500, 'xe_10t': 4570500, 'cont_20': 5100000, 'cont_40': 6413000,
        'cont_45': 6413000, 'xe_rao_14m': 8395200, 'xe_san_14m': 8395200, 'xe_fooc_18m': 13992000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '芒街 Móng Cái',
        'diem_den': '北歌尔工厂 Goertek Bắc Ninh - KCN Quế Võ/Nam Sơn Hạp Linh',
        'xe_1_9t': 2847300, 'xe_2_5t': 3248900, 'xe_3_5t': 3776500, 'xe_5t': 4253600,
        'xe_8t': 5136400, 'xe_10t': 5496900, 'cont_20': 8500000, 'cont_40': 11660000,
        'cont_45': 11660000, 'xe_rao_14m': 15741000, 'xe_san_14m': 15741000, 'xe_fooc_18m': 26818000,
        'thoi_hieu': '19h D+1'
    },
    {
        'diem_di': '峙马 Chi Ma',
        'diem_den': '北歌尔工厂 Goertek Bắc Ninh - KCN Quế Võ/Nam Sơn Hạp Linh',
        'xe_1_9t': 2452700, 'xe_2_5t': 2792000, 'xe_3_5t': 3236600, 'xe_5t': 3672200,
        'xe_8t': 4388800, 'xe_10t': 4666300, 'cont_20': 5300000, 'cont_40': 6646200,
        'cont_45': 6646200, 'xe_rao_14m': 8745000, 'xe_san_14m': 8745000, 'xe_fooc_18m': 14575000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '锦寮 - 友谊关各货场 Pô Chai - Bãi xe hàng HNQL',
        'diem_den': '北歌尔工厂 Goertek Bắc Ninh - KCN Quế Võ/Nam Sơn Hạp Linh',
        'xe_1_9t': 2366800, 'xe_2_5t': 2692500, 'xe_3_5t': 3118800, 'xe_5t': 3545400,
        'xe_8t': 4225900, 'xe_10t': 4485300, 'cont_20': 5100000, 'cont_40': 6413000,
        'cont_45': 6413000, 'xe_rao_14m': 8395200, 'xe_san_14m': 8395200, 'xe_fooc_18m': 13992000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '春運貨場/Vietel物流园 Xuân Cương',
        'diem_den': '北歌尔分拨仓 Kho phân bố Goertek Nam Sơn Hạp Linh',
        'xe_1_9t': 2306000, 'xe_2_5t': 2622200, 'xe_3_5t': 3035800, 'xe_5t': 3455900,
        'xe_8t': 4110900, 'xe_10t': 4357600, 'cont_20': 4600000, 'cont_40': 5830000,
        'cont_45': 5830000, 'xe_rao_14m': 7579000, 'xe_san_14m': 7579000, 'xe_fooc_18m': 12826000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '新清 Tân Thanh',
        'diem_den': '北歌尔分拨仓 Kho phân bố Goertek Nam Sơn Hạp Linh',
        'xe_1_9t': 2407300, 'xe_2_5t': 2739400, 'xe_3_5t': 3174300, 'xe_5t': 3605100,
        'xe_8t': 4302500, 'xe_10t': 4570500, 'cont_20': 5100000, 'cont_40': 6413000,
        'cont_45': 6413000, 'xe_rao_14m': 8395200, 'xe_san_14m': 8395200, 'xe_fooc_18m': 13992000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '芒街 Móng Cái',
        'diem_den': '北歌尔分拨仓 Kho phân bố Goertek Nam Sơn Hạp Linh',
        'xe_1_9t': 2847300, 'xe_2_5t': 3248900, 'xe_3_5t': 3776500, 'xe_5t': 4253600,
        'xe_8t': 5136400, 'xe_10t': 5496900, 'cont_20': 8500000, 'cont_40': 11660000,
        'cont_45': 11660000, 'xe_rao_14m': 15741000, 'xe_san_14m': 15741000, 'xe_fooc_18m': 26818000,
        'thoi_hieu': '19h D+1'
    },
    {
        'diem_di': '峙马 Chi Ma',
        'diem_den': '北歌尔分拨仓 Kho phân bố Goertek Nam Sơn Hạp Linh',
        'xe_1_9t': 2452700, 'xe_2_5t': 2792000, 'xe_3_5t': 3236600, 'xe_5t': 3672200,
        'xe_8t': 4388800, 'xe_10t': 4666300, 'cont_20': 5300000, 'cont_40': 6646200,
        'cont_45': 6646200, 'xe_rao_14m': 8745000, 'xe_san_14m': 8745000, 'xe_fooc_18m': 14575000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': '锦寮 - 友谊关各货场 Pô Chai - Bãi xe hàng HNQL',
        'diem_den': '北歌尔分拨仓 Kho phân bố Goertek Nam Sơn Hạp Linh',
        'xe_1_9t': 2366800, 'xe_2_5t': 2692500, 'xe_3_5t': 3118800, 'xe_5t': 3545400,
        'xe_8t': 4225900, 'xe_10t': 4485300, 'cont_20': 5100000, 'cont_40': 6413000,
        'cont_45': 6413000, 'xe_rao_14m': 8395200, 'xe_san_14m': 8395200, 'xe_fooc_18m': 13992000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': 'Cửa khẩu Hữu Nghị / Tân Thanh (Lạng Sơn)',
        'diem_den': 'KCN Quế Võ / VSIP / Đại Đồng Hoàn Sơn (Bắc Ninh)',
        'xe_1_9t': 2350000, 'xe_2_5t': 2650000, 'xe_3_5t': 3100000, 'xe_5t': 3500000,
        'xe_8t': 4200000, 'xe_10t': 4450000, 'cont_20': 5000000, 'cont_40': 6400000,
        'cont_45': 6400000, 'xe_rao_14m': 8300000, 'xe_san_14m': 8300000, 'xe_fooc_18m': 14000000,
        'thoi_hieu': '16h D+1'
    },
    {
        'diem_di': 'Cửa khẩu Hữu Nghị / Tân Thanh (Lạng Sơn)',
        'diem_den': 'KCN Yên Bình / Sông Công (Thái Nguyên)',
        'xe_1_9t': 2850000, 'xe_2_5t': 3200000, 'xe_3_5t': 3700000, 'xe_5t': 4200000,
        'xe_8t': 5000000, 'xe_10t': 5400000, 'cont_20': 6200000, 'cont_40': 7800000,
        'cont_45': 7800000, 'xe_rao_14m': 9800000, 'xe_san_14m': 9800000, 'xe_fooc_18m': 16500000,
        'thoi_hieu': '18h D+1'
    },
    {
        'diem_di': 'Cửa khẩu Hữu Nghị / Tân Thanh (Lạng Sơn)',
        'diem_den': 'KCN Đình Trám / Quang Châu / Vân Trung (Bắc Giang)',
        'xe_1_9t': 2100000, 'xe_2_5t': 2400000, 'xe_3_5t': 2800000, 'xe_5t': 3200000,
        'xe_8t': 3800000, 'xe_10t': 4100000, 'cont_20': 4600000, 'cont_40': 5800000,
        'cont_45': 5800000, 'xe_rao_14m': 7500000, 'xe_san_14m': 7500000, 'xe_fooc_18m': 12500000,
        'thoi_hieu': '14h D+1'
    },
    {
        'diem_di': 'Cửa khẩu Hữu Nghị / Tân Thanh (Lạng Sơn)',
        'diem_den': 'Hà Nội (KCN Thăng Long / Đài Tư / Gia Lâm / Long Biên)',
        'xe_1_9t': 2500000, 'xe_2_5t': 2850000, 'xe_3_5t': 3300000, 'xe_5t': 3800000,
        'xe_8t': 4500000, 'xe_10t': 4800000, 'cont_20': 5500000, 'cont_40': 7000000,
        'cont_45': 7000000, 'xe_rao_14m': 9000000, 'xe_san_14m': 9000000, 'xe_fooc_18m': 15000000,
        'thoi_hieu': '18h D+1'
    },
    {
        'diem_di': 'Cửa khẩu Tân Thanh (Lạng Sơn)',
        'diem_den': 'KCN Thuận Thành / Gia Bình (Bắc Ninh)',
        'xe_1_9t': 2450000, 'xe_2_5t': 2750000, 'xe_3_5t': 3200000, 'xe_5t': 3650000,
        'xe_8t': 4350000, 'xe_10t': 4600000, 'cont_20': 5200000, 'cont_40': 6500000,
        'cont_45': 6500000, 'xe_rao_14m': 8500000, 'xe_san_14m': 8500000, 'xe_fooc_18m': 14200000,
        'thoi_hieu': '16h D+1'
    }
]

TRANSPORT_NOTES = [
    "- Giá cước vận chuyển trên chưa bao gồm thuế giá trị gia tăng (VAT).",
    "- Phí lưu ca bắt đầu tính từ 15 giờ 00 phút ngày tiếp theo kể từ ngày đến nhận hàng/giao hàng:",
    "   + Phí lưu 02 ca đầu: 1.000.000 đ/ngày (xe tải) | 1.500.000 đ/ngày (xe container/fooc).",
    "   + Phí lưu từ ca 3 đến ca 5: 1.500.000 đ/ngày (xe tải) | 2.000.000 đ/ngày (xe container/fooc).",
    "   + Phí lưu ca thứ 6 trở đi: 2.000.000 đ/ngày.",
    "- Giá chưa bao gồm: phí bến bãi, bốc xếp, phí cân xe, nâng hạ hàng hóa, phí thủ tục xuất nhập cảnh.",
    "- Giá đã bao gồm phí cầu đường bộ, lương lái xe, chi phí nhiên liệu (dầu diesel).",
    "- Trường hợp hủy chuyến: Nếu xe đã điều đến bãi đóng hàng hoặc đi được nửa đường, khách hàng thanh toán 50% cước phí.",
    "- Khi giá dầu diesel có sự biến động +/- 10%, giá cước sẽ được hai bên điều chỉnh hiệp thương lại."
]

# ==============================================================================
# DỮ LIỆU CÁC HẠNG MỤC LOGISTICS KHÁC (BỐC XẾP, HẢI QUAN, KIỂM ĐỊNH, PHỤ PHÍ)
# ==============================================================================
BOCXEP_DATA = [
    ('Bốc xếp theo Trọng lượng (Hàng nặng / Sắt thép / Gạch / Máy)', 'Đơn giá tính theo kg (Hàng nặng)', 'kg', 180, 'Định mức nhân công dỡ hàng nặng tại kho bãi Lạng Sơn và Hub giao hàng.'),
    ('Bốc xếp theo Trọng lượng (Lô lớn ≥ 3 Tấn)', 'Đơn giá tính theo Tấn (Lô ≥ 3 Tấn)', 'Tấn', 180000, 'Áp dụng cho lô hàng từ 3 tấn trở lên, sang xe hoặc dỡ vào kho.'),
    ('Bốc xếp theo Thể tích / Khối (Hàng nhẹ cồng kềnh / Thùng Carton)', 'Đơn giá tính theo CBM / m³ (<250 kg/m³)', 'CBM', 75000, 'Hàng nhẹ thể tích (carton, bao bì, bông sợi). Bốc xếp bán kính ≤ 15m.'),
    ('Bốc xếp trọn gói Xe 5 Tấn (5T)', 'Trọn gói xe 5T (Sang hàng / Hạ kho)', 'Xe', 1100000, 'Căn cứ thực tế bốc dỡ hàng xe 5T tại kho Lạng Sơn (Lô CP 5.0).'),
    ('Bốc xếp trọn gói Xe 8 Tấn (8T)', 'Trọn gói xe 8T (Sang hàng / Hạ kho)', 'Xe', 1600000, 'Định mức nhân công bốc dỡ nguyên xe tải 8 tấn (thời gian dưới 3 giờ).'),
    ('Bốc xếp trọn gói Xe 15 Tấn (15T)', 'Trọn gói xe tải 3-4 chân', 'Xe', 2500000, 'Bốc dỡ hàng xe tải nặng 15T sang xe hoặc hạ kho tổng.'),
    ('Bốc xếp trọn gói Container 40 feet / 45 feet', 'Trọn gói Cont 40 / Cont 45', 'Cont', 4500000, 'Căn cứ dữ liệu thực tế bốc dỡ hàng nguyên container (Lô 2 tháng 09/2026).'),
    ('Sang hàng Pallet kéo tay (Kèm xe nâng tay)', 'Pallet tiêu chuẩn (1.0m x 1.2m)', 'Pallet', 180000, 'Căn cứ 5 đợt sang hàng pallet thực tế (Lô CP 2.0). Bao gồm kéo và cố định.'),
    ('Cơ giới sang hàng (Xe nâng hạ hàng nặng)', 'Xe nâng cơ giới (Forklift sang tải)', 'Xe', 900000, 'Thuê xe nâng cơ giới sang tải kiện hàng nặng trên 500kg tại bãi cửa khẩu.'),
    ('Mua phí sang tải cửa khẩu', 'Phí bến bãi sang tải cửa khẩu', 'Lượt', 180000, 'Vé bến bãi vào khu vực sang tải Lạng Sơn (Lô CP 5.0).'),
    ('Bốc xếp & Giao hàng chuỗi Keep Rise tại Hà Nội', 'Giao hàng tận nơi tại các điểm bán Hà Nội', 'Chuyến', 2500000, 'Thực tế bốc xếp giao hàng chuỗi Keep tại Hà Nội gồm xe nội thành và dỡ hàng.'),
    ('Bốc xếp & Giao hàng chuỗi Keep Rise tại TP. Hồ Chí Minh', 'Giao hàng tận nơi tại TP. Hồ Chí Minh', 'Chuyến', 2400000, 'Chi phí bốc xếp giao hàng thực tế tại kho và cửa hàng TP.HCM.'),
    ('Bốc xếp & Giao hàng chuỗi Keep Rise tại Nha Trang', 'Giao cửa hàng & dỡ hàng tại Nha Trang', 'Chuyến', 2000000, 'Chi phí thực tế bốc xếp lên cửa hàng và giao hàng tại Nha Trang.'),
    ('Bốc xếp & Giao hàng chuỗi Keep Rise tại Vũng Tàu', 'Giao cửa hàng & dỡ hàng tại Vũng Tàu', 'Chuyến', 1500000, 'Chi phí thực tế bốc xếp giao hàng tại Vũng Tàu.'),
    ('Bốc xếp & Giao hàng chuỗi Keep Rise tại Đà Nẵng', 'Giao cửa hàng & dỡ hàng tại Đà Nẵng', 'Chuyến', 1100000, 'Chi phí thực tế bốc xếp giao hàng tại Đà Nẵng.'),
    ('Thuê kho & Bốc xếp phân phối tại Đà Lạt', 'Thuê kho lưu hàng và bốc xếp Đà Lạt', 'Lô/Đợt', 9500000, 'Chi phí thuê kho và bốc xếp hàng phân phối tại Đà Lạt.')
]

HAIQUAN_DATA = [
    ('Dịch vụ Tờ khai Hải quan - Loại hình A11 (Nhập tiêu dùng / KD)', 'Loại hình A11 (Nhập kinh doanh thương mại)', 'Tờ khai', 4500000, 'Căn cứ các tờ khai A11 thực tế (Sunluxe). Bao gồm lập tờ khai nháp, truyền VNACCS, kiểm tra C/O, làm thủ tục hiện trường.'),
    ('Dịch vụ Tờ khai Hải quan - Loại hình A12 (Nhập KD sản xuất)', 'Loại hình A12 (Nhập sản xuất công nghiệp)', 'Tờ khai', 4500000, 'Căn cứ các tờ khai A12 thực tế (Sunluxe). Áp dụng doanh nghiệp nhập nguyên phụ liệu sản xuất.'),
    ('Dịch vụ Tờ khai Hải quan - Loại hình E21 (Nhập nguyên liệu gia công)', 'Loại hình E21 (Gia công cho thương nhân nước ngoài)', 'Tờ khai', 2200000, 'Căn cứ tờ khai E21 thực tế thông quan. Áp dụng hợp đồng gia công miễn thuế NK.'),
    ('Dịch vụ Tờ khai Hải quan - Loại hình H11 (Hàng phi mậu dịch / Quà biếu)', 'Loại hình H11 (Hàng phi mậu dịch / Hàng mẫu)', 'Tờ khai', 4000000, 'Căn cứ tờ khai H11 thực tế. Áp dụng cho hàng phi mậu dịch, hàng mẫu không thanh toán.'),
    ('Dịch vụ Tờ khai Hải quan - Loại hình G13 (Tạm nhập tái xuất / Dự án)', 'Loại hình G13 (Tạm nhập hàng trưng bày/triển lãm)', 'Tờ khai', 2200000, 'Căn cứ tờ khai G13 thực tế. Áp dụng hàng tạm nhập phục vụ sự kiện, triển lãm.'),
    ('Dịch vụ Tờ khai Hải quan - Loại hình A41 (Doanh nghiệp Chế xuất EPE)', 'Loại hình A41 (Khu phi thuế quan / DNCX)', 'Tờ khai', 1600000, 'Căn cứ tờ khai A41 thực tế. Doanh nghiệp chế xuất bán vào nội địa hoặc mua hàng nội địa.'),
    ('Dịch vụ Tờ khai Hải quan - Lô hàng lẻ / Cont 20 tiêu chuẩn', 'Tờ khai thông thường (Lô lẻ / 1 Cont 20 ≤ 3 dòng)', 'Tờ khai', 2500000, 'Căn cứ >30 đợt DVTK HQ thực tế trong hệ thống (Lô 1 tháng 08/2026).'),
    ('Phụ thu Tờ khai nhánh (Từ dòng hàng thứ 5 trở đi)', 'Tờ khai nhánh (>4 dòng hàng theo quy định VNACCS)', 'Tờ khai nhánh', 200000, 'Định mức phụ thu tờ khai nhánh trên hệ thống VNACCS khi lô hàng có trên 4 dòng.'),
    ('Phí tiếp nhận hồ sơ & Xử lý tờ khai quay đầu', 'Hồ sơ quay đầu chuyển cửa khẩu', 'Bộ hồ sơ', 500000, 'Căn cứ cước thực tế tiếp nhận hồ sơ quay đầu và làm thủ tục chuyển cửa khẩu (Cột 26 Báo Cáo Bán Hàng).'),
    ('Phí Hải quan giám sát tại bến bãi cửa khẩu', 'Hải quan giám sát bãi kiểm hóa', 'Xe/Cont', 400000, 'Căn cứ chi phí hải quan giám sát thực tế tại bãi kiểm hóa Tân Thanh/Hữu Nghị.')
]

KIEMDINH_DATA = [
    ('Kiểm tra chất lượng Nhà nước (Quatest) - Thiết bị điện / Gia dụng', 'Thiết bị điện & gia dụng (Lô ≤ 10 Tấn / 1 Cont)', 'Mẫu', 4000000, 'Căn cứ kiểm tra chất lượng thực tế thiết bị gia dụng tại Quatest 1 (Lô 08.2026).'),
    ('Kiểm tra chất lượng Quatest - Mẫu thử nghiệm phát sinh', 'Mẫu phát sinh cùng lô (+1 mẫu thử nghiệm)', 'Mẫu', 1200000, 'Áp dụng cho mẫu thử nghiệm phát sinh thêm cùng chủng loại trong 1 bộ hồ sơ đăng ký.'),
    ('Kiểm tra chất lượng Quatest - Hàng Dệt May / Quần Áo', 'Hàng dệt may thời trang (Theo Lô hàng Keep Rise)', 'Lô hàng', 5800000, 'Căn cứ chi phí Quatest thực tế hàng Keep Rise (thử nghiệm Formaldehyd & Azo).'),
    ('Kiểm tra chất lượng Quatest - Đồ chơi trẻ em / Đồ nhựa', 'Hợp quy Đồ chơi trẻ em & Nhựa (QCVN 3:2019/BKHCN)', 'Mẫu', 3800000, 'Định mức thử nghiệm chứng nhận hợp quy đồ chơi và đồ dùng tiếp xúc thực phẩm.'),
    ('Lấy mẫu kiểm tra chất lượng hiện trường nhanh tại Cửa khẩu', 'Lấy mẫu tại cửa khẩu (VN26040, VN26045...)', 'Lần', 1600000, 'Chi phí lấy mẫu sớm tại bãi kiểm hóa Lạng Sơn gửi về phòng lab (Lô CP 5.0).'),
    ('Phí chuẩn bị hồ sơ đăng ký kiểm tra chất lượng Nhà nước', 'Bộ hồ sơ đăng ký Cổng thông tin một cửa QG (NSW)', 'Bộ hồ sơ', 500000, 'Phí soạn hồ sơ, dịch thuật chứng chỉ và nộp NSW (Lô 08.2026).'),
    ('Kiểm dịch y tế phương tiện & hàng hóa (Việt Nam)', 'Kiểm dịch y tế cửa khẩu (Hữu Nghị / Tân Thanh)', 'Xe/Lô', 120000, 'Căn cứ 22 lượt kiểm dịch y tế thực tế tại cửa khẩu Hữu Nghị/Tân Thanh.'),
    ('Kiểm dịch y tế cửa khẩu Trung Quốc', 'Kiểm dịch y tế phương tiện phía TQ', 'Xe', 50000, 'Căn cứ 8 lượt kiểm dịch y tế xe phía Trung Quốc thực tế.'),
    ('Hải quan & Giám định đồng bộ dây chuyền máy móc', 'Giám định đồng bộ máy móc toàn bộ lô hàng', 'Lô hàng', 8000000, 'Căn cứ chi phí hải quan và giám định đồng bộ Vinacontrol/FCC (Lô 08.2026).'),
    ('Phí chuẩn bị hồ sơ giám định đồng bộ', 'Bộ hồ sơ kỹ thuật giám định đồng bộ', 'Bộ hồ sơ', 500000, 'Phí soạn thảo bộ hồ sơ kỹ thuật giám định đồng bộ dây chuyền.'),
    ('Chi phí xử lý kiểm định kỹ thuật đồng bộ tại hiện trường', 'Xử lý kiểm định đồng bộ cửa khẩu', 'Lô hàng', 3500000, 'Thực tế xử lý kiểm định đồng bộ tại cảng/cửa khẩu (Lô 08.2026).')
]

PHUPHI_DATA = [
    ('Phí Cơ Sở Hạ Tầng (CSHT) Cửa khẩu - Xe tải 5T - 8T', 'Xe tải thùng 5T - 8T (Biên lai UBND tỉnh)', 'Xe', 1380000, 'Căn cứ biên lai nộp phí sử dụng hạ tầng cửa khẩu Lạng Sơn (Lô 1, Lô 2).'),
    ('Phí Cơ Sở Hạ Tầng (CSHT) Cửa khẩu - Xe Container 40/45', 'Xe Container 40 / 45 feet', 'Cont', 2000000, 'Căn cứ biểu mức thu phí hạ tầng cửa khẩu áp dụng phương tiện container nhập khẩu.'),
    ('Vé xe ra vào bến bãi cửa khẩu (Tân Thanh / Hữu Nghị)', 'Vé cổng phương tiện bến xe cửa khẩu', 'Lượt', 250000, 'Vé xe bến bãi thực tế cổng kiểm soát Tân Thanh và Hữu Nghị.'),
    ('Dấu đầu xe & Tem kiểm soát phương tiện Trung Quốc', 'Tem xe & Dấu đầu xe TQ', 'Xe', 180000, 'Chi phí thực tế đóng dấu đầu xe và cấp tem kiểm soát phương tiện qua biên giới.'),
    ('Phí Lưu Ca Xe tải 5 Tấn - 8 Tấn (Quá 24h)', 'Xe tải thùng 5T - 8T (>24 giờ)', 'Ca/Ngày', 1000000, 'Dữ liệu thực tế phí lưu ca xe tải trong các lô hàng GIC (1.000.000 đ/ngày đêm).'),
    ('Phí Lưu Ca Xe Container 40 feet / 45 feet (Quá 24h)', 'Xe Container 40/45 (>24 giờ)', 'Ca/Ngày', 1500000, 'Định mức bồi hoàn lưu ca cho lái xe và đầu kéo container khi chờ thông quan quá hạn.'),
    ('Phụ phí phát sinh thêm điểm trả hàng (Nội tỉnh)', 'Điểm trả hàng thứ 2 trong cùng tỉnh/thành (≤20km)', 'Điểm', 500000, 'Chi phí phát sinh điều động xe trả thêm hàng tại điểm thứ 2 nội tỉnh.'),
    ('Phụ phí phát sinh thêm điểm trả hàng (Ngoại tỉnh lân cận)', 'Điểm trả hàng ngoại tỉnh (Cách tuyến >30km)', 'Điểm', 1000000, 'Thực tế phát sinh giao thêm 1 điểm tại Thái Bình/Hải Phòng (Lô 08.2026).'),
    ('Phí Hủy Xe sau khi đã điều xe vào bến đóng hàng', 'Hủy chuyến trong vòng 4 giờ trước giờ đóng', 'Chuyến', 1000000, 'Khoản phí bồi hoàn hủy xe đột xuất khi phương tiện đã tập kết bến bãi.'),
    ('Bảo hiểm Mọi Rủi Ro Hàng Hóa Vận Chuyển (ICC Clause A)', 'Bảo hiểm hàng hóa (0.08% Giá trị Invoice)', '% HĐ', '0.08% (Min 500k)', 'Bảo hiểm hàng hóa vận chuyển nội địa (All Risks). Bồi thường 100% rủi ro lật xe, đâm va, cháy nổ.'),
    ('Bảo hiểm Trách nhiệm Dân sự & Phương tiện Xe', 'Bảo hiểm phương tiện vận tải', 'Chuyến', 'Miễn phí', 'Đã bao gồm trong chi phí cước vận chuyển trọn gói của GIC Logistics.')
]

# ==============================================================================
# STYLING HELPERS CHO OPENPYXL
# ==============================================================================
FONT_FAMILY = "Times New Roman"

COLOR_HEADER_BG = "1F497D"      # Xanh Navy đậm sang trọng
COLOR_HEADER_FG = "FFFFFF"      # Trắng
COLOR_SUBHEADER_BG = "DCE6F1"   # Xanh nhạt
COLOR_ZEBRA_BG = "F9FAFB"       # Xám siêu nhạt cho dòng chẵn
COLOR_BORDER = "D9D9D9"         # Xám kẻ viền

thin_border_side = Side(border_style="thin", color="BFBFBF")
double_border_side = Side(border_style="double", color="1F497D")

cell_border = Border(
    left=thin_border_side,
    right=thin_border_side,
    top=thin_border_side,
    bottom=thin_border_side
)

header_border = Border(
    left=thin_border_side,
    right=thin_border_side,
    top=thin_border_side,
    bottom=Side(border_style="medium", color="1F497D")
)

def set_cell_style(cell, font_size=11, bold=False, italic=False, align="left", valign="center",
                   bg_color=None, text_color="000000", border=cell_border, num_format=None, wrap_text=True):
    cell.font = Font(name=FONT_FAMILY, size=font_size, bold=bold, italic=italic, color=text_color)
    cell.alignment = Alignment(horizontal=align, vertical=valign, wrap_text=wrap_text)
    if bg_color:
        cell.fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
    if border:
        cell.border = border
    if num_format:
        cell.number_format = num_format

def write_company_header(ws, title, max_col=15):
    """Vẽ thông tin công ty và tiêu đề bảng chuẩn như Mẫu báo giá.xlsx"""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=min(4, max_col))
    cell_a1 = ws.cell(1, 1, "Tên đơn vị: CÔNG TY TNHH TIẾP VẬN VÀ THƯƠNG MẠI GIC (GIC LOGISTICS)")
    set_cell_style(cell_a1, font_size=12, bold=True, border=None)

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=min(6, max_col))
    cell_a2 = ws.cell(2, 1, "Địa chỉ: Tầng 6, Tòa nhà Khâm Thiên, Đống Đa, Hà Nội / Chi nhánh Lạng Sơn, Hải Phòng")
    set_cell_style(cell_a2, font_size=11, border=None)

    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=min(3, max_col))
    cell_a3 = ws.cell(3, 1, "MST: 0109988776 | Hotline: 0912.345.678 | Email: contact@giclogistics.vn")
    set_cell_style(cell_a3, font_size=11, border=None)

    # Tiêu đề bảng
    ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=max_col)
    cell_title = ws.cell(4, 1, title.upper())
    set_cell_style(cell_title, font_size=16, bold=True, align="center", text_color="1F497D", border=None)
    ws.row_dimensions[4].height = 32


def generate_standard_quotation_excel():
    """
    Tạo toàn bộ File Excel Báo Giá Chuẩn Toàn Diện
    Gồm đầy đủ 6 sheet chuyên biệt:
    1. TongHop_Master: Tổng hợp tất cả bảng dịch vụ
    2. Cuoc_VanChuyen: Ma trận đa tải trọng xe (1.9T -> Fooc 18m)
    3. BocXep_NangHa: Đầy đủ kg, tấn, cbm, xe, địa phương
    4. ThuTuc_HaiQuan: Phân theo loại hình XNK (A11, A12, E21, H11...)
    5. KiemDinh_Quatest: Phân theo ngành hàng và chuyên ngành
    6. PhuPhi_BenBai_BH: Lưu ca, CSHT, bến bãi, bảo hiểm
    """
    wb = openpyxl.Workbook()

    # ==========================================================================
    # SHEET 1: CƯỚC VẬN CHUYỂN (MA TRẬN ĐÚNG CHUẨN MẪU BÁO GIÁ)
    # ==========================================================================
    ws_vc = wb.active
    ws_vc.title = "Cước Vận Chuyển"
    ws_vc.views.sheetView[0].showGridLines = True
    write_company_header(ws_vc, "BÁO GIÁ CƯỚC VẬN CHUYỂN ĐƯỜNG BỘ", max_col=len(TRANSPORT_COLUMNS))

    # Header columns (Row 5)
    ws_vc.row_dimensions[5].height = 38
    for col_idx, col_def in enumerate(TRANSPORT_COLUMNS, start=1):
        cell = ws_vc.cell(5, col_idx, col_def[1])
        set_cell_style(
            cell, font_size=10, bold=True, align="center", valign="center",
            bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border
        )
        ws_vc.column_dimensions[get_column_letter(col_idx)].width = col_def[2]

    # Matrix rows (Row 6 onwards)
    current_r = 6
    for row_idx, rdata in enumerate(TRANSPORT_MATRIX_DATA):
        bg = COLOR_ZEBRA_BG if row_idx % 2 == 1 else "FFFFFF"
        ws_vc.row_dimensions[current_r].height = 26

        for col_idx, col_def in enumerate(TRANSPORT_COLUMNS, start=1):
            key = col_def[0]
            val = rdata.get(key, "")
            cell = ws_vc.cell(current_r, col_idx)

            if isinstance(val, (int, float)):
                cell.value = val
                set_cell_style(cell, font_size=10, align="right", bg_color=bg, num_format="#,##0")
            else:
                cell.value = val
                align_h = "center" if key == "thoi_hieu" else "left"
                set_cell_style(cell, font_size=10, align=align_h, bg_color=bg)

        current_r += 1

    # Notes & Conditions
    current_r += 1
    cell_ghichu_title = ws_vc.cell(current_r, 1, "Ghi chú & Điều khoản:")
    set_cell_style(cell_ghichu_title, font_size=11, bold=True, border=None)

    for note in TRANSPORT_NOTES:
        ws_vc.merge_cells(start_row=current_r, start_column=2, end_row=current_r, end_column=len(TRANSPORT_COLUMNS))
        c_note = ws_vc.cell(current_r, 2, note)
        set_cell_style(c_note, font_size=10, italic=True, border=None)
        current_r += 1

    # ==========================================================================
    # SHEET 2: BỐC XẾP & NÂNG HẠ
    # ==========================================================================
    ws_bx = wb.create_sheet("Bốc Xếp & Nâng Hạ")
    ws_bx.views.sheetView[0].showGridLines = True
    write_company_header(ws_bx, "BÁO GIÁ DỊCH VỤ BỐC XẾP & NÂNG HẠ HÀNG HÓA", max_col=6)

    bx_headers = [("STT", 6), ("Nội Dung Hạng Mục Bốc Xếp", 42), ("Quy Cách Áp Dụng", 36), ("ĐVT", 12), ("Đơn Giá (VNĐ)", 18), ("Cơ Sở & Ghi Chú Kỹ Thuật", 50)]
    ws_bx.row_dimensions[5].height = 28
    for c_i, h in enumerate(bx_headers, start=1):
        cell = ws_bx.cell(5, c_i, h[0])
        set_cell_style(cell, font_size=11, bold=True, align="center", bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border)
        ws_bx.column_dimensions[get_column_letter(c_i)].width = h[1]

    r_idx = 6
    for i, item in enumerate(BOCXEP_DATA, start=1):
        bg = COLOR_ZEBRA_BG if i % 2 == 0 else "FFFFFF"
        ws_bx.row_dimensions[r_idx].height = 24
        ws_bx.cell(r_idx, 1, i)
        set_cell_style(ws_bx.cell(r_idx, 1), font_size=10, align="center", bg_color=bg)
        ws_bx.cell(r_idx, 2, item[0])
        set_cell_style(ws_bx.cell(r_idx, 2), font_size=10, bold=True, bg_color=bg)
        ws_bx.cell(r_idx, 3, item[1])
        set_cell_style(ws_bx.cell(r_idx, 3), font_size=10, bg_color=bg)
        ws_bx.cell(r_idx, 4, item[2])
        set_cell_style(ws_bx.cell(r_idx, 4), font_size=10, align="center", bg_color=bg)
        c_price = ws_bx.cell(r_idx, 5, item[3])
        set_cell_style(c_price, font_size=10, align="right", bold=True, bg_color=bg, num_format="#,##0")
        ws_bx.cell(r_idx, 6, item[4])
        set_cell_style(ws_bx.cell(r_idx, 6), font_size=9, italic=True, bg_color=bg)
        r_idx += 1

    # Điều khoản bốc xếp
    r_idx += 1
    ws_bx.cell(r_idx, 1, "Ghi chú:").font = Font(name=FONT_FAMILY, size=11, bold=True)
    ws_bx.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=6)
    ws_bx.cell(r_idx, 2, "- Giá chưa bao gồm VAT (8% hoặc 10%). Phạm vi di chuyển bốc xếp thủ công tiêu chuẩn ≤ 15m tính từ mép sàn xe.").font = Font(name=FONT_FAMILY, size=10, italic=True)
    r_idx += 1
    ws_bx.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=6)
    ws_bx.cell(r_idx, 2, "- Trường hợp hàng quá khổ, kiện máy trên 1 tấn yêu cầu sử dụng xe cẩu tự hành hoặc xe nâng chuyên dụng sẽ báo giá cụ thể theo vị trí hiện trường.").font = Font(name=FONT_FAMILY, size=10, italic=True)

    # ==========================================================================
    # SHEET 3: THỦ TỤC HẢI QUAN & TỜ KHAI
    # ==========================================================================
    ws_hq = wb.create_sheet("Thủ Tục Hải Quan")
    ws_hq.views.sheetView[0].showGridLines = True
    write_company_header(ws_hq, "BÁO GIÁ DỊCH VỤ THỦ TỤC HẢI QUAN & THÔNG QUAN", max_col=6)

    hq_headers = [("STT", 6), ("Loại Hình Tờ Khai / Dịch Vụ", 40), ("Mã / Phạm Vi Áp Dụng", 36), ("ĐVT", 14), ("Đơn Giá (VNĐ)", 18), ("Cơ Sở Dữ Liệu & Quy Định", 50)]
    ws_hq.row_dimensions[5].height = 28
    for c_i, h in enumerate(hq_headers, start=1):
        cell = ws_hq.cell(5, c_i, h[0])
        set_cell_style(cell, font_size=11, bold=True, align="center", bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border)
        ws_hq.column_dimensions[get_column_letter(c_i)].width = h[1]

    r_idx = 6
    for i, item in enumerate(HAIQUAN_DATA, start=1):
        bg = COLOR_ZEBRA_BG if i % 2 == 0 else "FFFFFF"
        ws_hq.row_dimensions[r_idx].height = 24
        ws_hq.cell(r_idx, 1, i)
        set_cell_style(ws_hq.cell(r_idx, 1), font_size=10, align="center", bg_color=bg)
        ws_hq.cell(r_idx, 2, item[0])
        set_cell_style(ws_hq.cell(r_idx, 2), font_size=10, bold=True, bg_color=bg)
        ws_hq.cell(r_idx, 3, item[1])
        set_cell_style(ws_hq.cell(r_idx, 3), font_size=10, bg_color=bg)
        ws_hq.cell(r_idx, 4, item[2])
        set_cell_style(ws_hq.cell(r_idx, 4), font_size=10, align="center", bg_color=bg)
        c_price = ws_hq.cell(r_idx, 5, item[3])
        set_cell_style(c_price, font_size=10, align="right", bold=True, bg_color=bg, num_format="#,##0")
        ws_hq.cell(r_idx, 6, item[4])
        set_cell_style(ws_hq.cell(r_idx, 6), font_size=9, italic=True, bg_color=bg)
        r_idx += 1

    r_idx += 1
    ws_hq.cell(r_idx, 1, "Ghi chú:").font = Font(name=FONT_FAMILY, size=11, bold=True)
    ws_hq.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=6)
    ws_hq.cell(r_idx, 2, "- Đơn giá dịch vụ hải quan chưa bao gồm các khoản thuế nhập khẩu, thuế GTGT hàng nhập khẩu và lệ phí nhà nước.").font = Font(name=FONT_FAMILY, size=10, italic=True)
    r_idx += 1
    ws_hq.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=6)
    ws_hq.cell(r_idx, 2, "- Đã bao gồm chi phí kiểm tra bộ chứng từ (Invoice, Packing List, C/O), lên tờ khai nháp và thông quan luồng Xanh/Vàng.").font = Font(name=FONT_FAMILY, size=10, italic=True)

    # ==========================================================================
    # SHEET 4: KIỂM ĐỊNH & KIỂM TRA CHUYÊN NGÀNH
    # ==========================================================================
    ws_kd = wb.create_sheet("Kiểm Định & Quatest")
    ws_kd.views.sheetView[0].showGridLines = True
    write_company_header(ws_kd, "BÁO GIÁ DỊCH VỤ KIỂM TRA CHUYÊN NGÀNH & KIỂM ĐỊNH", max_col=6)

    kd_headers = [("STT", 6), ("Hạng Mục Kiểm Tra Chuyên Ngành", 40), ("Quy Chuẩn / Mặt Hàng", 36), ("ĐVT", 14), ("Đơn Giá (VNĐ)", 18), ("Cơ Sở Dữ Liệu & Quy Định", 50)]
    ws_kd.row_dimensions[5].height = 28
    for c_i, h in enumerate(kd_headers, start=1):
        cell = ws_kd.cell(5, c_i, h[0])
        set_cell_style(cell, font_size=11, bold=True, align="center", bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border)
        ws_kd.column_dimensions[get_column_letter(c_i)].width = h[1]

    r_idx = 6
    for i, item in enumerate(KIEMDINH_DATA, start=1):
        bg = COLOR_ZEBRA_BG if i % 2 == 0 else "FFFFFF"
        ws_kd.row_dimensions[r_idx].height = 24
        ws_kd.cell(r_idx, 1, i)
        set_cell_style(ws_kd.cell(r_idx, 1), font_size=10, align="center", bg_color=bg)
        ws_kd.cell(r_idx, 2, item[0])
        set_cell_style(ws_kd.cell(r_idx, 2), font_size=10, bold=True, bg_color=bg)
        ws_kd.cell(r_idx, 3, item[1])
        set_cell_style(ws_kd.cell(r_idx, 3), font_size=10, bg_color=bg)
        ws_kd.cell(r_idx, 4, item[2])
        set_cell_style(ws_kd.cell(r_idx, 4), font_size=10, align="center", bg_color=bg)
        c_price = ws_kd.cell(r_idx, 5, item[3])
        set_cell_style(c_price, font_size=10, align="right", bold=True, bg_color=bg, num_format="#,##0")
        ws_kd.cell(r_idx, 6, item[4])
        set_cell_style(ws_kd.cell(r_idx, 6), font_size=9, italic=True, bg_color=bg)
        r_idx += 1

    r_idx += 1
    ws_kd.cell(r_idx, 1, "Ghi chú:").font = Font(name=FONT_FAMILY, size=11, bold=True)
    ws_kd.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=6)
    ws_kd.cell(r_idx, 2, "- Phí kiểm tra chất lượng áp dụng cho mẫu thông thường. Mẫu yêu cầu phá hủy hoặc thử nghiệm chuyên sâu sẽ theo biểu phí cơ quan kiểm định.").font = Font(name=FONT_FAMILY, size=10, italic=True)

    # ==========================================================================
    # SHEET 5: BẾN BÃI, PHỤ PHÍ & BẢO HIỂM
    # ==========================================================================
    ws_pp = wb.create_sheet("Bến Bãi & Phụ Phí")
    ws_pp.views.sheetView[0].showGridLines = True
    write_company_header(ws_pp, "BÁO GIÁ PHÍ BẾN BÃI, PHỤ PHÍ & BẢO HIỂM", max_col=6)

    pp_headers = [("STT", 6), ("Tên Khoản Mục Phí / Phụ Phí", 40), ("Điều Kiện Áp Dụng", 36), ("ĐVT", 14), ("Đơn Giá (VNĐ)", 18), ("Cơ Sở Quy Định & Ghi Chú", 50)]
    ws_pp.row_dimensions[5].height = 28
    for c_i, h in enumerate(pp_headers, start=1):
        cell = ws_pp.cell(5, c_i, h[0])
        set_cell_style(cell, font_size=11, bold=True, align="center", bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border)
        ws_pp.column_dimensions[get_column_letter(c_i)].width = h[1]

    r_idx = 6
    for i, item in enumerate(PHUPHI_DATA, start=1):
        bg = COLOR_ZEBRA_BG if i % 2 == 0 else "FFFFFF"
        ws_pp.row_dimensions[r_idx].height = 24
        ws_pp.cell(r_idx, 1, i)
        set_cell_style(ws_pp.cell(r_idx, 1), font_size=10, align="center", bg_color=bg)
        ws_pp.cell(r_idx, 2, item[0])
        set_cell_style(ws_pp.cell(r_idx, 2), font_size=10, bold=True, bg_color=bg)
        ws_pp.cell(r_idx, 3, item[1])
        set_cell_style(ws_pp.cell(r_idx, 3), font_size=10, bg_color=bg)
        ws_pp.cell(r_idx, 4, item[2])
        set_cell_style(ws_pp.cell(r_idx, 4), font_size=10, align="center", bg_color=bg)
        c_price = ws_pp.cell(r_idx, 5, item[3])
        if isinstance(item[3], (int, float)):
            set_cell_style(c_price, font_size=10, align="right", bold=True, bg_color=bg, num_format="#,##0")
        else:
            set_cell_style(c_price, font_size=10, align="center", bold=True, bg_color=bg)
        ws_pp.cell(r_idx, 6, item[4])
        set_cell_style(ws_pp.cell(r_idx, 6), font_size=9, italic=True, bg_color=bg)
        r_idx += 1

    return wb


def export_quotation_to_excel(quote):
    """
    Xuất một Bảng Báo Giá cụ thể của khách hàng sang file Excel chuyên nghiệp
    """
    import json
    items = []
    try:
        items = json.loads(quote.items_json or '[]')
    except Exception:
        pass

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"BaoGia_{quote.quote_code}"
    ws.views.sheetView[0].showGridLines = True

    # 1. Company Header
    write_company_header(ws, f"BẢNG BÁO GIÁ DỊCH VỤ LOGISTICS - {quote.quote_code}", max_col=7)

    # 2. Customer Info Box (Row 6 - 9)
    ws.merge_cells("A6:D6")
    ws.cell(6, 1, f"Kính gửi Quý khách: {quote.customer_name}").font = Font(name=FONT_FAMILY, size=11, bold=True)
    ws.merge_cells("E6:G6")
    ws.cell(6, 5, f"Mã báo giá: {quote.quote_code}").font = Font(name=FONT_FAMILY, size=11, bold=True)

    ws.merge_cells("A7:D7")
    ws.cell(7, 1, f"Người liên hệ: {quote.contact_person or '-'}").font = Font(name=FONT_FAMILY, size=10)
    ws.merge_cells("E7:G7")
    created_str = quote.created_at.strftime('%d/%m/%Y') if quote.created_at else '-'
    ws.cell(7, 5, f"Ngày lập: {created_str}").font = Font(name=FONT_FAMILY, size=10)

    ws.merge_cells("A8:D8")
    ws.cell(8, 1, f"Số điện thoại: {quote.phone or '-'}").font = Font(name=FONT_FAMILY, size=10)
    ws.merge_cells("E8:G8")
    ws.cell(8, 5, f"Thời hạn hiệu lực: {quote.valid_days or 15} ngày").font = Font(name=FONT_FAMILY, size=10)

    # 3. Table Headers (Row 10)
    headers = [
        ("STT", 6),
        ("Nội Dung Dịch Vụ / Tuyến Đường", 38),
        ("Quy Cách / Loại Xe", 25),
        ("ĐVT", 10),
        ("SL", 8),
        ("Đơn Giá (VNĐ)", 16),
        ("Thành Tiền (VNĐ)", 18)
    ]
    ws.row_dimensions[10].height = 26
    for c_i, h in enumerate(headers, start=1):
        cell = ws.cell(10, c_i, h[0])
        set_cell_style(cell, font_size=11, bold=True, align="center", bg_color=COLOR_HEADER_BG, text_color=COLOR_HEADER_FG, border=header_border)
        ws_col_letter = get_column_letter(c_i)
        ws.column_dimensions[ws_col_letter].width = h[1]

    # 4. Item Rows
    current_r = 11
    for idx, it in enumerate(items, start=1):
        bg = COLOR_ZEBRA_BG if idx % 2 == 0 else "FFFFFF"
        ws.row_dimensions[current_r].height = 24

        qty = float(it.get('quantity') or 1)
        price = float(it.get('unit_price') or 0)
        total = qty * price

        ws.cell(current_r, 1, idx)
        set_cell_style(ws.cell(current_r, 1), font_size=10, align="center", bg_color=bg)

        ws.cell(current_r, 2, it.get('name', ''))
        set_cell_style(ws.cell(current_r, 2), font_size=10, bold=True, bg_color=bg)

        ws.cell(current_r, 3, it.get('spec', '-'))
        set_cell_style(ws.cell(current_r, 3), font_size=10, bg_color=bg)

        ws.cell(current_r, 4, it.get('unit', 'Chuyến'))
        set_cell_style(ws.cell(current_r, 4), font_size=10, align="center", bg_color=bg)

        ws.cell(current_r, 5, qty)
        set_cell_style(ws.cell(current_r, 5), font_size=10, align="center", bg_color=bg)

        ws.cell(current_r, 6, price)
        set_cell_style(ws.cell(current_r, 6), font_size=10, align="right", bg_color=bg, num_format="#,##0")

        ws.cell(current_r, 7, total)
        set_cell_style(ws.cell(current_r, 7), font_size=10, align="right", bold=True, bg_color=bg, num_format="#,##0")

        current_r += 1

    # 5. Summary (Subtotal, VAT, Total)
    ws.merge_cells(start_row=current_r, start_column=1, end_row=current_r, end_column=6)
    c_sub_label = ws.cell(current_r, 1, "Tổng cộng cước dịch vụ (chưa VAT):")
    set_cell_style(c_sub_label, font_size=10, bold=True, align="right", bg_color="F2F2F2")
    c_sub_val = ws.cell(current_r, 7, quote.subtotal or 0)
    set_cell_style(c_sub_val, font_size=10, bold=True, align="right", bg_color="F2F2F2", num_format="#,##0")
    current_r += 1

    ws.merge_cells(start_row=current_r, start_column=1, end_row=current_r, end_column=6)
    c_vat_label = ws.cell(current_r, 1, f"Thuế GTGT ({quote.vat_percent or 10.0:.0f}%):")
    set_cell_style(c_vat_label, font_size=10, align="right", bg_color="F2F2F2")
    c_vat_val = ws.cell(current_r, 7, quote.vat_amount or 0)
    set_cell_style(c_vat_val, font_size=10, align="right", bg_color="F2F2F2", num_format="#,##0")
    current_r += 1

    ws.merge_cells(start_row=current_r, start_column=1, end_row=current_r, end_column=6)
    c_tot_label = ws.cell(current_r, 1, "TỔNG GIÁ TRỊ THANH TOÁN (ĐÃ VAT):")
    set_cell_style(c_tot_label, font_size=11, bold=True, align="right", bg_color=COLOR_SUBHEADER_BG, text_color="1F497D")
    c_tot_val = ws.cell(current_r, 7, quote.total_amount or 0)
    set_cell_style(c_tot_val, font_size=11, bold=True, align="right", bg_color=COLOR_SUBHEADER_BG, text_color="1F497D", num_format="#,##0")
    current_r += 1

    # 6. Notes & Terms
    current_r += 1
    ws.cell(current_r, 1, "Ghi chú & Điều khoản chung:").font = Font(name=FONT_FAMILY, size=11, bold=True)
    current_r += 1

    terms = [
        "- Báo giá có hiệu lực trong vòng " + str(quote.valid_days or 15) + " ngày kể từ ngày ban hành.",
        "- Giá cước đã bao gồm chi phí nhiên liệu, cầu đường, lương tài xế theo đúng lộ trình thỏa thuận.",
        "- Phí lưu ca xe tính từ 15h00 ngày tiếp theo kể từ khi xe đến điểm nhận/giao (Xe tải: 1.000.000 đ/ngày; Container: 1.500.000 đ/ngày).",
        "- Giá chưa bao gồm phí bốc xếp, nâng hạ, chi phí kiểm tra chất lượng nếu không được liệt kê cụ thể trong bảng trên.",
        "- Trường hợp giá dầu diesel biến động trên 10%, hai bên sẽ hiệp thương điều chỉnh lại cước phù hợp thực tế."
    ]
    if quote.notes:
        terms.insert(0, f"- Ghi chú riêng: {quote.notes}")

    for t in terms:
        ws.merge_cells(start_row=current_r, start_column=1, end_row=current_r, end_column=7)
        c_term = ws.cell(current_r, 1, t)
        set_cell_style(c_term, font_size=9, italic=True, border=None)
        current_r += 1

    # 7. Signatures
    current_r += 2
    ws.merge_cells(start_row=current_r, start_column=1, end_row=current_r, end_column=3)
    ws.cell(current_r, 1, "ĐẠI DIỆN KHÁCH HÀNG\n(Ký & Ghi rõ họ tên)").alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.cell(current_r, 1).font = Font(name=FONT_FAMILY, size=10, bold=True)

    ws.merge_cells(start_row=current_r, start_column=5, end_row=current_r, end_column=7)
    ws.cell(current_r, 5, "ĐẠI DIỆN GIC LOGISTICS\n(Người lập báo giá)").alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.cell(current_r, 5).font = Font(name=FONT_FAMILY, size=10, bold=True)

    return wb
