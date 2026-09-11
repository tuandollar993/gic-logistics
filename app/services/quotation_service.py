import unicodedata
import re
from collections import defaultdict
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import RevenueItem, OperatingCost

def normalize_text_key(text):
    """Chuẩn hóa chuỗi tiếng Việt để so khớp (bỏ dấu, thường, xóa khoảng trắng thừa)"""
    if not text:
        return ''
    s = unicodedata.normalize('NFC', text.strip().lower())
    s_ascii = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s_ascii)

def get_all_benchmarks():
    """
    Quét toàn bộ RevenueItem và OperatingCost, tổng hợp thành bảng thống kê giá lịch sử
    theo từng tổ hợp (Category, Service/Route Name, Spec/Weight/Location).
    """
    groups = defaultdict(lambda: {
        'category': '',
        'name': '',
        'spec': '',
        'buy_prices': [],
        'sell_prices': [],
        'margins': [],
        'count': 0,
        'latest_lot': '',
        'latest_month': 0,
        'latest_year': 0
    })

    # 1. Doanh thu & Cước vận tải
    rev_items = RevenueItem.query.options(joinedload(RevenueItem.lot)).filter(
        RevenueItem.is_deleted == False
    ).all()

    for item in rev_items:
        cat = item.category
        name = (item.display_description or item.service_description or 'Dịch vụ vận tải').strip()
        spec = (item.weight_class or '').strip()
        
        norm_name = normalize_text_key(name)
        norm_spec = normalize_text_key(spec)
        key = (cat, norm_name, norm_spec)
        
        g = groups[key]
        if not g['category']:
            g['category'] = cat
            g['name'] = name
            g['spec'] = spec
        elif len(name) > len(g['name']):
            g['name'] = name
        if spec and not g['spec']:
            g['spec'] = spec

        g['count'] += 1
        buy = item.buy_price or item.total_buy_price or 0.0
        sell = item.sell_price or item.total_sell_price or 0.0
        
        if buy > 0:
            g['buy_prices'].append(buy)
        if sell > 0:
            g['sell_prices'].append(sell)
        if buy > 0 and sell > 0:
            margin = ((sell - buy) / sell) * 100
            g['margins'].append(margin)

        if item.lot:
            m = item.lot.month or 0
            y = item.lot.year or 2026
            if (y > g['latest_year']) or (y == g['latest_year'] and m >= g['latest_month']):
                g['latest_year'] = y
                g['latest_month'] = m
                g['latest_lot'] = f"{item.lot.lot_label} (Tháng {m:02d}/{y})"

    # 2. Chi phí vận hành thực tế
    cost_items = OperatingCost.query.options(joinedload(OperatingCost.lot)).filter(
        OperatingCost.is_deleted == False
    ).all()

    for cost in cost_items:
        cat = cost.category
        name = (cost.display_description or cost.description or 'Chi phí vận hành').strip()
        spec = (cost.vehicle_plate or cost.cost_type if cost.cost_type != cat else '') or ''
        
        norm_name = normalize_text_key(name)
        norm_spec = normalize_text_key(spec)
        key = (cat, norm_name, norm_spec)
        
        g = groups[key]
        if not g['category']:
            g['category'] = cat
            g['name'] = name
            g['spec'] = spec
        elif len(name) > len(g['name']):
            g['name'] = name
        if spec and not g['spec']:
            g['spec'] = spec

        g['count'] += 1
        buy = cost.total_amount or cost.unit_price or 0.0
        sell = cost.sell_price or 0.0
        
        if buy > 0:
            g['buy_prices'].append(buy)
        if sell > 0:
            g['sell_prices'].append(sell)
        if buy > 0 and sell > 0:
            margin = ((sell - buy) / sell) * 100
            g['margins'].append(margin)

        if cost.lot:
            m = cost.lot.month or 0
            y = cost.lot.year or 2026
            if (y > g['latest_year']) or (y == g['latest_year'] and m >= g['latest_month']):
                g['latest_year'] = y
                g['latest_month'] = m
                g['latest_lot'] = f"{cost.lot.lot_label} (Tháng {m:02d}/{y})"

    results = []
    for g in groups.values():
        b_count = len(g['buy_prices'])
        s_count = len(g['sell_prices'])
        
        buy_avg = sum(g['buy_prices']) / b_count if b_count > 0 else 0.0
        buy_min = min(g['buy_prices']) if b_count > 0 else 0.0
        buy_max = max(g['buy_prices']) if b_count > 0 else 0.0
        
        sell_avg = sum(g['sell_prices']) / s_count if s_count > 0 else 0.0
        sell_min = min(g['sell_prices']) if s_count > 0 else 0.0
        sell_max = max(g['sell_prices']) if s_count > 0 else 0.0
        
        margin_avg = sum(g['margins']) / len(g['margins']) if g['margins'] else 0.0
        
        # Mức giá bán đề xuất để chào khách
        if sell_avg > 0:
            recommended_price = round(sell_avg, -4)
        elif buy_avg > 0:
            # Nếu chưa có giá bán ra, đề xuất giá vốn + 25% biên lợi nhuận
            recommended_price = round(buy_avg * 1.25, -4)
        else:
            recommended_price = 0.0

        # Chuỗi cơ sở định giá chi tiết và rõ ràng
        basis_parts = []
        basis_parts.append(f"Dựa trên {g['count']} chuyến/lần thực hiện trong lịch sử.")
        if b_count > 0:
            if buy_min == buy_max:
                basis_parts.append(f"Giá vốn NCC: {buy_avg:,.0f} đ.")
            else:
                basis_parts.append(f"Giá vốn NCC: {buy_min:,.0f} đ – {buy_max:,.0f} đ (TB: {buy_avg:,.0f} đ).")
        if s_count > 0:
            if sell_min == sell_max:
                basis_parts.append(f"Giá đã thu khách: {sell_avg:,.0f} đ.")
            else:
                basis_parts.append(f"Giá đã thu khách: {sell_min:,.0f} đ – {sell_max:,.0f} đ (TB: {sell_avg:,.0f} đ).")
        if margin_avg != 0:
            basis_parts.append(f"Biên LN bình quân: {margin_avg:.1f}%.")
        if g['latest_lot']:
            basis_parts.append(f"Gần nhất: {g['latest_lot']}.")
            
        basis_text = " ".join(basis_parts)

        results.append({
            'category': g['category'],
            'name': g['name'],
            'spec': g['spec'],
            'count': g['count'],
            'buy_avg': buy_avg,
            'buy_min': buy_min,
            'buy_max': buy_max,
            'sell_avg': sell_avg,
            'sell_min': sell_min,
            'sell_max': sell_max,
            'margin_avg': round(margin_avg, 1),
            'recommended_price': recommended_price,
            'latest_lot': g['latest_lot'],
            'basis_text': basis_text
        })

    # Sắp xếp theo số lần thực hiện giảm dần (phổ biến nhất lên đầu)
    results.sort(key=lambda x: x['count'], reverse=True)
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

    # 1. Khớp chính xác cả name và spec
    for it in all_items:
        if (not category or it['category'] == category) and \
           normalize_text_key(it['name']) == name_norm and \
           (not spec_norm or normalize_text_key(it['spec']) == spec_norm):
            return it

    # 2. Khớp name chứa chuỗi
    for it in all_items:
        if (not category or it['category'] == category) and \
           (name_norm in normalize_text_key(it['name']) or normalize_text_key(it['name']) in name_norm):
            return it

    # 3. Fallback: lấy trung bình của cả Category đó
    cat_items = [it for it in all_items if it['category'] == category]
    if cat_items:
        avg_rec = sum(it['recommended_price'] for it in cat_items) / len(cat_items)
        return {
            'category': category,
            'name': name,
            'spec': spec or '',
            'count': sum(it['count'] for it in cat_items),
            'recommended_price': round(avg_rec, -4),
            'basis_text': f"Dựa trên mức giá trung bình của {len(cat_items)} hạng mục thuộc nhóm '{category}' trong lịch sử hệ thống GIC Logistics."
        }

    return None

def get_quick_options():
    """Lấy danh sách các tuyến đường, địa điểm và dịch vụ phổ biến để gợi ý nhanh"""
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
            'recommended_price': b['recommended_price'],
            'basis_text': b['basis_text']
        })

    return {
        'routes': routes,
        'vehicles': sorted(list(vehicles)),
        'categories_count': dict(categories_count)
    }
