from flask import Flask
from app.config import Config
from app.extensions import db, login_manager, migrate
from app.models import User

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Vui lòng đăng nhập để truy cập trang này.'
    login_manager.login_message_category = 'warning'
    
    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
            if user and getattr(user, 'is_active', True):
                return user
        except Exception:
            pass
        return None

    # Security & CSRF
    from app.security import generate_csrf_token, validate_csrf

    @app.context_processor
    def inject_csrf():
        return dict(csrf_token=generate_csrf_token)

    @app.before_request
    def check_csrf_protection():
        if not validate_csrf():
            from flask import jsonify, abort, request
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'CSRF token missing or invalid'}), 400
            abort(400, description="CSRF token missing or invalid. Please refresh the page and try again.")

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self' https: data: 'unsafe-inline'; "
            "img-src 'self' data: https: blob:; "
            "font-src 'self' https: data:;"
        )
        return response

    # Custom Jinja filters
    @app.template_filter('format_money')
    def format_money_filter(value):
        if value is None:
            return '0\u00a0đ'
        try:
            val = float(value)
            return f"{val:,.0f}\u00a0đ".replace(',', '.')
        except Exception:
            return '0\u00a0đ'
            
    @app.template_filter('format_compact_money')
    def format_compact_money(value):
        if value is None:
            return '0'
        try:
            val = float(value)
            if abs(val) >= 1_000_000_000:
                return f"{val / 1_000_000_000:.2f} tỷ"
            elif abs(val) >= 1_000_000:
                return f"{val / 1_000_000:.1f} tr"
            elif abs(val) >= 1_000:
                return f"{val / 1_000:.0f} k"
            return f"{val:,.0f}".replace(',', '.')
        except Exception:
            return '0'

    @app.template_filter('clean_date_vn')
    def clean_date_vn_filter(val, default_month=None, default_year=2026):
        import re
        if not val:
            return '-'
        val_str = str(val).strip()
        if not val_str or val_str == '-':
            return '-'
        
        # 1. Full date DD/MM/YYYY or DD-MM-YYYY
        m = re.match(r'^(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{4})$', val_str)
        if m:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f'{d:02d}/{mth:02d}/{y}'
        
        # YYYY-MM-DD
        m = re.match(r'^(\d{4})[/\.-](\d{1,2})[/\.-](\d{1,2})', val_str)
        if m:
            y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f'{d:02d}/{mth:02d}/{y}'
            
        # 2. 'thg 6' or 'thg6' or 'tháng 6'
        m = re.match(r'^(\d{1,2})[/\s\.-]+(?:thg|tháng)\s*(\d{1,2})', val_str, re.IGNORECASE)
        if m:
            d, mth = int(m.group(1)), int(m.group(2))
            y = default_year or 2026
            return f'{d:02d}/{mth:02d}/{y}'

        # 3. Date with English month name like '13-Aug', '7-Sep'
        month_names = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        m = re.match(r'^(\d{1,2})[/\s\.-]+([a-zA-Z]+)', val_str, re.IGNORECASE)
        if m:
            d = int(m.group(1))
            mth_str = m.group(2).lower()[:3]
            if mth_str in month_names:
                mth = month_names[mth_str]
                y = default_year or 2026
                return f'{d:02d}/{mth:02d}/{y}'

        # 4. Just day number e.g. '13' or '25'
        m = re.match(r'^(\d{1,2})$', val_str)
        if m and default_month:
            d = int(m.group(1))
            y = default_year or 2026
            return f'{d:02d}/{int(default_month):02d}/{y}'

        return val_str

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.lots import lots_bp
    from app.routes.costs import costs_bp
    from app.routes.tasks import tasks_bp
    from app.routes.suppliers import suppliers_bp
    from app.routes.users import users_bp
    from app.routes.advances import advances_bp
    from app.routes.reports import reports_bp
    from app.routes.quotations import quotations_bp
    from app.routes.customers import customers_bp
    from app.routes.audit import audit_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(lots_bp, url_prefix='/lots')
    app.register_blueprint(costs_bp, url_prefix='/costs')
    app.register_blueprint(tasks_bp, url_prefix='/tasks')
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(advances_bp, url_prefix='/advances')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(audit_bp, url_prefix='/audit')
    app.register_blueprint(quotations_bp, url_prefix='/quotations')
    app.register_blueprint(customers_bp, url_prefix='/customers')
    
    # Auto ensure essential schema updates
    try:
        with app.app_context():
            from sqlalchemy import text
            with db.engine.connect() as conn:
                db_url = str(db.engine.url)
                if 'sqlite' in db_url:
                    op_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(operating_costs)")).fetchall()]
                    rev_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(revenue_items)")).fetchall()]
                    for col, typ in [('invoice_classification', 'VARCHAR(50)'), ('revenue_month', 'INT'), ('revenue_year', 'INT'), ('revenue_invoice_date', 'DATE'), ('revenue_invoice_number', 'VARCHAR(100)')]:
                        if op_cols and col not in op_cols:
                            conn.execute(text(f"ALTER TABLE operating_costs ADD COLUMN {col} {typ}"))
                    for col, typ in [('revenue_month', 'INT'), ('revenue_year', 'INT'), ('revenue_invoice_date', 'DATE'), ('revenue_invoice_number', 'VARCHAR(100)')]:
                        if rev_cols and col not in rev_cols:
                            conn.execute(text(f"ALTER TABLE revenue_items ADD COLUMN {col} {typ}"))
                    conn.commit()
                elif 'postgres' in db_url:
                    conn.execute(text("ALTER TABLE operating_costs ADD COLUMN IF NOT EXISTS invoice_classification VARCHAR(50);"))
                    conn.execute(text("ALTER TABLE operating_costs ADD COLUMN IF NOT EXISTS revenue_month INT;"))
                    conn.execute(text("ALTER TABLE operating_costs ADD COLUMN IF NOT EXISTS revenue_year INT;"))
                    conn.execute(text("ALTER TABLE operating_costs ADD COLUMN IF NOT EXISTS revenue_invoice_date DATE;"))
                    conn.execute(text("ALTER TABLE operating_costs ADD COLUMN IF NOT EXISTS revenue_invoice_number VARCHAR(100);"))
                    conn.execute(text("ALTER TABLE revenue_items ADD COLUMN IF NOT EXISTS revenue_month INT;"))
                    conn.execute(text("ALTER TABLE revenue_items ADD COLUMN IF NOT EXISTS revenue_year INT;"))
                    conn.execute(text("ALTER TABLE revenue_items ADD COLUMN IF NOT EXISTS revenue_invoice_date DATE;"))
                    conn.execute(text("ALTER TABLE revenue_items ADD COLUMN IF NOT EXISTS revenue_invoice_number VARCHAR(100);"))
                    conn.commit()
    except Exception as e:
        app.logger.warning(f"Auto schema update warning: {e}")

    return app
