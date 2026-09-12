"""
Customer Normalization and Management Service for GIC Logistics
Handles customer deduplication, canonical naming, alias mapping, and business statistics.
"""

import re
import unicodedata
from app.extensions import db
from app.models import Customer, Lot

# Canonical mapping dictionary: maps lowercase stripped name or alias to (Canonical Name, Code, Default Contact)
CUSTOMER_ALIASES = {
    # Keep Rise variations
    'keeprise': ('Keep Rise', 'KEEPRISE', None),
    'keep rise': ('Keep Rise', 'KEEPRISE', None),
    'keep_rise': ('Keep Rise', 'KEEPRISE', None),
    'keep-rise': ('Keep Rise', 'KEEPRISE', None),

    # Anh Thắng variations
    'anh thắng': ('Anh Thắng', 'ANHTHNG', 'Mr. Thắng'),
    'anh thang': ('Anh Thắng', 'ANHTHNG', 'Mr. Thắng'),
    'a thắng': ('Anh Thắng', 'ANHTHNG', 'Mr. Thắng'),
    'a thang': ('Anh Thắng', 'ANHTHNG', 'Mr. Thắng'),

    # Junk customer redirects to Khách vãng lai
    'cpvh': ('Khách vãng lai', 'RETAIL', None),
    'cpvh 11.2025': ('Khách vãng lai', 'RETAIL', None),
    'nhà cung cấp': ('Khách vãng lai', 'RETAIL', None),
    'nha cung cap': ('Khách vãng lai', 'RETAIL', None),
    'trung quốc chi hộ': ('Khách vãng lai', 'RETAIL', None),
    'trung quoc chi ho': ('Khách vãng lai', 'RETAIL', None),
    'trung quốc': ('Khách vãng lai', 'RETAIL', None),
    'trung quoc': ('Khách vãng lai', 'RETAIL', None),

    # Sunluxe variations
    'sunluxe': ('Sunluxe', 'SUNLUXE', 'Mr. Thắng'),
    'sun luxe': ('Sunluxe', 'SUNLUXE', 'Mr. Thắng'),
    'sun_luxe': ('Sunluxe', 'SUNLUXE', 'Mr. Thắng'),

    # JiaYi variations
    'jiayi': ('JiaYi', 'JIAYI', 'Mr. Thắng'),
    'jia yi': ('JiaYi', 'JIAYI', 'Mr. Thắng'),
    'jiayi vn': ('JiaYi', 'JIAYI', 'Mr. Thắng'),

    # Huy Hoàng variations
    'huy hoàng': ('Huy Hoàng', 'HUYHOANG', None),
    'huy hoang': ('Huy Hoàng', 'HUYHOANG', None),

    # Hải Bân variations
    'hải bân': ('Hải Bân', 'HAIBAN', None),
    'hai ban': ('Hải Bân', 'HAIBAN', None),

    # Bình Minh variations
    'bình minh': ('Bình Minh', 'BINHMINH', None),
    'binh minh': ('Bình Minh', 'BINHMINH', None),

    # Johnson variations
    'johnson': ('Johnson', 'JOHNSON', None),
    'johnson 1': ('Johnson', 'JOHNSON', None),
    'johnson 2': ('Johnson', 'JOHNSON', None),

    # Thành Khởi variations
    'thành khởi': ('Thành Khởi', 'THANHKHOI', None),
    'thanh khoi': ('Thành Khởi', 'THANHKHOI', None),

    # Xingfa
    'xingfa': ('Xingfa', 'XINGFA', None),

    # Aqua
    'aqua': ('Aqua', 'AQUA', None),

    # Kaixin
    'kaixin': ('Kaixin', 'KAIXIN', None),

    # Ginhung
    'ginhung': ('Ginhung', 'GINHUNG', None),

    # Ocean
    'ocean': ('Ocean', 'OCEAN', None),

    # GHNex
    'ghnex': ('GHNex', 'GHNEX', None),
    'ghnlog': ('GHNex', 'GHNEX', None),
    'ghn log': ('GHNex', 'GHNEX', None),

    # Zhongyuanda & Yunqian
    'guangxi zhongyuanda': ('GUANGXI ZHONGYUANDA', 'ZYD', None),
    'zhongyuanda': ('GUANGXI ZHONGYUANDA', 'ZYD', None),
    'guangxi yunqian': ('GUANGXI YUNQIAN', 'YUNQIAN', None),
    'yunqian': ('GUANGXI YUNQIAN', 'YUNQIAN', None),

    # Sao Đỏ
    'saodo': ('Sao Đỏ', 'SAODO', None),
    'sao do': ('Sao Đỏ', 'SAODO', None),
    'sao đỏ': ('Sao Đỏ', 'SAODO', None),

    # Ween
    'ween': ('Ween', 'WEEN', None),

    # Hưng Đại
    'hưng đại': ('Hưng Đại', 'HUNGDAI', None),
    'hung dai': ('Hưng Đại', 'HUNGDAI', None),

    # Linghang
    'linghang': ('Linghang', 'LINGHANG', None),

    # Okia
    'okia': ('Okia', 'OKIA', None),

    # Jierun
    'jierun': ('Jierun', 'JIERUN', None),

    # Song Hào
    'song hao': ('Song Hào', 'SONGHAO', None),
    'song hào': ('Song Hào', 'SONGHAO', None),

    # Linte
    'linte': ('Linte', 'LINTE', None),

    # Hiếu Tín Phát
    'công ty tnhh giao nhận vận tải hiếu tín phát': ('Hiếu Tín Phát', 'HIEUTINPHAT', None),
    'hiếu tín phát': ('Hiếu Tín Phát', 'HIEUTINPHAT', None),

    # Khách vãng lai
    'khách vãng lai': ('Khách vãng lai', 'RETAIL', None),
    'khach vang lai': ('Khách vãng lai', 'RETAIL', None)
}

# Non-customer junk strings to ignore / clean up
JUNK_NAMES = {'11/2025', 'cpvh 11.2025', 'nhà cung cấp', 'trung quốc chi hộ', 'gido'}


def normalize_customer_name(raw_name):
    """
    Chuẩn hóa tên khách hàng:
    - Loại bỏ các biến thể viết hoa, viết thường, gạch chân
    - Tách người liên hệ nếu có tiền tố (ví dụ: 'MR THẮNG_Sunluxe' -> Sunluxe, liên hệ: Mr. Thắng)
    - Chuẩn hóa Unicode NFC (tránh lỗi tiếng Việt tổ hợp)
    Returns: (canonical_name, canonical_code, contact_person)
    """
    if not raw_name:
        return ('Khách vãng lai', 'RETAIL', None)

    # Unicode NFC normalization
    norm = unicodedata.normalize('NFC', str(raw_name)).strip()
    if not norm:
        return ('Khách vãng lai', 'RETAIL', None)

    contact_person = None

    # Check for prefix like 'MR THẮNG_Sunluxe', 'Anh Thắng_Sunluxe', 'A Thắng'
    prefix_match = re.match(r'^(?:mr\.?|anh|chị|em|bác|a\.?)\s+([^_\-]+)[_\-](.+)$', norm, re.IGNORECASE)
    if prefix_match:
        c_name = prefix_match.group(1).strip().title()
        contact_person = f"Mr. {c_name}" if not c_name.lower().startswith(('mr', 'anh')) else c_name
        norm = prefix_match.group(2).strip()

    # Check for suffix contact like 'Sunluxe (Anh Thắng)'
    suffix_match = re.match(r'^(.+?)\s*\((?:mr\.?|anh|chị)\s*([^)]+)\)$', norm, re.IGNORECASE)
    if suffix_match:
        norm = suffix_match.group(1).strip()
        contact_person = f"Mr. {suffix_match.group(2).strip().title()}"

    lower_key = norm.lower()

    # If it is an exact alias
    if lower_key in CUSTOMER_ALIASES:
        c_name, c_code, def_contact = CUSTOMER_ALIASES[lower_key]
        return (c_name, c_code, contact_person or def_contact)

    # Partial / substring match in aliases
    for k, (c_name, c_code, def_contact) in CUSTOMER_ALIASES.items():
        if k in lower_key or lower_key in k:
            return (c_name, c_code, contact_person or def_contact)

    # Special handling for Johnson project codes like 'Johnson 1 - ZYD-0325-NT24'
    if 'johnson' in lower_key:
        return ('Johnson', 'JOHNSON', contact_person)

    # Fallback: clean name (preserve acronym casing like VIP unless all upper/lower)
    if norm.islower() or norm.isupper():
        clean_name = norm.title()
    else:
        clean_name = norm
    clean_code = re.sub(r'[^A-Z0-9]', '', clean_name.upper())[:15] or 'KH'
    return (clean_name, clean_code, contact_person)


def get_or_create_canonical_customer(raw_name, contact_hint=None):
    """
    Tìm hoặc tạo khách hàng chuẩn hóa theo canonical name.
    Đảm bảo 100% không tạo duplicate khách hàng như KEEPRISE vs Keep Rise.
    """
    canonical_name, canonical_code, detected_contact = normalize_customer_name(raw_name)
    contact = contact_hint or detected_contact

    # Query existing Customer by name case-insensitively
    cust = Customer.query.filter(
        db.func.lower(Customer.name) == canonical_name.lower()
    ).first()

    if not cust:
        cust = Customer(
            name=canonical_name,
            code=canonical_code,
            contact_person=contact
        )
        db.session.add(cust)
        db.session.flush()
    else:
        # Update code or contact if missing
        if not cust.code and canonical_code:
            cust.code = canonical_code
        if not cust.contact_person and contact:
            cust.contact_person = contact

    return cust


def merge_customers(source_customer_id, target_customer_id):
    """
    Gộp 2 khách hàng: chuyển toàn bộ các lô hàng của source sang target,
    cập nhật thông tin và xóa source nếu source không còn lô nào.
    """
    if source_customer_id == target_customer_id:
        return False, "Không thể gộp khách hàng vào chính nó."

    source = db.session.get(Customer, source_customer_id)
    target = db.session.get(Customer, target_customer_id)

    if not source or not target:
        return False, "Khách hàng không tồn tại."

    # Move all lots
    lots = Lot.query.filter_by(customer_id=source.id).all()
    for l in lots:
        l.customer_id = target.id
        l.company = target.name

    # Merge contact info if target lacks it
    if not target.contact_person and source.contact_person:
        target.contact_person = source.contact_person
    if not target.phone and source.phone:
        target.phone = source.phone
    if not target.email and source.email:
        target.email = source.email
    if not target.address and source.address:
        target.address = source.address

    # Mark source as merged and inactive
    source.is_active = False
    source.notes = (source.notes or '') + f" [Đã gộp vào '{target.name}' (ID: {target.id})]"
    
    db.session.commit()
    return True, f"Đã gộp thành công {len(lots)} lô hàng từ '{source.name}' sang '{target.name}'."


def clean_and_migrate_all_customers():
    """
    Chạy chuẩn hóa toàn diện trên toàn bộ database:
    1. Gộp các khách hàng trùng lặp: Keep Rise, Sunluxe, JiaYi, Huy Hoàng, Hải Bân...
    2. Cập nhật Lot.customer_id và Lot.company thành tên chuẩn.
    3. Dọn dẹp các khách hàng rác.
    """
    print("Bắt đầu chuẩn hóa khách hàng...")
    all_lots = Lot.query.filter_by(is_deleted=False).all()

    # Step 1: Normalize all lot associations
    relinked_count = 0
    for lot in all_lots:
        current_raw = lot.company or (lot.customer.name if lot.customer else '')
        canonical_name, canonical_code, detected_contact = normalize_customer_name(current_raw)

        # Get or create target canonical customer
        target_cust = Customer.query.filter(
            db.func.lower(Customer.name) == canonical_name.lower()
        ).first()

        if not target_cust:
            target_cust = Customer(
                name=canonical_name,
                code=canonical_code,
                contact_person=detected_contact
            )
            db.session.add(target_cust)
            db.session.flush()
        else:
            if not target_cust.contact_person and detected_contact:
                target_cust.contact_person = detected_contact
            if not target_cust.code and canonical_code:
                target_cust.code = canonical_code

        # Update lot
        if lot.customer_id != target_cust.id or lot.company != canonical_name:
            lot.customer_id = target_cust.id
            lot.company = canonical_name
            relinked_count += 1

    db.session.commit()

    # Step 2: Delete duplicate or empty junk customer rows
    customers = Customer.query.all()
    deleted_count = 0
    for c in customers:
        active_lot_count = c.lots.filter_by(is_deleted=False).count()
        lower_c = c.name.lower().strip()
        is_junk = lower_c in JUNK_NAMES or active_lot_count == 0

        # Check if another customer with same canonical name exists with lower id
        can_name, _, _ = normalize_customer_name(c.name)
        duplicate = Customer.query.filter(
            db.func.lower(Customer.name) == can_name.lower(),
            Customer.id != c.id
        ).first()

        if active_lot_count == 0 or (duplicate and duplicate.id < c.id and active_lot_count == 0) or is_junk:
            if active_lot_count == 0:
                db.session.delete(c)
                deleted_count += 1

    db.session.commit()
    print(f"Hoàn thành chuẩn hóa: Relinked {relinked_count} lots, xóa {deleted_count} khách hàng trùng/rác.")
    return relinked_count, deleted_count


def get_customer_summary_stats():
    """Thống kê tổng hợp cho trang Dashboard Khách Hàng"""
    customers = Customer.query.filter_by(is_active=True).all()
    active_customers = [c for c in customers if c.total_lots > 0]

    total_lots = sum(c.total_lots for c in active_customers)
    total_revenue = sum(c.total_revenue for c in active_customers)
    total_profit = sum(c.net_profit for c in active_customers)
    avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0.0

    return {
        'total_customers': len(customers),
        'active_customers': len(active_customers),
        'total_lots': total_lots,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'avg_margin': round(avg_margin, 2)
    }
