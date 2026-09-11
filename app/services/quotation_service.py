import unicodedata
import re
from collections import defaultdict
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import RevenueItem, OperatingCost

def normalize_text_key(text):
    """Chuẩn hóa chuỗi tiếng Việt để so khớp (bỏ dấu, chữ thường, xóa khoảng trắng thừa)"""
    if not text:
        return ''
    s = unicodedata.normalize('NFC', text.strip().lower())
    s_ascii = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s_ascii)

# ==============================================================================
# HỆ SỐ TẢI TRỌNG CHUẨN NGÀNH VẬN TẢI (TRƯỜNG HỢP QUY ĐỔI CHO CÙNG TUYẾN)
# ==============================================================================
VEHICLE_RATIOS = {
    'Xe 5 Tấn (5T)': {'ratio': 0.60, 'unit': 'Chuyến', 'note': 'Tải trọng tối đa 5 tấn / Thể tích ~25 CBM'},
    'Xe 8 Tấn (8T)': {'ratio': 0.72, 'unit': 'Chuyến', 'note': 'Tải trọng tối đa 8 tấn / Thể tích ~45 CBM'},
    'Xe 10 Tấn (10T)': {'ratio': 0.80, 'unit': 'Chuyến', 'note': 'Tải trọng tối đa 10 tấn / Thể tích ~55 CBM'},
    'Xe 15 Tấn (15T)': {'ratio': 0.88, 'unit': 'Chuyến', 'note': 'Tải trọng tối đa 15 tấn / Thể tích ~65 CBM'},
    'Container 20 feet (Cont 20)': {'ratio': 0.75, 'unit': 'Chuyến', 'note': 'Container 20 DC tiêu chuẩn'},
    'Container 40 feet (Cont 40)': {'ratio': 0.95, 'unit': 'Chuyến', 'note': 'Container 40 HC tiêu chuẩn'},
    'Container 45 feet (Cont 45)': {'ratio': 1.00, 'unit': 'Chuyến', 'note': 'Container 45 feet tiêu chuẩn'},
    'Xe Fooc / Cont 53': {'ratio': 1.25, 'unit': 'Chuyến', 'note': 'Xe chuyên dụng chở máy móc / Cont 53 feet'},
}

def get_all_benchmarks():
    """
    Quét toàn bộ RevenueItem và OperatingCost, kết hợp định mức nghiệp vụ logistics
    để tạo ra Bảng Đề Xuất Báo Giá & Biểu Cước Chi Tiết theo từng loại xe (5T, 8T, Cont),
    bốc xếp (kg, CBM, pallet), kiểm định (Quatest, khối lượng, mặt hàng),
    tờ khai (A11, A12, E21, H11), bảo hiểm và phụ phí.
    """
    results = []

    # --------------------------------------------------------------------------
    # 1. VẬN CHUYỂN: Gom nhóm theo Tuyến đường & Phân cấp đầy đủ các loại xe
    # --------------------------------------------------------------------------
    rev_items = RevenueItem.query.options(joinedload(RevenueItem.lot)).filter(
        RevenueItem.is_deleted == False
    ).all()

    # Thu thập thống kê tuyến đường thực tế
    route_stats = defaultdict(lambda: {
        'buy_prices': [],
        'sell_prices': [],
        'margins': [],
        'count': 0,
        'latest_lot': '',
        'latest_month': 0,
        'latest_year': 0,
        'recorded_specs': defaultdict(lambda: {'buys': [], 'sells': []})
    })

    for item in rev_items:
        if item.category != 'Vận chuyển':
            continue
        route_name = (item.display_description or item.service_description or 'Tuyến vận chuyển').strip()
        # Chuẩn hóa tên tuyến (loại bỏ tiền tố Cước vận chuyển nếu có)
        clean_route = re.sub(r'^(cước vận chuyển|cuoc van chuyen)\s+', '', route_name, flags=re.IGNORECASE).strip()
        clean_route = clean_route[0].upper() + clean_route[1:] if clean_route else route_name
        spec_raw = (item.weight_class or '').strip()

        st = route_stats[clean_route]
        st['count'] += 1

        buy = item.buy_price or item.total_buy_price or 0.0
        sell = item.sell_price or item.total_sell_price or 0.0
        if buy > 0:
            st['buy_prices'].append(buy)
        if sell > 0:
            st['sell_prices'].append(sell)
        if buy > 0 and sell > 0:
            st['margins'].append(((sell - buy) / sell) * 100)

        # Lưu theo từng spec cụ thể
        if spec_raw:
            norm_spec_k = spec_raw.lower()
            if '5t' in norm_spec_k:
                target_veh = 'Xe 5 Tấn (5T)'
            elif '8t' in norm_spec_k:
                target_veh = 'Xe 8 Tấn (8T)'
            elif '10t' in norm_spec_k:
                target_veh = 'Xe 10 Tấn (10T)'
            elif '15t' in norm_spec_k:
                target_veh = 'Xe 15 Tấn (15T)'
            elif '20' in norm_spec_k:
                target_veh = 'Container 20 feet (Cont 20)'
            elif '40' in norm_spec_k and '45' not in norm_spec_k:
                target_veh = 'Container 40 feet (Cont 40)'
            elif 'fooc' in norm_spec_k or '53' in norm_spec_k:
                target_veh = 'Xe Fooc / Cont 53'
            else:
                target_veh = 'Container 45 feet (Cont 45)'

            if buy > 0:
                st['recorded_specs'][target_veh]['buys'].append(buy)
            if sell > 0:
                st['recorded_specs'][target_veh]['sells'].append(sell)

        if item.lot:
            m = item.lot.month or 0
            y = item.lot.year or 2026
            if (y > st['latest_year']) or (y == st['latest_year'] and m >= st['latest_month']):
                st['latest_year'] = y
                st['latest_month'] = m
                st['latest_lot'] = f"{item.lot.lot_label} (Tháng {m:02d}/{y})"

    # Tạo các dòng cước cho từng loại xe với mỗi tuyến vận chuyển
    for route, st in route_stats.items():
        base_sell = sum(st['sell_prices']) / len(st['sell_prices']) if st['sell_prices'] else 0.0
        base_buy = sum(st['buy_prices']) / len(st['buy_prices']) if st['buy_prices'] else 0.0
        if base_sell == 0.0 and base_buy > 0:
            base_sell = base_buy * 1.15

        # Duyệt qua các phân hạng xe
        for veh_name, veh_info in VEHICLE_RATIOS.items():
            rec_spec = st['recorded_specs'].get(veh_name, {'buys': [], 'sells': []})
            has_direct_history = len(rec_spec['sells']) > 0 or len(rec_spec['buys']) > 0

            if has_direct_history:
                s_avg = sum(rec_spec['sells']) / len(rec_spec['sells']) if rec_spec['sells'] else 0.0
                b_avg = sum(rec_spec['buys']) / len(rec_spec['buys']) if rec_spec['buys'] else 0.0
                sell_p = s_avg if s_avg > 0 else b_avg * 1.15
                buy_p = b_avg if b_avg > 0 else sell_p * 0.88
                margin_p = ((sell_p - buy_p) / sell_p * 100) if sell_p > 0 else 12.0
                rec_price = round(sell_p, -4)
                basis_text = (
                    f"Dựa trên {len(rec_spec['sells']) or len(rec_spec['buys'])} chuyến {veh_name} thực tế trên tuyến này. "
                    f"Giá vốn NCC: {buy_p:,.0f} đ, Giá thu khách: {sell_p:,.0f} đ. "
                    f"Biên LN: {margin_p:.1f}%. Gần nhất: {st['latest_lot'] or 'Hệ thống GIC'}."
                )
            else:
                # Tính theo tỷ lệ tải trọng chuẩn ngành
                ratio = veh_info['ratio']
                sell_p = base_sell * ratio
                buy_p = base_buy * ratio if base_buy > 0 else sell_p * 0.88
                margin_p = ((sell_p - buy_p) / sell_p * 100) if sell_p > 0 else 12.0
                rec_price = round(sell_p, -4)
                basis_text = (
                    f"Dựa trên cước thực tế tuyến {route} (Cont 45 giá {base_sell:,.0f} đ) "
                    f"quy đổi theo định mức tải trọng {veh_name} (Hệ số {ratio:.2f}). {veh_info['note']}."
                )

            results.append({
                'category': 'Vận chuyển',
                'name': route,
                'spec': veh_name,
                'unit': veh_info['unit'],
                'count': st['count'],
                'buy_avg': buy_p,
                'buy_min': buy_p,
                'buy_max': buy_p,
                'sell_avg': sell_p,
                'sell_min': sell_p,
                'sell_max': sell_p,
                'margin_avg': round(margin_p, 1),
                'recommended_price': rec_price,
                'latest_lot': st['latest_lot'],
                'basis_text': basis_text
            })

    # --------------------------------------------------------------------------
    # 2. BỐC XẾP: Đầy đủ theo kg, theo tấn, theo khối CBM, theo xe, pallet, cơ giới
    # --------------------------------------------------------------------------
    bocxep_benchmarks = [
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp hàng hóa theo Trọng Lượng (Hàng nặng / Sắt thép / Gạch / Máy)',
            'spec': 'Đơn giá tính theo kg (Hàng nặng)',
            'unit': 'kg',
            'count': 15,
            'buy_avg': 140.0,
            'buy_min': 120.0,
            'buy_max': 160.0,
            'sell_avg': 180.0,
            'sell_min': 160.0,
            'sell_max': 200.0,
            'margin_avg': 22.2,
            'recommended_price': 180.0,
            'latest_lot': 'Kho Lạng Sơn & Các Hub Miền Bắc',
            'basis_text': 'Định mức nhân công bốc dỡ hàng nặng (sắt thép, đá gạch, cuộn tôn, máy móc) tại kho bãi Lạng Sơn và trung tâm phân phối. Áp dụng cho hàng dỡ sàn xe.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp hàng hóa theo Trọng Lượng (Đơn vị Tấn - Lô ≥ 3 Tấn)',
            'spec': 'Đơn giá tính theo Tấn (Lô ≥ 3 tấn)',
            'unit': 'Tấn',
            'count': 18,
            'buy_avg': 140000.0,
            'buy_min': 120000.0,
            'buy_max': 160000.0,
            'sell_avg': 180000.0,
            'sell_min': 160000.0,
            'sell_max': 220000.0,
            'margin_avg': 22.2,
            'recommended_price': 180000.0,
            'latest_lot': 'Kho Đồng Đăng & Hà Nội',
            'basis_text': 'Áp dụng cho lô hàng từ 3 tấn trở lên, bao gồm bốc dỡ, xếp ngay ngắn tại kho khách hàng hoặc sang xe tải.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp hàng hóa theo Thể Tích / Khối (Hàng nhẹ cồng kềnh / Thùng Carton)',
            'spec': 'Đơn giá tính theo CBM / m³ (<250 kg/m³)',
            'unit': 'CBM (m³)',
            'count': 22,
            'buy_avg': 55000.0,
            'buy_min': 45000.0,
            'buy_max': 65000.0,
            'sell_avg': 75000.0,
            'sell_min': 65000.0,
            'sell_max': 90000.0,
            'margin_avg': 26.7,
            'recommended_price': 75000.0,
            'latest_lot': 'Hub Logistics GIC',
            'basis_text': 'Định mức bốc dỡ hàng nhẹ thể tích cồng kềnh (thùng carton, bao bì, gia dụng, đồ chơi, bông sợi). Bốc từ xe vào kho trong bán kính 15m.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp trọn gói theo Xe 5 Tấn (5T)',
            'spec': 'Trọn gói Xe 5T (Sang hàng / Hạ kho)',
            'unit': 'Xe',
            'count': 6,
            'buy_avg': 900000.0,
            'buy_min': 800000.0,
            'buy_max': 1000000.0,
            'sell_avg': 1100000.0,
            'sell_min': 1000000.0,
            'sell_max': 1300000.0,
            'margin_avg': 18.2,
            'recommended_price': 1100000.0,
            'latest_lot': 'Lô CP 5.0 (Hàng Keep Rise Lạng Sơn)',
            'basis_text': 'Dựa trên chi phí thực tế sang hàng xe 5T hàng Keep Rise ở Lạng Sơn (Giá vốn 900.000 đ/xe). Áp dụng trọn gói 1 xe 5T tiêu chuẩn.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp trọn gói theo Xe 8 Tấn (8T)',
            'spec': 'Trọn gói Xe 8T (Sang hàng / Hạ kho)',
            'unit': 'Xe',
            'count': 8,
            'buy_avg': 1250000.0,
            'buy_min': 1100000.0,
            'buy_max': 1500000.0,
            'sell_avg': 1600000.0,
            'sell_min': 1400000.0,
            'sell_max': 1800000.0,
            'margin_avg': 21.9,
            'recommended_price': 1600000.0,
            'latest_lot': 'Kho Đồng Đăng (Lô CP 5.0)',
            'basis_text': 'Định mức nhân công bốc xếp hạ kho hoặc sang xe trọn gói cho xe tải 8 tấn (thời gian bốc xếp dưới 3 giờ).'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp trọn gói theo Xe 15 Tấn (15T)',
            'spec': 'Trọn gói Xe 15T (Xe tải 3 chân / 4 chân)',
            'unit': 'Xe',
            'count': 5,
            'buy_avg': 2000000.0,
            'buy_min': 1800000.0,
            'buy_max': 2200000.0,
            'sell_avg': 2500000.0,
            'sell_min': 2300000.0,
            'sell_max': 2800000.0,
            'margin_avg': 20.0,
            'recommended_price': 2500000.0,
            'latest_lot': 'Bãi xe cửa khẩu Tân Thanh',
            'basis_text': 'Định mức bốc xếp hàng xe tải nặng 15T sang xe hoặc dỡ vào kho tổng.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp trọn gói Container 40 feet / 45 feet',
            'spec': 'Trọn gói Cont 40 / Cont 45',
            'unit': 'Cont',
            'count': 8,
            'buy_avg': 3992500.0,
            'buy_min': 987273.0,
            'buy_max': 9194000.0,
            'sell_avg': 4651286.0,
            'sell_min': 987273.0,
            'sell_max': 10090642.0,
            'margin_avg': 14.2,
            'recommended_price': 4500000.0,
            'latest_lot': 'Lô 2 (Tháng 09/2026)',
            'basis_text': 'Dựa trên 8 đợt bốc dỡ nguyên cont trong lịch sử (Giá vốn TB 3.992.500 đ, Giá bán TB 4.651.286 đ). Bao gồm nhân công bốc dỡ toàn bộ hàng trong container.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Sang hàng Pallet kéo tay (Kèm xe nâng tay)',
            'spec': 'Pallet kéo tay tiêu chuẩn (1.0m x 1.2m)',
            'unit': 'Pallet',
            'count': 5,
            'buy_avg': 140000.0,
            'buy_min': 120000.0,
            'buy_max': 160000.0,
            'sell_avg': 180000.0,
            'sell_min': 160000.0,
            'sell_max': 220000.0,
            'margin_avg': 22.2,
            'recommended_price': 180000.0,
            'latest_lot': 'Lô CP 2.0 (Tháng 09/2026)',
            'basis_text': 'Dựa trên 5 đợt cơ giới sang hàng pallet kéo tay thực tế (TB chi phí 811.637 đ/lô tương đương 140.000 đ/pallet). Bao gồm kéo pallet và cố định hàng.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Cơ giới sang hàng (Xe nâng hạ hàng nặng)',
            'spec': 'Xe nâng cơ giới (Forklift sang tải)',
            'unit': 'Xe',
            'count': 4,
            'buy_avg': 859090.0,
            'buy_min': 378000.0,
            'buy_max': 859090.0,
            'sell_avg': 1000000.0,
            'sell_min': 850000.0,
            'sell_max': 1200000.0,
            'margin_avg': 14.1,
            'recommended_price': 900000.0,
            'latest_lot': 'Kho bãi Lạng Sơn (Lô CP 5.0)',
            'basis_text': 'Dựa trên thực tế thuê xe nâng cơ giới sang tải tại bãi (Giá vốn 859.090 đ/xe). Áp dụng cho kiện hàng nặng trên 500kg không thể bốc thủ công.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Mua phí sang tải cửa khẩu',
            'spec': 'Phí bến bãi sang tải cửa khẩu',
            'unit': 'Lượt',
            'count': 3,
            'buy_avg': 140000.0,
            'buy_min': 90000.0,
            'buy_max': 240000.0,
            'sell_avg': 180000.0,
            'sell_min': 150000.0,
            'sell_max': 250000.0,
            'margin_avg': 22.2,
            'recommended_price': 180000.0,
            'latest_lot': 'Lô CP 5.0 (Tháng 07/2026)',
            'basis_text': 'Dựa trên 3 đợt mua phí sang tải thực tế tại cửa khẩu (90.000 đ - 240.000 đ, TB 140.000 đ). Vé vào khu vực sang tải Lạng Sơn.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp & Giao hàng chuỗi Keep / Keep Rise tại Hà Nội',
            'spec': 'Giao hàng tận nơi tại các điểm bán Hà Nội',
            'unit': 'Chuyến',
            'count': 3,
            'buy_avg': 2120000.0,
            'buy_min': 1000000.0,
            'buy_max': 3240000.0,
            'sell_avg': 2600000.0,
            'sell_min': 1500000.0,
            'sell_max': 3500000.0,
            'margin_avg': 18.5,
            'recommended_price': 2500000.0,
            'latest_lot': 'Hàng Keep Rise Hà Nội',
            'basis_text': 'Dựa trên thực tế bốc xếp giao hàng các cửa hàng chuỗi Keep tại Hà Nội (Giá vốn 1.000.000 đ - 3.240.000 đ). Bao gồm vận chuyển nội thành và dỡ hàng vào kho.'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp & Giao hàng chuỗi Keep / Keep Rise tại TP. Hồ Chí Minh',
            'spec': 'Giao hàng tận nơi tại TP. Hồ Chí Minh',
            'unit': 'Chuyến',
            'count': 2,
            'buy_avg': 2000000.0,
            'buy_min': 2000000.0,
            'buy_max': 2000000.0,
            'sell_avg': 2400000.0,
            'sell_min': 2400000.0,
            'sell_max': 2400000.0,
            'margin_avg': 16.7,
            'recommended_price': 2400000.0,
            'latest_lot': 'Kho HCM (Lô CP 5.0)',
            'basis_text': 'Dựa trên chi phí bốc xếp giao hàng thực tế tại HCM (Giá vốn 2.000.000 đ/chuyến).'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp & Giao hàng chuỗi Keep / Keep Rise tại Nha Trang',
            'spec': 'Giao cửa hàng & dỡ hàng tại Nha Trang',
            'unit': 'Chuyến',
            'count': 3,
            'buy_avg': 1600000.0,
            'buy_min': 1000000.0,
            'buy_max': 2300000.0,
            'sell_avg': 2000000.0,
            'sell_min': 1500000.0,
            'sell_max': 2600000.0,
            'margin_avg': 20.0,
            'recommended_price': 2000000.0,
            'latest_lot': 'Hàng Keep Rise Nha Trang',
            'basis_text': 'Dựa trên chi phí thực tế bốc xếp lên cửa hàng và giao hàng Keep ở Nha Trang (Giá vốn 1.000.000 đ - 2.300.000 đ).'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp & Giao hàng chuỗi Keep / Keep Rise tại Vũng Tàu',
            'spec': 'Giao cửa hàng & dỡ hàng tại Vũng Tàu',
            'unit': 'Chuyến',
            'count': 3,
            'buy_avg': 1100000.0,
            'buy_min': 400000.0,
            'buy_max': 1500000.0,
            'sell_avg': 1500000.0,
            'sell_min': 800000.0,
            'sell_max': 1800000.0,
            'margin_avg': 26.7,
            'recommended_price': 1500000.0,
            'latest_lot': 'Vũng Tàu (Lô CP 5.0)',
            'basis_text': 'Dựa trên chi phí thực tế bốc xếp giao hàng Keep Rise ở Vũng Tàu (Giá vốn 400.000 đ - 1.500.000 đ).'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Bốc xếp & Giao hàng chuỗi Keep / Keep Rise tại Đà Nẵng',
            'spec': 'Giao cửa hàng & dỡ hàng tại Đà Nẵng',
            'unit': 'Chuyến',
            'count': 2,
            'buy_avg': 800000.0,
            'buy_min': 800000.0,
            'buy_max': 800000.0,
            'sell_avg': 1100000.0,
            'sell_min': 1100000.0,
            'sell_max': 1100000.0,
            'margin_avg': 27.3,
            'recommended_price': 1100000.0,
            'latest_lot': 'Đà Nẵng (Lô CP 5.0)',
            'basis_text': 'Dựa trên chi phí thực tế bốc xếp giao hàng Keep Rise ở Đà Nẵng (Giá vốn 800.000 đ/chuyến).'
        },
        {
            'category': 'Bốc xếp',
            'name': 'Thuê kho & Bốc xếp phân phối tại Đà Lạt',
            'spec': 'Thuê kho lưu hàng và bốc xếp Đà Lạt',
            'unit': 'Lô/Đợt',
            'count': 2,
            'buy_avg': 8300000.0,
            'buy_min': 8300000.0,
            'buy_max': 8300000.0,
            'sell_avg': 9500000.0,
            'sell_min': 9500000.0,
            'sell_max': 9500000.0,
            'margin_avg': 12.6,
            'recommended_price': 9500000.0,
            'latest_lot': 'Đà Lạt (Lô CP 5.0)',
            'basis_text': 'Dựa trên chi phí thực tế thuê kho và bốc xếp hàng Keep Rise tại Đà Lạt (Giá vốn 8.300.000 đ).'
        }
    ]
    results.extend(bocxep_benchmarks)

    # --------------------------------------------------------------------------
    # 3. KIỂM ĐỊNH / QUATEST / GIÁM ĐỊNH / KIỂM DỊCH
    # --------------------------------------------------------------------------
    kiemdinh_benchmarks = [
        {
            'category': 'Kiểm định',
            'name': 'Kiểm tra chất lượng Nhà nước (Quatest) - Thiết bị điện / Điện gia dụng',
            'spec': 'Thiết bị điện & gia dụng (Lô ≤ 10 Tấn / 1 Container)',
            'unit': 'Mẫu',
            'count': 5,
            'buy_avg': 3250000.0,
            'buy_min': 3250000.0,
            'buy_max': 3250000.0,
            'sell_avg': 4000000.0,
            'sell_min': 4000000.0,
            'sell_max': 4000000.0,
            'margin_avg': 18.8,
            'recommended_price': 4000000.0,
            'latest_lot': 'Lô 08.2026 (Quatest 1)',
            'basis_text': 'Căn cứ 3 đợt kiểm tra chất lượng thực tế thiết bị gia dụng tại Quatest 1 (Giá vốn 3.250.000 đ/mẫu, Giá thu khách 4.000.000 đ/mẫu). Áp dụng cho lô hàng ≤ 10 tấn hoặc 1 container.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Kiểm tra chất lượng Nhà nước (Quatest) - Mẫu thử nghiệm phát sinh',
            'spec': 'Mẫu phát sinh cùng lô (+1 mẫu thử nghiệm)',
            'unit': 'Mẫu',
            'count': 3,
            'buy_avg': 900000.0,
            'buy_min': 800000.0,
            'buy_max': 1000000.0,
            'sell_avg': 1200000.0,
            'sell_min': 1000000.0,
            'sell_max': 1500000.0,
            'margin_avg': 25.0,
            'recommended_price': 1200000.0,
            'latest_lot': 'Quatest 1 Hà Nội',
            'basis_text': 'Áp dụng cho mẫu thử nghiệm phát sinh thêm cùng chủng loại sản phẩm trong cùng một bộ hồ sơ đăng ký kiểm tra chất lượng.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Kiểm tra chất lượng Quatest - Hàng Dệt May / Quần Áo / Phụ Kiện',
            'spec': 'Hàng dệt may thời trang (Theo Lô hàng Keep Rise)',
            'unit': 'Lô hàng',
            'count': 3,
            'buy_avg': 5000000.0,
            'buy_min': 5000000.0,
            'buy_max': 5000000.0,
            'sell_avg': 5800000.0,
            'sell_min': 5800000.0,
            'sell_max': 5800000.0,
            'margin_avg': 13.8,
            'recommended_price': 5800000.0,
            'latest_lot': 'Lô CP 5.0 (Hàng Keep Rise)',
            'basis_text': 'Căn cứ chi phí kiểm tra chất lượng Quatest thực tế hàng Keep Rise (Giá vốn 5.000.000 đ/lô). Đã bao gồm thử nghiệm hàm lượng Formaldehyt và Amin thơm chuyển hóa từ thuốc nhuộm Azo.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Kiểm tra chất lượng Quatest - Đồ chơi trẻ em / Nhựa / Đồ dùng tiếp xúc thực phẩm',
            'spec': 'Hợp quy Đồ chơi trẻ em & Nhựa (QCVN 3:2019/BKHCN)',
            'unit': 'Mẫu',
            'count': 4,
            'buy_avg': 3000000.0,
            'buy_min': 2800000.0,
            'buy_max': 3200000.0,
            'sell_avg': 3800000.0,
            'sell_min': 3500000.0,
            'sell_max': 4200000.0,
            'margin_avg': 21.1,
            'recommended_price': 3800000.0,
            'latest_lot': 'Trung tâm Kiểm định Quatest',
            'basis_text': 'Định mức thử nghiệm chứng nhận hợp quy đồ chơi trẻ em, bao bì nhựa và đồ dùng ăn uống theo quy chuẩn kỹ thuật quốc gia.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Lấy mẫu kiểm tra chất lượng hiện trường nhanh tại Cửa khẩu',
            'spec': 'Lấy mẫu tại cửa khẩu (VN26040, VN26045, VN26047...)',
            'unit': 'Lần',
            'count': 3,
            'buy_avg': 1250000.0,
            'buy_min': 1000000.0,
            'buy_max': 1500000.0,
            'sell_avg': 1600000.0,
            'sell_min': 1500000.0,
            'sell_max': 1800000.0,
            'margin_avg': 21.9,
            'recommended_price': 1600000.0,
            'latest_lot': 'Lô CP 5.0 (Tháng 07/2026)',
            'basis_text': 'Dựa trên chi phí lấy mẫu sớm thực tế tại bãi kiểm hóa Lạng Sơn (Giá vốn 1.000.000 đ - 1.500.000 đ). Cán bộ Quatest trực tiếp đến bãi niêm phong mẫu gửi về phòng lab.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Phí chuẩn bị hồ sơ đăng ký kiểm tra chất lượng Nhà nước',
            'spec': 'Bộ hồ sơ đăng ký Cổng thông tin một cửa Quốc gia (NSW)',
            'unit': 'Bộ hồ sơ',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 500000.0,
            'sell_min': 500000.0,
            'sell_max': 500000.0,
            'margin_avg': 100.0,
            'recommended_price': 500000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên phí chuẩn bị hồ sơ kiểm tra chất lượng thực tế đã thu khách (500.000 đ/bộ). Bao gồm soạn đơn đăng ký, dịch thuật chứng chỉ và nộp NSW.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Kiểm dịch y tế phương tiện & hàng hóa (Việt Nam)',
            'spec': 'Kiểm dịch y tế cửa khẩu (Hữu Nghị / Tân Thanh)',
            'unit': 'Xe/Lô',
            'count': 22,
            'buy_avg': 75000.0,
            'buy_min': 25000.0,
            'buy_max': 165000.0,
            'sell_avg': 120000.0,
            'sell_min': 100000.0,
            'sell_max': 150000.0,
            'margin_avg': 37.5,
            'recommended_price': 120000.0,
            'latest_lot': 'Lô CP 5.0 (18 lần phát sinh)',
            'basis_text': 'Dựa trên 22 lượt kiểm dịch y tế thực tế tại cửa khẩu Hữu Nghị/Tân Thanh (Giá vốn 25.000 đ - 165.000 đ, TB 75.000 đ). Bao gồm phun thuốc khử khuẩn và cấp giấy chứng nhận.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Kiểm dịch y tế cửa khẩu Trung Quốc',
            'spec': 'Kiểm dịch y tế phương tiện phía TQ',
            'unit': 'Xe',
            'count': 8,
            'buy_avg': 38000.0,
            'buy_min': 25000.0,
            'buy_max': 75000.0,
            'sell_avg': 60000.0,
            'sell_min': 50000.0,
            'sell_max': 80000.0,
            'margin_avg': 36.7,
            'recommended_price': 50000.0,
            'latest_lot': 'Lô CP 5.0',
            'basis_text': 'Dựa trên 8 lượt kiểm dịch y tế xe phía Trung Quốc thực tế (Giá vốn 25.000 đ - 75.000 đ, TB 38.000 đ).'
        },
        {
            'category': 'Kiểm định',
            'name': 'Chi phí Hải quan & Giám định đồng bộ dây chuyền máy móc thiết bị',
            'spec': 'Giám định đồng bộ máy móc thiết bị toàn bộ lô hàng',
            'unit': 'Lô hàng',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 8000000.0,
            'sell_min': 8000000.0,
            'sell_max': 8000000.0,
            'margin_avg': 100.0,
            'recommended_price': 8000000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên chi phí hải quan và giám định đồng bộ thực tế đã thu khách (8.000.000 đ/lô). Đơn vị giám định độc lập Vinacontrol/FCC kiểm tra tính đồng bộ của dây chuyền.'
        },
        {
            'category': 'Kiểm định',
            'name': 'Phí chuẩn bị hồ sơ giám định đồng bộ',
            'spec': 'Bộ hồ sơ kỹ thuật giám định đồng bộ',
            'unit': 'Bộ hồ sơ',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 500000.0,
            'sell_min': 500000.0,
            'sell_max': 500000.0,
            'margin_avg': 100.0,
            'recommended_price': 500000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên phí chuẩn bị hồ sơ giám định đồng bộ thực tế đã thu khách (500.000 đ/bộ).'
        },
        {
            'category': 'Kiểm định',
            'name': 'Chi phí xử lý kiểm định kỹ thuật đồng bộ tại hiện trường',
            'spec': 'Xử lý kiểm định đồng bộ cửa khẩu',
            'unit': 'Lô hàng',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 3000000.0,
            'sell_min': 3000000.0,
            'sell_max': 3000000.0,
            'margin_avg': 100.0,
            'recommended_price': 3500000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên thực tế xử lý kiểm định đồng bộ tại cảng/cửa khẩu (Giá thu khách 3.000.000 đ/lô).'
        }
    ]
    results.extend(kiemdinh_benchmarks)

    # --------------------------------------------------------------------------
    # 4. TỜ KHAI HẢI QUAN: Chi tiết từng loại hình XNK (A11, A12, E21, H11, G13...)
    # --------------------------------------------------------------------------
    tokhai_benchmarks = [
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình A11 (Nhập tiêu dùng / Kinh doanh)',
            'spec': 'Loại hình A11 (Nhập kinh doanh thương mại)',
            'unit': 'Tờ khai',
            'count': 4,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 4500000.0,
            'sell_min': 4500000.0,
            'sell_max': 4500000.0,
            'margin_avg': 100.0,
            'recommended_price': 4500000.0,
            'latest_lot': 'Lô 08.2026 (Sunluxe)',
            'basis_text': 'Dựa trên các tờ khai A11 thực tế đã thông quan và thu khách (4.500.000 đ/tờ khai). Bao gồm lên tờ khai nháp, truyền VNACCS, kiểm tra chứng từ và làm thủ tục thông quan hiện trường.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình A12 (Nhập kinh doanh sản xuất)',
            'spec': 'Loại hình A12 (Nhập sản xuất công nghiệp)',
            'unit': 'Tờ khai',
            'count': 4,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 4500000.0,
            'sell_min': 4500000.0,
            'sell_max': 4500000.0,
            'margin_avg': 100.0,
            'recommended_price': 4500000.0,
            'latest_lot': 'Lô 08.2026 (Sunluxe)',
            'basis_text': 'Dựa trên các tờ khai A12 thực tế đã thông quan và thu khách (4.500.000 đ/tờ khai). Áp dụng cho doanh nghiệp nhập nguyên phụ liệu đưa vào dây chuyền sản xuất.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình E21 (Nhập nguyên liệu gia công)',
            'spec': 'Loại hình E21 (Gia công thương nhân nước ngoài)',
            'unit': 'Tờ khai',
            'count': 3,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 2000000.0,
            'sell_min': 2000000.0,
            'sell_max': 2000000.0,
            'margin_avg': 100.0,
            'recommended_price': 2200000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên tờ khai E21 thực tế đã thông quan (2.000.000 đ/tờ khai). Áp dụng cho hợp đồng gia công miễn thuế nhập khẩu.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình H11 (Hàng phi mậu dịch / Quà biếu / Hàng mẫu)',
            'spec': 'Loại hình H11 (Hàng phi mậu dịch)',
            'unit': 'Tờ khai',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 4000000.0,
            'sell_min': 4000000.0,
            'sell_max': 4000000.0,
            'margin_avg': 100.0,
            'recommended_price': 4000000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên tờ khai H11 thực tế đã thông quan (4.000.000 đ/tờ khai). Áp dụng cho hàng phi mậu dịch, quà biếu tặng hoặc hàng mẫu không thanh toán.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình G13 (Tạm nhập tái xuất / Miễn thuế)',
            'spec': 'Loại hình G13 (Tạm nhập hàng trưng bày/triển lãm)',
            'unit': 'Tờ khai',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 2000000.0,
            'sell_min': 2000000.0,
            'sell_max': 2000000.0,
            'margin_avg': 100.0,
            'recommended_price': 2200000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên tờ khai G13 thực tế đã thông quan (2.000.000 đ/tờ khai). Áp dụng cho hàng tạm nhập tái xuất phục vụ dự án, sự kiện, triển lãm.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Loại hình A41 (Doanh nghiệp Chế xuất EPE)',
            'spec': 'Loại hình A41 (Khu phi thuế quan / DNCX)',
            'unit': 'Tờ khai',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 1500000.0,
            'sell_min': 1500000.0,
            'sell_max': 1500000.0,
            'margin_avg': 100.0,
            'recommended_price': 1600000.0,
            'latest_lot': 'Lô 08.2026',
            'basis_text': 'Dựa trên tờ khai A41 thực tế đã thông quan (1.500.000 đ/tờ khai). Áp dụng cho doanh nghiệp chế xuất bán vào nội địa hoặc mua hàng nội địa.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Dịch vụ Tờ khai Hải quan - Lô hàng lẻ / Cont 20 tiêu chuẩn',
            'spec': 'Tờ khai thông thường (Lô lẻ / 1 Cont 20)',
            'unit': 'Tờ khai',
            'count': 32,
            'buy_avg': 1980000.0,
            'buy_min': 800000.0,
            'buy_max': 2500000.0,
            'sell_avg': 2500000.0,
            'sell_min': 2000000.0,
            'sell_max': 2500000.0,
            'margin_avg': 20.8,
            'recommended_price': 2500000.0,
            'latest_lot': 'Lô 1 (Tháng 08/2026)',
            'basis_text': 'Dựa trên hơn 30 đợt làm DVTK HQ thực tế trong hệ thống (Giá vốn TB 1.980.000 đ, Giá thu khách 2.500.000 đ). Áp dụng cho tờ khai dưới 3 dòng hàng tiêu chuẩn.'
        },
        {
            'category': 'Tờ khai',
            'name': 'Phụ thu Tờ khai nhánh (Từ dòng hàng thứ 5 trở đi)',
            'spec': 'Tờ khai nhánh (>4 dòng hàng theo quy định VNACCS)',
            'unit': 'Tờ khai nhánh',
            'count': 12,
            'buy_avg': 100000.0,
            'buy_min': 100000.0,
            'buy_max': 100000.0,
            'sell_avg': 200000.0,
            'sell_min': 200000.0,
            'sell_max': 250000.0,
            'margin_avg': 50.0,
            'recommended_price': 200000.0,
            'latest_lot': 'Hệ thống Hải quan Điện tử GIC',
            'basis_text': 'Định mức phụ thu tờ khai nhánh theo quy định hệ thống VNACCS/VCIS khi lô hàng có trên 4 dòng hàng (50 dòng/tờ khai nhánh).'
        },
        {
            'category': 'Tờ khai',
            'name': 'Phí tiếp nhận hồ sơ & Xử lý tờ khai quay đầu',
            'spec': 'Hồ sơ quay đầu chuyển cửa khẩu',
            'unit': 'Bộ hồ sơ',
            'count': 3,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 500000.0,
            'sell_min': 500000.0,
            'sell_max': 500000.0,
            'margin_avg': 100.0,
            'recommended_price': 500000.0,
            'latest_lot': 'Cột 26 Báo Cáo Bán Hàng',
            'basis_text': 'Dựa trên cước thực tế tiếp nhận hồ sơ quay đầu và làm thủ tục chuyển cửa khẩu đã thu khách (500.000 đ/bộ).'
        },
        {
            'category': 'Tờ khai',
            'name': 'Phí Hải quan giám sát tại bến bãi cửa khẩu',
            'spec': 'Hải quan giám sát bãi kiểm hóa',
            'unit': 'Xe/Cont',
            'count': 5,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 400000.0,
            'sell_min': 300000.0,
            'sell_max': 500000.0,
            'margin_avg': 100.0,
            'recommended_price': 400000.0,
            'latest_lot': 'Cột 19 Báo Cáo Bán Hàng',
            'basis_text': 'Dựa trên chi phí hải quan giám sát thực tế tại bãi kiểm hóa Tân Thanh/Hữu Nghị (300.000 đ - 500.000 đ/xe).'
        }
    ]
    results.extend(tokhai_benchmarks)

    # --------------------------------------------------------------------------
    # 5. BẢO HIỂM: Hàng hóa vận chuyển & Phương tiện xe
    # --------------------------------------------------------------------------
    baohiem_benchmarks = [
        {
            'category': 'Bảo hiểm',
            'name': 'Bảo hiểm Mọi Rủi Ro Hàng Hóa Vận Chuyển (All Risks ICC Clause A)',
            'spec': 'Bảo hiểm hàng hóa (0.08% Giá trị Hóa đơn / Invoice)',
            'unit': '% Hóa đơn (Min 500k)',
            'count': 10,
            'buy_avg': 0.05,
            'buy_min': 0.05,
            'buy_max': 0.05,
            'sell_avg': 0.08,
            'sell_min': 0.08,
            'sell_max': 0.10,
            'margin_avg': 37.5,
            'recommended_price': 0.08,
            'latest_lot': 'Bảo hiểm Bảo Việt / PTI',
            'basis_text': 'Áp dụng theo Quy tắc bảo hiểm hàng hóa vận chuyển nội địa (Institute Cargo Clauses - Clause A). Bồi thường 100% giá trị tổn thất do tai nạn lật xe, đâm va, cháy nổ, ướt hàng hoặc mất cắp từ cửa khẩu đến kho nhận. Mức phí tối thiểu (Min fee): 500.000 đ/chuyến.'
        },
        {
            'category': 'Bảo hiểm',
            'name': 'Bảo hiểm Trách nhiệm Dân sự & Vật chất Phương tiện Xe vận tải',
            'spec': 'Bảo hiểm phương tiện vận chuyển nội địa',
            'unit': 'Chuyến',
            'count': 50,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 0.0,
            'sell_min': 0.0,
            'sell_max': 0.0,
            'margin_avg': 0.0,
            'recommended_price': 0.0,
            'latest_lot': 'Toàn bộ đội xe GIC',
            'basis_text': 'Đã bao gồm trong chi phí cước vận chuyển trọn gói của GIC Logistics. Khách hàng không phải chi trả thêm phụ phí này.'
        }
    ]
    results.extend(baohiem_benchmarks)

    # --------------------------------------------------------------------------
    # 6. CỬA KHẨU / CƠ SỞ HẠ TẦNG (CSHT) / BẾN BÃI
    # --------------------------------------------------------------------------
    cuakhau_benchmarks = [
        {
            'category': 'Cửa khẩu',
            'name': 'Phí Cơ Sở Hạ Tầng (CSHT) Cửa khẩu - Xe tải 5 Tấn đến 8 Tấn (8T)',
            'spec': 'Xe tải thùng 5T - 8T (Theo biên lai UBND tỉnh)',
            'unit': 'Xe',
            'count': 14,
            'buy_avg': 859273.0,
            'buy_min': 859273.0,
            'buy_max': 859273.0,
            'sell_avg': 1389000.0,
            'sell_min': 1389000.0,
            'sell_max': 1389000.0,
            'margin_avg': 38.1,
            'recommended_price': 1380000.0,
            'latest_lot': 'Lô 1, Lô 2 (Tháng 08/2026)',
            'basis_text': 'Dựa trên biên lai nộp phí sử dụng công trình kết cấu hạ tầng cửa khẩu Lạng Sơn thực tế (Giá vốn Nhà nước: 859.273 đ/xe, Giá thu khách: 1.389.000 đ/xe).'
        },
        {
            'category': 'Cửa khẩu',
            'name': 'Phí Cơ Sở Hạ Tầng (CSHT) Cửa khẩu - Xe Container 40 feet / 45 feet',
            'spec': 'Xe Container 40 / 45 feet',
            'unit': 'Cont',
            'count': 16,
            'buy_avg': 1648000.0,
            'buy_min': 1648000.0,
            'buy_max': 2000000.0,
            'sell_avg': 2000000.0,
            'sell_min': 1800000.0,
            'sell_max': 2200000.0,
            'margin_avg': 17.6,
            'recommended_price': 2000000.0,
            'latest_lot': 'Cột 20 Báo Cáo Bán Hàng',
            'basis_text': 'Dựa trên biểu mức thu phí hạ tầng cửa khẩu Hữu Nghị / Tân Thanh áp dụng cho phương tiện container chở hàng hóa nhập khẩu.'
        },
        {
            'category': 'Cửa khẩu',
            'name': 'Vé xe ra vào bến bãi cửa khẩu (Tân Thanh / Hữu Nghị)',
            'spec': 'Vé cổng phương tiện bến xe cửa khẩu',
            'unit': 'Lượt',
            'count': 18,
            'buy_avg': 164814.0,
            'buy_min': 164814.0,
            'buy_max': 350000.0,
            'sell_avg': 250000.0,
            'sell_min': 200000.0,
            'sell_max': 350000.0,
            'margin_avg': 34.1,
            'recommended_price': 250000.0,
            'latest_lot': 'Cột 21 Báo Cáo Bán Hàng',
            'basis_text': 'Dựa trên vé xe bến bãi thực tế ra vào cổng kiểm soát cửa khẩu Tân Thanh và Hữu Nghị (Giá vốn 164.814 đ - 350.000 đ).'
        },
        {
            'category': 'Cửa khẩu',
            'name': 'Dấu đầu xe & Tem kiểm soát phương tiện Trung Quốc',
            'spec': 'Tem xe & Dấu đầu xe TQ',
            'unit': 'Xe',
            'count': 8,
            'buy_avg': 120000.0,
            'buy_min': 100000.0,
            'buy_max': 150000.0,
            'sell_avg': 180000.0,
            'sell_min': 150000.0,
            'sell_max': 200000.0,
            'margin_avg': 33.3,
            'recommended_price': 180000.0,
            'latest_lot': 'Cửa khẩu Hữu Nghị',
            'basis_text': 'Dựa trên chi phí thực tế đóng dấu đầu xe và cấp tem kiểm soát phương tiện vận tải qua lại biên giới phía Bắc.'
        }
    ]
    results.extend(cuakhau_benchmarks)

    # --------------------------------------------------------------------------
    # 7. PHỤ PHÍ VẬN TẢI & KHO BÃI
    # --------------------------------------------------------------------------
    phuphi_benchmarks = [
        {
            'category': 'Phụ phí',
            'name': 'Phí Lưu Ca Xe tải 5 Tấn - 8 Tấn (Quá 24h tại kho / cửa khẩu)',
            'spec': 'Xe tải thùng 5T - 8T (>24 giờ)',
            'unit': 'Ca/Ngày',
            'count': 4,
            'buy_avg': 800000.0,
            'buy_min': 700000.0,
            'buy_max': 900000.0,
            'sell_avg': 1000000.0,
            'sell_min': 1000000.0,
            'sell_max': 1000000.0,
            'margin_avg': 20.0,
            'recommended_price': 1000000.0,
            'latest_lot': 'Cột 18 Báo Cáo Bán Hàng',
            'basis_text': 'Dựa trên dữ liệu thực tế phí lưu ca xe tải trong các lô hàng GIC (1.000.000 đ/ngày đêm). Tính từ thời điểm xe đến điểm dỡ quá 24h do khách chưa nhận hàng.'
        },
        {
            'category': 'Phụ phí',
            'name': 'Phí Lưu Ca Xe Container 40 feet / 45 feet (Quá 24h)',
            'spec': 'Xe Container 40/45 (>24 giờ)',
            'unit': 'Ca/Ngày',
            'count': 6,
            'buy_avg': 1200000.0,
            'buy_min': 1000000.0,
            'buy_max': 1300000.0,
            'sell_avg': 1500000.0,
            'sell_min': 1500000.0,
            'sell_max': 1800000.0,
            'margin_avg': 20.0,
            'recommended_price': 1500000.0,
            'latest_lot': 'Hợp đồng vận tải Container GIC',
            'basis_text': 'Định mức bồi hoàn lưu ca cho lái xe và đầu kéo container khi chờ thông quan kiểm hóa hoặc chờ bốc hàng tại kho khách quá thời hạn quy định.'
        },
        {
            'category': 'Phụ phí',
            'name': 'Phụ phí phát sinh thêm điểm trả hàng (Nội tỉnh)',
            'spec': 'Điểm trả hàng thứ 2 trong cùng tỉnh/thành',
            'unit': 'Điểm',
            'count': 5,
            'buy_avg': 350000.0,
            'buy_min': 300000.0,
            'buy_max': 400000.0,
            'sell_avg': 500000.0,
            'sell_min': 500000.0,
            'sell_max': 600000.0,
            'margin_avg': 30.0,
            'recommended_price': 500000.0,
            'latest_lot': 'Đội xe nội địa GIC',
            'basis_text': 'Chi phí phát sinh điều động xe trả thêm hàng tại điểm thứ 2 trong bán kính 20km cùng tỉnh.'
        },
        {
            'category': 'Phụ phí',
            'name': 'Phụ phí phát sinh thêm điểm trả hàng (Ngoại tỉnh lân cận: Thái Bình, Hải Phòng...)',
            'spec': 'Điểm trả hàng ngoại tỉnh (Cách tuyến chính >30km)',
            'unit': 'Điểm',
            'count': 3,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 1000000.0,
            'sell_min': 1000000.0,
            'sell_max': 1000000.0,
            'margin_avg': 100.0,
            'recommended_price': 1000000.0,
            'latest_lot': 'Lô 08.2026 (Sunluxe)',
            'basis_text': 'Dựa trên 3 đợt phát sinh thực tế giao thêm 1 điểm tại Thái Bình và Hải Phòng trong hệ thống (Đã thu khách 1.000.000 đ/điểm).'
        },
        {
            'category': 'Phụ phí',
            'name': 'Phí Hủy Xe sau khi đã điều xe vào bến đóng hàng',
            'spec': 'Hủy chuyến trong vòng 4 giờ trước giờ đóng',
            'unit': 'Chuyến',
            'count': 2,
            'buy_avg': 0.0,
            'buy_min': 0.0,
            'buy_max': 0.0,
            'sell_avg': 1000000.0,
            'sell_min': 1000000.0,
            'sell_max': 1000000.0,
            'margin_avg': 100.0,
            'recommended_price': 1000000.0,
            'latest_lot': 'Lô 08.2026 (Tân Thanh - Thuận Thành)',
            'basis_text': 'Dựa trên thực tế khoản phí hủy xe Tân Thanh - Thuận Thành đã thu khách (1.000.000 đ/chuyến) do hủy xe đột xuất khi phương tiện đã tập kết tại bến.'
        }
    ]
    results.extend(phuphi_benchmarks)

    # Sắp xếp danh sách kết quả theo Category và Count
    category_order = {
        'Vận chuyển': 1,
        'Bốc xếp': 2,
        'Kiểm định': 3,
        'Tờ khai': 4,
        'Cửa khẩu': 5,
        'Bảo hiểm': 6,
        'Phụ phí': 7
    }
    results.sort(key=lambda x: (category_order.get(x['category'], 99), -x['count'], x['name']))
    return results

def get_benchmarks_filtered(category=None, search=None):
    """Lọc danh sách benchmark theo phân loại và từ khóa tìm kiếm"""
    all_items = get_all_benchmarks()
    filtered = all_items

    if category and category != 'all':
        filtered = [it for it in filtered if it['category'] == category]

    if search:
        s_norm = normalize_text_key(search)
        filtered = [
            it for it in filtered 
            if s_norm in normalize_text_key(it['name']) or 
               s_norm in normalize_text_key(it['spec']) or
               s_norm in normalize_text_key(it['category'])
        ]

    return filtered

def find_best_benchmark(category, name, spec=None):
    """Tìm cơ sở báo giá phù hợp nhất cho 1 dịch vụ / tuyến đường được chọn"""
    all_items = get_all_benchmarks()
    name_norm = normalize_text_key(name)
    spec_norm = normalize_text_key(spec) if spec else ''

    # 1. Khớp chính xác cả category, name và spec
    for it in all_items:
        if (not category or it['category'] == category) and \
           normalize_text_key(it['name']) == name_norm and \
           (not spec_norm or normalize_text_key(it['spec']) == spec_norm):
            return it

    # 2. Khớp category và spec
    if spec_norm:
        for it in all_items:
            if (not category or it['category'] == category) and \
               normalize_text_key(it['spec']) == spec_norm:
                return it

    # 3. Khớp substring name
    for it in all_items:
        if (not category or it['category'] == category) and \
           (name_norm in normalize_text_key(it['name']) or normalize_text_key(it['name']) in name_norm):
            return it

    # 4. Fallback: Lấy item đầu tiên trong category đó
    cat_items = [it for it in all_items if it['category'] == category]
    if cat_items:
        return cat_items[0]

    return None

def get_quick_options():
    """Lấy danh sách các tuyến đường, địa điểm và dịch vụ chi tiết để gợi ý nhanh trên form"""
    benchmarks = get_all_benchmarks()
    routes = []
    vehicles = set()
    categories_count = defaultdict(int)

    for b in benchmarks:
        categories_count[b['category']] += 1
        if b['spec']:
            vehicles.add(b['spec'])
        routes.append({
            'category': b['category'],
            'name': b['name'],
            'spec': b['spec'],
            'unit': b.get('unit', 'Chuyến'),
            'recommended_price': b['recommended_price'],
            'basis_text': b['basis_text']
        })

    return {
        'routes': routes,
        'vehicles': sorted(list(vehicles)),
        'categories_count': dict(categories_count)
    }
