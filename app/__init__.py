from flask import Flask
from app.config import Config
from app.extensions import db, login_manager
from app.models import User

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
        
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

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.lots import lots_bp
    from app.routes.costs import costs_bp
    from app.routes.tasks import tasks_bp
    from app.routes.suppliers import suppliers_bp
    from app.routes.users import users_bp
    from app.routes.advances import advances_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(lots_bp, url_prefix='/lots')
    app.register_blueprint(costs_bp, url_prefix='/costs')
    app.register_blueprint(tasks_bp, url_prefix='/tasks')
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(advances_bp, url_prefix='/advances')
    
    return app
