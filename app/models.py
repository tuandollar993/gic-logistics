import re
import unicodedata
from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')  # 'manager' or 'staff'
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    assigned_lots = db.relationship('Lot', backref='assignee', foreign_keys='Lot.assigned_to', lazy='dynamic')
    assigned_tasks = db.relationship('CostEntryTask', backref='assignee', foreign_keys='CostEntryTask.assigned_to', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role in ('manager', 'admin')

    @property
    def is_staff(self):
        return self.role == 'staff'
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'full_name': self.full_name,
            'role': self.role,
            'telegram_chat_id': self.telegram_chat_id,
            'email': self.email,
            'is_active': self.is_active
        }

class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    code = db.Column(db.String(50), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.Text, nullable=True)
    tax_code = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    lots = db.relationship('Lot', backref='customer', lazy='dynamic')

    @property
    def sales_lots(self):
        """Chỉ các lô bán hàng thực tế (source_type != 'cpvh')"""
        return [l for l in self.lots.all() if not l.is_deleted and l.is_sales_lot]

    @property
    def unresolved_cpvh_lots(self):
        """Các nhóm CPVH chưa đối soát gắn với khách hàng này (nếu có)"""
        return [l for l in self.lots.all() if not l.is_deleted and l.is_unresolved_cpvh]

    @property
    def active_lots(self):
        """Chỉ Sales Lot mới được tính vào KPI số lô và tổng hợp tài chính khách hàng"""
        return self.sales_lots

    @property
    def total_lots(self):
        return len(self.active_lots)

    @property
    def total_revenue(self):
        return sum(l.total_sell_revenue for l in self.active_lots)

    @property
    def total_cost(self):
        return sum((l.total_buy_cost + l.total_operating_cost) for l in self.active_lots)

    @property
    def net_profit(self):
        return sum(l.net_profit for l in self.active_lots)

    @property
    def margin_percent(self):
        rev = self.total_revenue
        if rev > 0:
            return round((self.net_profit / rev) * 100.0, 2)
        return 0.0

    @property
    def latest_lot(self):
        lots = self.active_lots
        if not lots:
            return None
        return sorted(lots, key=lambda l: (l.year or 0, l.month or 0, l.id), reverse=True)[0]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code or '',
            'contact_person': self.contact_person or '',
            'phone': self.phone or '',
            'email': self.email or '',
            'total_lots': self.total_lots,
            'total_revenue': self.total_revenue,
            'net_profit': self.net_profit,
            'margin_percent': self.margin_percent
        }

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    
    id = db.Column(db.Integer, primary_key=True)
    tax_code = db.Column(db.String(50), nullable=True, index=True)
    supplier_code = db.Column(db.String(50), nullable=True)
    name = db.Column(db.String(300), nullable=False)
    address = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'tax_code': self.tax_code or '',
            'supplier_code': self.supplier_code or '',
            'name': self.name,
            'address': self.address or ''
        }

class Target(db.Model):
    __tablename__ = 'targets'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    target_amount = db.Column(db.Float, nullable=False)  # Đơn vị: nghìn đồng
    
    __table_args__ = (db.UniqueConstraint('year', 'month', name='uq_target_year_month'),)
    
    @property
    def target_amount_vnd(self):
        # 1 nghìn đồng = 1,000 VND
        return (self.target_amount or 0) * 1000

class Lot(db.Model):
    __tablename__ = 'lots'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_label = db.Column(db.String(50), nullable=True)  # 'Lô 1', 'Lô 2', hoặc mã tự sinh
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    company = db.Column(db.String(200), nullable=True)   # Johnson 2, Sunluxe, Keep Rise...
    customs_declaration = db.Column(db.String(150), nullable=True, index=True)  # Số tờ khai HQ
    month = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    
    source_sheet = db.Column(db.String(50), nullable=True)
    source_type = db.Column(db.String(20), default='gido')  # 'gido' hoặc 'ghnlog'
    
    # Workflow
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'assigned', 'in_progress', 'completed'
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    cost_deadline = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    revenue_items = db.relationship('RevenueItem', backref='lot', cascade='all, delete-orphan', lazy='selectin')
    operating_costs = db.relationship('OperatingCost', backref='lot', cascade='all, delete-orphan', lazy='selectin')
    tasks = db.relationship('CostEntryTask', backref='lot', cascade='all, delete-orphan', lazy='dynamic')
    
    @property
    def total_sell_revenue(self):
        """Tổng doanh thu bán (chưa VAT) của lô"""
        revenue_items_total = sum(item.total_sell_price for item in self.revenue_items if not item.is_deleted)
        operating_costs_sell = sum(
            cost.sell_price or 0 for cost in self.operating_costs if not cost.is_deleted
        )
        return revenue_items_total + operating_costs_sell
    
    @property
    def total_buy_cost(self):
        """Tổng chi phí mua (đã có VAT) từ báo cáo bán hàng"""
        return sum(item.total_buy_price for item in self.revenue_items if not item.is_deleted)
    
    @property
    def total_operating_cost(self):
        """Tổng chi phí vận hành thực tế do nhân viên điền"""
        return sum(cost.total_amount or 0 for cost in self.operating_costs if not cost.is_deleted)
    
    @property
    def gross_profit(self):
        """Lợi nhuận gộp (Doanh thu bán - Giá mua hàng)"""
        return self.total_sell_revenue - self.total_buy_cost
    
    @property
    def net_profit(self):
        """Lợi nhuận thực tế (Doanh thu bán - Giá mua - Chi phí vận hành)"""
        return self.total_sell_revenue - self.total_buy_cost - self.total_operating_cost
    
    @property
    def profit_margin(self):
        rev = self.total_sell_revenue
        if rev > 0:
            return round((self.net_profit / rev) * 100, 2)
        return 0.0

    @property
    def is_sales_lot(self):
        """Phân biệt lô bán hàng thực tế với các nhóm CPVH chưa đối soát"""
        return self.source_type != 'cpvh'

    @property
    def is_unresolved_cpvh(self):
        """Nhóm chi phí vận hành chưa đối soát chắc chắn với Sales Lot nào"""
        return self.source_type == 'cpvh'

    @property
    def display_lot_label(self):
        """Tên nhãn hiển thị: Sales Lot giữ nguyên mã lô, nhóm CPVH thể hiện rõ bản chất"""
        if self.is_unresolved_cpvh:
            lbl = self.lot_label or f"Nhóm CPVH #{self.id}"
            if lbl.lower().startswith('lô cp'):
                return lbl.replace('Lô CP', 'Nhóm CPVH').replace('lô cp', 'Nhóm CPVH')
            return lbl
        return self.lot_label or f"Lô #{self.id}"

    @classmethod
    def sales_lots_query(cls):
        """Query scope: Chỉ các Sales Lot active (không bao gồm nhóm CPVH chưa đối soát)"""
        return cls.query.filter(cls.is_deleted == False, cls.source_type != 'cpvh')

    @classmethod
    def unresolved_cpvh_query(cls):
        """Query scope: Chỉ các nhóm CPVH chưa đối soát active"""
        return cls.query.filter(cls.is_deleted == False, cls.source_type == 'cpvh')

    @property
    def display_customer_name(self):
        """Tên khách hàng chuẩn hóa hiển thị trên bảng lô hàng"""
        if self.customer and self.customer.name:
            return self.customer.name
        if self.company:
            return self.company
        return "Khách vãng lai"

    @property
    def display_contact_person(self):
        """Người liên hệ nếu có"""
        if self.customer and self.customer.contact_person:
            return self.customer.contact_person
        if self.company and ('mr ' in self.company.lower() or 'anh ' in self.company.lower()):
            parts = self.company.split('_')
            if len(parts) > 1:
                return parts[0].strip()
        return None

    @property
    def active_revenue_items(self):
        return [item for item in self.revenue_items if not item.is_deleted]

    @property
    def active_operating_costs(self):
        return [cost for cost in self.operating_costs if not cost.is_deleted]

    @property
    def cost_status(self):
        """
        Trạng thái điền chi phí vận hành:
        - 'none': Chưa có chi phí
        - 'partial': Có chi phí nhưng chưa đủ thông tin hợp lệ
        - 'completed': Đã đủ thông tin hợp lệ và hoàn tất
        """
        costs = [cost for cost in self.operating_costs if not cost.is_deleted]
        if not costs or len(costs) == 0:
            return 'none'
        all_valid = True
        for c in costs:
            has_desc = bool(c.description and c.description.strip())
            has_amount = bool((c.total_amount and c.total_amount > 0) or (c.cost_amount and c.cost_amount > 0))
            has_doc = bool(c.invoice_type or c.invoice_number or (c.note and 'không hđ' in c.note.lower()))
            has_supp = bool(c.supplier_name or c.supplier_tax_code)
            if not (has_desc and has_amount and has_doc and has_supp and c.document_date):
                all_valid = False
                break
        if all_valid and self.status == 'completed':
            return 'completed'
        return 'partial'

    @property
    def is_cost_complete(self):
        return self.cost_status == 'completed'

    @property
    def distinct_vehicles(self):
        """
        Danh sách tất cả các xe / biển số xe (BKS) vận hành trong lô hàng này.
        Thu thập từ cả doanh thu bán hàng (RevenueItem) và chi phí vận hành (OperatingCost).
        """
        vehicles = []
        seen = set()

        def _add(plate, label=None):
            if not plate:
                return
            cleaned = str(plate).strip()
            if not cleaned or cleaned.lower() in ('none', '-', 'nan', 'null', ''):
                return
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            if cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                vehicles.append({
                    'plate': cleaned,
                    'label': label or cleaned
                })

        for ri in self.active_revenue_items:
            p_vn = (ri.vehicle_plate_vn or '').strip()
            p_cn = (ri.vehicle_plate_cn or '').strip()
            desc = ri.service_description or ''
            vehicle_tag = None
            cont_m = re.search(r'\b(Cont\s*\(\d+\)|Cont\s*\d+|Xe\s*\d+T|\d+T)\b', desc, re.IGNORECASE)
            if cont_m:
                vehicle_tag = cont_m.group(1).title()

            if p_vn and p_cn:
                _add(f"{p_vn} / {p_cn}", label=f"{vehicle_tag} - {p_vn}" if vehicle_tag else p_vn)
            elif p_vn:
                _add(p_vn, label=f"{vehicle_tag} - {p_vn}" if vehicle_tag else p_vn)
            elif p_cn:
                _add(p_cn, label=f"{vehicle_tag} - {p_cn}" if vehicle_tag else p_cn)
            elif vehicle_tag:
                _add(vehicle_tag, label=vehicle_tag)

        for cost in self.active_operating_costs:
            _add(cost.vehicle_plate)

        return vehicles

    @property
    def total_vehicle_count(self):
        """
        Tổng số xe chạy trong lô hàng này.
        """
        v_list = self.distinct_vehicles
        if v_list:
            return len(v_list)
        transport_items = [ri for ri in self.active_revenue_items if ri.category == 'Vận chuyển']
        if transport_items:
            return len(transport_items)
        max_vc = max([c.vehicle_count or 1 for c in self.active_operating_costs], default=0)
        if max_vc > 1:
            return int(max_vc)
        if self.active_revenue_items or self.active_operating_costs:
            return 1
        return 0

    @property
    def costs_by_vehicle(self):
        """
        Phân loại các khoản chi phí vận hành theo từng xe (BKS).
        Trả về dict: { 'BKS_1': [cost1, cost2], ..., 'general': [cost_chung] }
        """
        grouped = {}
        for c in self.active_operating_costs:
            plate = (c.vehicle_plate or '').strip()
            key = plate if plate and plate.lower() not in ('none', '-', 'nan') else 'general'
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(c)
        return grouped

    def to_dict(self):
        return {
            'id': self.id,
            'lot_label': self.lot_label or f"Lô #{self.id}",
            'customer_name': self.customer.name if self.customer else '',
            'company': self.company or '',
            'customs_declaration': self.customs_declaration or '',
            'month': self.month,
            'year': self.year,
            'start_date': self.start_date.strftime('%d/%m/%Y') if self.start_date else '',
            'end_date': self.end_date.strftime('%d/%m/%Y') if self.end_date else '',
            'status': self.status,
            'cost_status': self.cost_status,
            'assigned_to': self.assigned_to,
            'assignee_name': self.assignee.full_name if self.assignee else 'Chưa gán',
            'cost_deadline': self.cost_deadline.strftime('%d/%m/%Y') if self.cost_deadline else '',
            'total_sell_revenue': self.total_sell_revenue,
            'total_buy_cost': self.total_buy_cost,
            'total_operating_cost': self.total_operating_cost,
            'gross_profit': self.gross_profit,
            'net_profit': self.net_profit,
            'profit_margin': round(self.profit_margin, 1),
            'operating_cost_count': sum(1 for cost in self.operating_costs if not cost.is_deleted),
            'revenue_item_count': len(self.active_revenue_items),
            'is_sales_lot': self.is_sales_lot,
            'is_unresolved_cpvh': self.is_unresolved_cpvh,
            'source_type': self.source_type,
            'display_lot_label': self.display_lot_label,
            'distinct_vehicles': self.distinct_vehicles,
            'total_vehicle_count': self.total_vehicle_count
        }

def classify_service_category(raw_desc, fallback_hint=None):
    """Phân loại nghiệp vụ chuẩn hóa 6 nhóm: Cửa khẩu, Tờ khai, Bốc xếp, Kiểm định, Phụ phí, Vận chuyển"""
    raw = (raw_desc or '').strip()
    hint = (fallback_hint or '').strip()
    combined = f"{raw} {hint}".lower()
    
    desc_nfc = unicodedata.normalize('NFC', combined)
    desc_ascii = ''.join(c for c in unicodedata.normalize('NFD', combined) if unicodedata.category(c) != 'Mn')
    
    # 1. Kiểm định / Giám định / Quatest / Kiểm dịch
    if any(k in desc_nfc for k in ['quatest', 'lấy mẫu', 'kiểm định', 'giám định', 'giám đinh', 'kiểm dịch', 'kiểm tra chất lượng']) or \
       any(k in desc_ascii for k in ['quatest', 'lay mau', 'kiem dinh', 'giam dinh', 'kiem dich', 'kiem tra chat luong']):
        return 'Kiểm định'
        
    # 2. Bốc xếp / Sang tải / Nâng hạ / Bốc dỡ
    if any(k in desc_nfc for k in ['bốc xếp', 'bốp xếp', 'boc xep', 'sang tải', 'sang hàng', 'hạ hàng', 'nâng hạ', 'sang xe', 'cởi bạt', 'pallet', 'cơ giới sang', 'công nhân hạ']) or \
       any(k in desc_ascii for k in ['boc xep', 'bop xep', 'sang tai', 'sang hang', 'ha hang', 'nang ha', 'sang xe', 'coi bat', 'pallet', 'co gioi sang', 'cong nhan ha']):
        return 'Bốc xếp'
        
    # 3. Tờ khai / Hải quan / Thủ tục thông quan / Giám sát / Hồ sơ
    if any(k in desc_nfc for k in ['tờ khai', 'dvtk', 'dvtkhq', 'hải quan', 'thông quan', 'hồ sơ', 'tiếp nhận', 'giám sát', 'cơ động', 'trả giấy']) or \
       any(k in desc_ascii for k in ['to khai', 'dvtk', 'dvtkhq', 'hai quan', 'thong quan', 'ho so', 'tiep nhan', 'giam sat', 'co dong', 'tra giay']) or \
       re.search(r'\b(hq|dvtk|hs)\b', desc_ascii):
        return 'Tờ khai'
        
    # 4. Cửa khẩu / Bến bãi / CSHT / Biên phòng / Phương tiện
    if any(k in desc_nfc for k in ['cửa khẩu', 'cơ sở hạ tầng', 'csht', 'bến bãi', 'vé xe', 'vé cổng', 'cổng b1', 'biên phòng', 'tem xe', 'dấu đầu xe', 'mái che', 'mua phí xe', 'xe trung quốc']) or \
       any(k in desc_ascii for k in ['cua khau', 'co so ha tang', 'csht', 'ben bai', 've xe', 've cong', 'cong b1', 'bien phong', 'tem xe', 'dau dau xe', 'mai che', 'mua phi xe', 'xe trung quoc']):
        return 'Cửa khẩu'
        
    # 5. Phụ phí / Chi phí khác
    if any(k in desc_nfc for k in ['lưu ca', 'lưu kho', 'hủy xe', 'phạt', 'xử phạt', 'ngủ đêm', 'bảo hiểm', 'ổ khóa', 'thuê lái xe']) or \
       any(k in desc_ascii for k in ['luu ca', 'luu kho', 'huy xe', 'phat', 'xu phat', 'ngu dem', 'bao hiem', 'o khoa', 'thue lai xe']):
        return 'Phụ phí'
        
    # 6. Fallback based on hint
    if hint:
        hint_ascii = ''.join(c for c in unicodedata.normalize('NFD', hint.lower()) if unicodedata.category(c) != 'Mn')
        if any(k in hint_ascii for k in ['cua khau', 'ben bai', 'csht', 'bien phong']):
            return 'Cửa khẩu'
        if any(k in hint_ascii for k in ['to khai', 'thong quan', 'hai quan']):
            return 'Tờ khai'
        if any(k in hint_ascii for k in ['boc xep', 'bop xep', 'sang tai', 'nang ha']):
            return 'Bốc xếp'
        if any(k in hint_ascii for k in ['kiem dinh', 'kiem dich', 'quatest']):
            return 'Kiểm định'
            
    return 'Vận chuyển'

class RevenueItem(db.Model):
    __tablename__ = 'revenue_items'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False, index=True)
    
    supplier = db.Column(db.String(200), nullable=True)
    vehicle_plate_cn = db.Column(db.String(50), nullable=True)
    vehicle_plate_vn = db.Column(db.String(50), nullable=True)
    weight_class = db.Column(db.String(50), nullable=True)
    service_description = db.Column(db.Text, nullable=True)
    quantity = db.Column(db.Float, default=1.0)
    
    # Giá mua (CÓ VAT) & Giá bán (CHƯA VAT)
    buy_price = db.Column(db.Float, default=0.0)
    buy_price_loading = db.Column(db.Float, default=0.0)
    sell_price = db.Column(db.Float, default=0.0)
    
    # Phụ phí tiêu chuẩn
    overtime_count = db.Column(db.Float, default=0.0)
    overtime_fee = db.Column(db.Float, default=0.0)
    customs_inspection = db.Column(db.Float, default=0.0)
    infrastructure_fee = db.Column(db.Float, default=0.0)
    ticket_fee = db.Column(db.Float, default=0.0)
    new_machine_surcharge = db.Column(db.Float, default=0.0)
    oversize_surcharge = db.Column(db.Float, default=0.0)
    loading_fee = db.Column(db.Float, default=0.0)
    penalty_fee = db.Column(db.Float, default=0.0)
    
    # Phụ phí bổ sung theo từng sheet
    tan_thanh_fee = db.Column(db.Float, default=0.0)       # Lấy hàng tại Tân Thanh
    thuan_thanh_fee = db.Column(db.Float, default=0.0)     # Trả hàng tại Thuận Thành
    return_dossier_fee = db.Column(db.Float, default=0.0)  # Tiếp nhận hồ sơ quay đầu
    storage_fee = db.Column(db.Float, default=0.0)         # Lưu kho
    penalty_dossier_fee = db.Column(db.Float, default=0.0) # Phí hồ sơ xử phạt
    penalty_payment = db.Column(db.Float, default=0.0)     # Nộp xử phạt
    other_surcharge = db.Column(db.Float, default=0.0)     # Phụ phí khác
    
    # GHNLog specific
    route = db.Column(db.String(200), nullable=True)
    inspection_point = db.Column(db.Float, default=0.0)
    inspection_fee = db.Column(db.Float, default=0.0)
    routing_fee = db.Column(db.Float, default=0.0)
    empty_container = db.Column(db.Float, default=0.0)
    
    # Giá trị từ cột Tổng tiền mua và Tổng tiền bán trong Excel
    total_buy_price_excel = db.Column(db.Float, nullable=True)
    total_sell_price_excel = db.Column(db.Float, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    @property
    def total_buy_price(self):
        """Tổng tiền mua: ưu tiên lấy từ cột Tổng tiền mua trong Excel nếu có"""
        if self.total_buy_price_excel is not None:
            return self.total_buy_price_excel
        surcharges = (self.overtime_fee or 0) + (self.inspection_fee or 0) + (self.routing_fee or 0) + (self.empty_container or 0)
        return (self.buy_price or 0) + (self.buy_price_loading or 0) + surcharges

    @property
    def total_sell_price(self):
        """Tổng tiền bán: ưu tiên lấy từ cột Tổng tiền bán trong Excel nếu có"""
        if self.total_sell_price_excel is not None:
            return self.total_sell_price_excel
        surcharges = ((self.overtime_fee or 0) + (self.customs_inspection or 0) + 
                      (self.infrastructure_fee or 0) + (self.ticket_fee or 0) + 
                      (self.new_machine_surcharge or 0) + (self.oversize_surcharge or 0) + 
                      (self.loading_fee or 0) + (self.penalty_fee or 0) + 
                      (self.inspection_fee or 0) + (self.routing_fee or 0) + (self.empty_container or 0) +
                      (self.tan_thanh_fee or 0) + (self.thuan_thanh_fee or 0) +
                      (self.return_dossier_fee or 0) + (self.storage_fee or 0) +
                      (self.penalty_dossier_fee or 0) + (self.penalty_payment or 0) +
                      (self.other_surcharge or 0))
        return (self.sell_price or 0) + surcharges

    @property
    def category(self):
        """Phân loại nghiệp vụ chuẩn hóa: Cửa khẩu, Tờ khai, Bốc xếp, Kiểm định, Phụ phí, Vận chuyển"""
        return classify_service_category(self.service_description, self.weight_class)

    @property
    def display_description(self):
        """Tên dịch vụ viết rõ ràng, mở rộng viết tắt (VD: DVTK TQ -> Dịch vụ tờ khai Trung Quốc)"""
        desc = self.service_description or ''
        if not desc:
            return 'Cước vận chuyển hàng hóa'
        # Viết đầy đủ DVTK TQ -> Dịch vụ tờ khai Trung Quốc
        if re.search(r'\bDVTK\s*TQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTK\s*TQ\b', 'Dịch vụ tờ khai Trung Quốc', desc, flags=re.IGNORECASE)
        # Viết đầy đủ DVTK HQ -> Dịch vụ tờ khai Hải quan
        if re.search(r'\bDVTK\s*HQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTK\s*HQ\b', 'Dịch vụ tờ khai Hải quan', desc, flags=re.IGNORECASE)
        if re.search(r'\bDVTKHQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTKHQ\b', 'Dịch vụ tờ khai Hải quan', desc, flags=re.IGNORECASE)
        if desc.strip().upper() == 'DVTK':
            return 'Dịch vụ tờ khai'
        return desc

    def to_dict(self):
        return {
            'id': self.id,
            'supplier': self.supplier or '',
            'vehicle_plate': self.vehicle_plate_vn or self.vehicle_plate_cn or '',
            'weight_class': self.weight_class or '',
            'service_description': self.service_description or '',
            'category': self.category,
            'quantity': self.quantity or 1,
            'buy_price': self.buy_price or 0,
            'sell_price': self.sell_price or 0,
            'total_buy_price': self.total_buy_price,
            'total_sell_price': self.total_sell_price,
            'overtime_fee': self.overtime_fee or 0,
            'customs_inspection': self.customs_inspection or 0,
            'infrastructure_fee': self.infrastructure_fee or 0,
            'ticket_fee': self.ticket_fee or 0,
            'loading_fee': self.loading_fee or 0
        }

class OperatingCost(db.Model):
    __tablename__ = 'operating_costs'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False, index=True)
    
    cost_type = db.Column(db.String(100), nullable=True)  # Phí thông quan, Phí cửa khẩu...
    description = db.Column(db.Text, nullable=False)       # Nội dung chi tiết
    vehicle_plate = db.Column(db.String(50), nullable=True) # BKS
    vehicle_count = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)        # Đơn giá * SL xe (Giá Mua Vào)
    sell_price = db.Column(db.Float, default=0.0)          # Giá Bán Ra thu khách (nếu có)
    
    # Chứng từ (bắt buộc khi hoàn thành)
    invoice_type = db.Column(db.String(100), nullable=True)  # Hóa đơn GTGT, Phiếu thu, Vé xe...
    invoice_symbol = db.Column(db.String(50), nullable=True)
    invoice_number = db.Column(db.String(50), nullable=True)
    document_date = db.Column(db.Date, nullable=True)
    supplier_tax_code = db.Column(db.String(50), nullable=True)
    supplier_name = db.Column(db.String(300), nullable=True)
    
    note = db.Column(db.Text, nullable=True)
    pic = db.Column(db.String(100), nullable=True)
    cost_amount = db.Column(db.Float, default=0.0)
    vat_amount = db.Column(db.Float, default=0.0)
    payment_method = db.Column(db.String(50), default='Tiền mặt') # UNC / Tiền mặt
    
    filled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    filled_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    source_sheet = db.Column(db.String(50), nullable=True, index=True)
    source_row = db.Column(db.Integer, nullable=True)
    source_payload = db.Column(db.Text, nullable=True)
    
    filler = db.relationship('User', foreign_keys=[filled_by])

    @property
    def category(self):
        """Phân loại nghiệp vụ chuẩn hóa 6 nhóm: Cửa khẩu, Tờ khai, Bốc xếp, Kiểm định, Phụ phí, Vận chuyển"""
        return classify_service_category(self.description, self.cost_type)

    @property
    def display_cost_type(self):
        """Tên phân loại chi phí chuẩn hóa"""
        return self.category

    @property
    def display_description(self):
        """Tên chi phí viết rõ ràng, mở rộng viết tắt (VD: DVTK TQ -> Dịch vụ tờ khai Trung Quốc)"""
        desc = self.description or ''
        if not desc:
            return 'Chi phí vận hành'
        if re.search(r'\bDVTK\s*TQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTK\s*TQ\b', 'Dịch vụ tờ khai Trung Quốc', desc, flags=re.IGNORECASE)
        if re.search(r'\bDVTK\s*HQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTK\s*HQ\b', 'Dịch vụ tờ khai Hải quan', desc, flags=re.IGNORECASE)
        if re.search(r'\bDVTKHQ\b', desc, re.IGNORECASE):
            return re.sub(r'\bDVTKHQ\b', 'Dịch vụ tờ khai Hải quan', desc, flags=re.IGNORECASE)
        if desc.strip().upper() == 'DVTK':
            return 'Dịch vụ tờ khai'
        return desc

    def to_dict(self):
        return {
            'id': self.id,
            'lot_id': self.lot_id,
            'cost_type': self.cost_type or '',
            'category': self.category,
            'description': self.description or '',
            'display_description': self.display_description,
            'vehicle_plate': self.vehicle_plate or '',
            'vehicle_count': self.vehicle_count or 1,
            'unit_price': self.unit_price or 0,
            'total_amount': self.total_amount or 0,
            'invoice_type': self.invoice_type or '',
            'invoice_symbol': self.invoice_symbol or '',
            'invoice_number': self.invoice_number or '',
            'document_date': self.document_date.strftime('%d/%m/%Y') if self.document_date else '',
            'supplier_tax_code': self.supplier_tax_code or '',
            'supplier_name': self.supplier_name or '',
            'note': self.note or '',
            'pic': self.pic or '',
            'payment_method': self.payment_method or 'Tiền mặt',
            'filled_by_name': self.filler.full_name if self.filler else ''
        }

class CostEntryTask(db.Model):
    __tablename__ = 'cost_entry_tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    deadline = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'reminded', 'overdue', 'completed'
    reminder_count = db.Column(db.Integer, default=0)
    last_reminded_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    logs = db.relationship('ReminderLog', backref='task', cascade='all, delete-orphan', lazy='dynamic')
    
    @property
    def days_remaining(self):
        if not self.deadline:
            return 0
        today = date.today()
        return (self.deadline - today).days

    @property
    def is_overdue(self):
        return self.status != 'completed' and self.days_remaining < 0

    def to_dict(self):
        return {
            'id': self.id,
            'lot_id': self.lot_id,
            'lot_label': self.lot.lot_label if self.lot else '',
            'customer_name': self.lot.customer.name if (self.lot and self.lot.customer) else '',
            'customs_declaration': self.lot.customs_declaration if self.lot else '',
            'assigned_to': self.assigned_to,
            'assignee_name': self.assignee.full_name if self.assignee else '',
            'deadline': self.deadline.strftime('%d/%m/%Y'),
            'days_remaining': self.days_remaining,
            'is_overdue': self.is_overdue,
            'status': 'overdue' if self.is_overdue else self.status,
            'reminder_count': self.reminder_count,
            'last_reminded_at': self.last_reminded_at.strftime('%d/%m/%Y %H:%M') if self.last_reminded_at else ''
        }

class ReminderLog(db.Model):
    __tablename__ = 'reminder_log'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('cost_entry_tasks.id'), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    channel = db.Column(db.String(20), default='telegram')
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='sent')


class CashAdvanceMonthly(db.Model):
    __tablename__ = 'cash_advance_monthly'
    
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    sheet_name = db.Column(db.String(100), nullable=True)
    sheet_gid = db.Column(db.String(50), nullable=True)
    
    opening_balance = db.Column(db.Float, default=0.0)         # Tồn đầu kỳ
    total_company_receipts = db.Column(db.Float, default=0.0)  # Thu từ Công ty
    total_haiban_receipts = db.Column(db.Float, default=0.0)   # Thu từ Hải Bân
    total_other_receipts = db.Column(db.Float, default=0.0)    # Thu khác
    total_haiban_to_company = db.Column(db.Float, default=0.0) # Chi trả Hải Bân về cty
    total_advances_spent = db.Column(db.Float, default=0.0)    # Chi tạm ứng
    total_xuyen = db.Column(db.Float, default=0.0)             # Xuyên
    total_luong_thu = db.Column(db.Float, default=0.0)         # Lương Thu
    total_luong_chi = db.Column(db.Float, default=0.0)         # Lương Chi
    total_truong = db.Column(db.Float, default=0.0)            # Trường
    total_partner = db.Column(db.Float, default=0.0)           # Đối tác
    closing_balance = db.Column(db.Float, default=0.0)         # Tồn cuối kỳ
    
    creator_name = db.Column(db.String(100), default='Trần Xuân Trường')
    last_synced_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_locked = db.Column(db.Boolean, default=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    locked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    transactions = db.relationship('CashAdvanceTransaction', backref='monthly_sheet', cascade='all, delete-orphan', lazy='dynamic', order_by='CashAdvanceTransaction.row_index')

    __table_args__ = (db.UniqueConstraint('year', 'month', name='uq_cash_advance_month_year'),)

    def to_dict(self):
        return {
            'id': self.id,
            'month': self.month,
            'year': self.year,
            'sheet_name': self.sheet_name,
            'sheet_gid': self.sheet_gid,
            'opening_balance': self.opening_balance,
            'total_company_receipts': self.total_company_receipts,
            'total_haiban_receipts': self.total_haiban_receipts,
            'total_other_receipts': self.total_other_receipts,
            'total_haiban_to_company': self.total_haiban_to_company,
            'total_advances_spent': self.total_advances_spent,
            'total_xuyen': self.total_xuyen,
            'total_luong_thu': self.total_luong_thu,
            'total_luong_chi': self.total_luong_chi,
            'total_truong': self.total_truong,
            'total_partner': self.total_partner,
            'closing_balance': self.closing_balance,
            'creator_name': self.creator_name,
            'is_locked': self.is_locked,
            'locked_at': self.locked_at.strftime('%d/%m/%Y %H:%M') if self.locked_at else None,
            'last_synced_at': self.last_synced_at.strftime('%d/%m/%Y %H:%M') if self.last_synced_at else ''
        }


class CashAdvanceTransaction(db.Model):
    __tablename__ = 'cash_advance_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    monthly_id = db.Column(db.Integer, db.ForeignKey('cash_advance_monthly.id'), nullable=True, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    row_index = db.Column(db.Integer, default=0)
    external_id = db.Column(db.String(128), nullable=True, unique=True, index=True)
    sync_status = db.Column(db.String(30), default='synced', index=True)
    sync_hash = db.Column(db.String(64), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_reason = db.Column(db.Text, nullable=True)
    
    trans_date = db.Column(db.String(50), nullable=True)
    content = db.Column(db.Text, nullable=False)
    
    # Nhóm Tuấn
    tuan_ton = db.Column(db.Float, default=0.0)
    tuan_thu_cty = db.Column(db.Float, default=0.0)
    tuan_thu_haiban = db.Column(db.Float, default=0.0)
    tuan_thu_khac = db.Column(db.Float, default=0.0)
    tuan_chi_haiban_cty = db.Column(db.Float, default=0.0)
    tuan_chi = db.Column(db.Float, default=0.0)
    
    # Nhóm nhân sự khác
    xuyen_amount = db.Column(db.Float, default=0.0)
    luong_thu = db.Column(db.Float, default=0.0)
    luong_chi = db.Column(db.Float, default=0.0)
    truong_amount = db.Column(db.Float, default=0.0)
    
    # Đối tác & Chứng từ
    partner_amount = db.Column(db.Float, default=0.0)
    partner_invoice = db.Column(db.String(500), nullable=True)
    bill_link = db.Column(db.String(500), nullable=True)
    advance_refund = db.Column(db.String(100), nullable=True)
    accounting_status = db.Column(db.String(100), nullable=True)
    
    # === PHÂN LOẠI HÓA ĐƠN & HOÀN ỨNG (Chốt kế toán hàng tháng) ===
    invoice_category = db.Column(db.String(20), default='unknown')
    # Giá trị: 'has_invoice', 'no_invoice', 'unknown'
    
    refund_status = db.Column(db.String(20), default='pending')
    # Giá trị: 'pending', 'submitted', 'settled', 'overdue', 'excluded'
    
    refund_deadline = db.Column(db.Date, nullable=True)
    # Tự động = ngày cuối cùng của tháng giao dịch
    
    refund_settled_at = db.Column(db.DateTime, nullable=True)
    # Ngày nhân viên hoàn ứng thực tế
    
    # === LOẠI TRỪ (cho khoản Không HĐ) ===
    exclusion_status = db.Column(db.String(20), nullable=True)
    # Giá trị: None, 'pending_approval', 'approved', 'rejected'
    
    exclusion_requested_at = db.Column(db.DateTime, nullable=True)
    exclusion_approved_at = db.Column(db.DateTime, nullable=True)
    exclusion_approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    exclusion_note = db.Column(db.Text, nullable=True)
    # Ghi chú lý do loại trừ
    
    is_manual = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'monthly_id': self.monthly_id,
            'month': self.month,
            'year': self.year,
            'row_index': self.row_index,
            'trans_date': self.trans_date or '',
            'content': self.content or '',
            'tuan_ton': self.tuan_ton or 0.0,
            'tuan_thu_cty': self.tuan_thu_cty or 0.0,
            'tuan_thu_haiban': self.tuan_thu_haiban or 0.0,
            'tuan_thu_khac': self.tuan_thu_khac or 0.0,
            'tuan_chi_haiban_cty': self.tuan_chi_haiban_cty or 0.0,
            'tuan_chi': self.tuan_chi or 0.0,
            'xuyen_amount': self.xuyen_amount or 0.0,
            'luong_thu': self.luong_thu or 0.0,
            'luong_chi': self.luong_chi or 0.0,
            'truong_amount': self.truong_amount or 0.0,
            'partner_amount': self.partner_amount or 0.0,
            'partner_invoice': self.partner_invoice or '',
            'bill_link': self.bill_link or '',
            'advance_refund': self.advance_refund or '',
            'accounting_status': self.accounting_status or '',
            'invoice_category': self.invoice_category or 'unknown',
            'refund_status': self.refund_status or 'pending',
            'refund_deadline': self.refund_deadline.strftime('%d/%m/%Y') if self.refund_deadline else '',
            'refund_settled_at': self.refund_settled_at.strftime('%d/%m/%Y %H:%M') if self.refund_settled_at else '',
            'exclusion_status': self.exclusion_status or '',
            'exclusion_note': self.exclusion_note or '',
            'is_manual': self.is_manual
        }


class CashAdvanceBillMedia(db.Model):
    __tablename__ = 'cash_advance_bill_media'
    
    id = db.Column(db.String(64), primary_key=True)
    file_id = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(255), default='receipt.jpg')
    mime_type = db.Column(db.String(100), default='image/jpeg')
    file_size = db.Column(db.Integer, default=0)
    data_base64 = db.Column(db.Text, nullable=True)
    storage_url = db.Column(db.Text, nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('cash_advance_transactions.id', name='fk_cabm_transaction_id'), nullable=True, index=True)
    operating_cost_id = db.Column(db.Integer, db.ForeignKey('operating_costs.id', name='fk_cabm_operating_cost_id'), nullable=True, index=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id', name='fk_cabm_lot_id'), nullable=True, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_cabm_uploaded_by'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship('CashAdvanceTransaction', foreign_keys=[transaction_id], backref=db.backref('bill_media_items', lazy='dynamic'))
    operating_cost = db.relationship('OperatingCost', foreign_keys=[operating_cost_id], backref=db.backref('bill_media_items', lazy='dynamic'))
    lot = db.relationship('Lot', foreign_keys=[lot_id], backref=db.backref('bill_media_items', lazy='dynamic'))
    uploader = db.relationship('User', foreign_keys=[uploaded_by], backref=db.backref('uploaded_bills', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'file_id': self.file_id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'transaction_id': self.transaction_id,
            'operating_cost_id': self.operating_cost_id,
            'lot_id': self.lot_id,
            'uploaded_by': self.uploaded_by,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else ''
        }


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    actor = db.Column(db.String(100), nullable=True) # username or automated service
    action = db.Column(db.String(50), nullable=False, index=True)
    target_type = db.Column(db.String(50), nullable=False, index=True) # entity name
    target_id = db.Column(db.String(64), nullable=True, index=True)   # entity id
    before_state = db.Column(db.Text, nullable=True)                  # JSON string before mutation
    after_state = db.Column(db.Text, nullable=True)                   # JSON string after mutation
    reason = db.Column(db.Text, nullable=True)                        # reason for action
    request_id = db.Column(db.String(64), nullable=True, index=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'actor': self.actor or (self.user.username if self.user else 'system'),
            'username': self.user.username if self.user else self.actor,
            'action': self.action,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'before_state': self.before_state,
            'after_state': self.after_state,
            'reason': self.reason,
            'request_id': self.request_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M:%S') if self.created_at else ''
        }


class Quotation(db.Model):
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    quote_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(255), nullable=False)
    contact_person = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    valid_days = db.Column(db.Integer, default=15)
    items_json = db.Column(db.Text, nullable=False, default='[]')
    subtotal = db.Column(db.Float, default=0.0)
    vat_percent = db.Column(db.Float, default=10.0)
    vat_amount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='sent')
    is_deleted = db.Column(db.Boolean, default=False, index=True)

    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        import json
        try:
            items = json.loads(self.items_json or '[]')
        except Exception:
            items = []
        return {
            'id': self.id,
            'quote_code': self.quote_code,
            'customer_name': self.customer_name,
            'contact_person': self.contact_person or '',
            'phone': self.phone or '',
            'created_at': self.created_at.strftime('%d/%m/%Y') if self.created_at else '',
            'valid_days': self.valid_days or 15,
            'items': items,
            'subtotal': self.subtotal or 0.0,
            'vat_percent': self.vat_percent or 10.0,
            'vat_amount': self.vat_amount or 0.0,
            'total_amount': self.total_amount or 0.0,
            'notes': self.notes or '',
            'status': self.status or 'sent',
            'creator_name': self.creator.full_name if self.creator else ''
        }


class MonthlySettlement(db.Model):
    """Bảng chốt kế toán hàng tháng — snapshot tổng hợp cuối kỳ"""
    __tablename__ = 'monthly_settlements'

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)

    # Tổng hợp chi phí
    total_expenses = db.Column(db.Float, default=0.0)        # Tổng chi phí trong tháng
    total_with_invoice = db.Column(db.Float, default=0.0)    # Tổng có HĐ
    total_no_invoice = db.Column(db.Float, default=0.0)      # Tổng không HĐ
    total_settled = db.Column(db.Float, default=0.0)         # Đã hoàn ứng
    total_excluded = db.Column(db.Float, default=0.0)        # Đã loại trừ (sếp duyệt)
    total_overdue = db.Column(db.Float, default=0.0)         # Quá hạn chưa hoàn
    total_to_remit = db.Column(db.Float, default=0.0)        # Số tiền phải gửi về KT

    # Đếm số lượng
    count_total = db.Column(db.Integer, default=0)
    count_with_invoice = db.Column(db.Integer, default=0)
    count_no_invoice = db.Column(db.Integer, default=0)
    count_settled = db.Column(db.Integer, default=0)
    count_excluded = db.Column(db.Integer, default=0)
    count_overdue = db.Column(db.Integer, default=0)
    count_pending = db.Column(db.Integer, default=0)

    # Trạng thái chốt kỳ
    status = db.Column(db.String(20), default='open')        # open, closing, closed
    closed_at = db.Column(db.DateTime, nullable=True)
    closed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('year', 'month', name='uq_settlement_year_month'),)

    def to_dict(self):
        return {
            'id': self.id,
            'month': self.month,
            'year': self.year,
            'total_expenses': self.total_expenses,
            'total_with_invoice': self.total_with_invoice,
            'total_no_invoice': self.total_no_invoice,
            'total_settled': self.total_settled,
            'total_excluded': self.total_excluded,
            'total_overdue': self.total_overdue,
            'total_to_remit': self.total_to_remit,
            'count_total': self.count_total,
            'count_with_invoice': self.count_with_invoice,
            'count_no_invoice': self.count_no_invoice,
            'count_settled': self.count_settled,
            'count_excluded': self.count_excluded,
            'count_overdue': self.count_overdue,
            'count_pending': self.count_pending,
            'status': self.status,
            'closed_at': self.closed_at.strftime('%d/%m/%Y %H:%M') if self.closed_at else '',
            'notes': self.notes or ''
        }
