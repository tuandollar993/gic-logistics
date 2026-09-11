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
    def is_manager(self):
        return self.role == 'manager'
    
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
    
    lots = db.relationship('Lot', backref='customer', lazy='dynamic')

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
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    company = db.Column(db.String(200), nullable=True)   # Johnson 2, Sunluxe, Keep Rise...
    customs_declaration = db.Column(db.String(150), nullable=True, index=True)  # Số tờ khai HQ
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    
    source_sheet = db.Column(db.String(50), nullable=True)
    source_type = db.Column(db.String(20), default='gido')  # 'gido' hoặc 'ghnlog'
    
    # Workflow
    status = db.Column(db.String(20), default='pending')  # 'pending', 'assigned', 'in_progress', 'completed'
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cost_deadline = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    revenue_items = db.relationship('RevenueItem', backref='lot', cascade='all, delete-orphan', lazy='joined')
    operating_costs = db.relationship('OperatingCost', backref='lot', cascade='all, delete-orphan', lazy='joined')
    tasks = db.relationship('CostEntryTask', backref='lot', cascade='all, delete-orphan', lazy='dynamic')
    
    @property
    def total_sell_revenue(self):
        """Tổng doanh thu bán (chưa VAT) của lô"""
        return sum(item.total_sell_price for item in self.revenue_items)
    
    @property
    def total_buy_cost(self):
        """Tổng chi phí mua (đã có VAT) từ báo cáo bán hàng"""
        return sum(item.total_buy_price for item in self.revenue_items)
    
    @property
    def total_operating_cost(self):
        """Tổng chi phí vận hành thực tế do nhân viên điền"""
        return sum(cost.total_amount or 0 for cost in self.operating_costs)
    
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
            return (self.net_profit / rev) * 100
        return 0.0

    @property
    def is_sales_lot(self):
        """Phân biệt lô bán hàng thực tế với các lô CPVH tạo tự động khi không ghép được"""
        return self.source_type != 'cpvh'

    @property
    def cost_status(self):
        """
        Trạng thái điền chi phí vận hành:
        - 'none': Chưa có chi phí
        - 'partial': Có chi phí nhưng chưa đủ thông tin hợp lệ
        - 'completed': Đã đủ thông tin hợp lệ và hoàn tất
        """
        costs = self.operating_costs
        if not costs or len(costs) == 0:
            return 'none'
        all_valid = True
        for c in costs:
            has_desc = bool(c.description and c.description.strip())
            has_amount = bool((c.total_amount and c.total_amount > 0) or (c.cost_amount and c.cost_amount > 0))
            has_doc = bool(c.invoice_type or c.invoice_number or (c.note and 'không hđ' in c.note.lower()))
            has_supp = bool(c.supplier_name or c.supplier_tax_code)
            if not (has_desc and has_amount and has_doc and has_supp):
                all_valid = False
                break
        if all_valid and self.status == 'completed':
            return 'completed'
        return 'partial'

    @property
    def is_cost_complete(self):
        return self.cost_status == 'completed'

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
            'operating_cost_count': len(self.operating_costs),
            'revenue_item_count': len(self.revenue_items)
        }

class RevenueItem(db.Model):
    __tablename__ = 'revenue_items'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False)
    
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

    def to_dict(self):
        return {
            'id': self.id,
            'supplier': self.supplier or '',
            'vehicle_plate': self.vehicle_plate_vn or self.vehicle_plate_cn or '',
            'weight_class': self.weight_class or '',
            'service_description': self.service_description or '',
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
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False)
    
    cost_type = db.Column(db.String(100), nullable=True)  # Phí thông quan, Phí cửa khẩu...
    description = db.Column(db.Text, nullable=False)       # Nội dung chi tiết
    vehicle_plate = db.Column(db.String(50), nullable=True) # BKS
    vehicle_count = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)        # Đơn giá * SL xe
    
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
    
    filler = db.relationship('User', foreign_keys=[filled_by])

    def to_dict(self):
        return {
            'id': self.id,
            'lot_id': self.lot_id,
            'cost_type': self.cost_type or '',
            'description': self.description or '',
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
