from datetime import date
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.services.calculator import CalculatorService
from app.services.comment_engine import CommentEngine

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    months = CalculatorService.get_available_months()
    # Default to latest month in database or current month
    default_year = 2026
    default_month = 8
    if months:
        default_year, default_month = months[0]
        
    selected_month = request.args.get('month', default_month, type=int)
    selected_year = request.args.get('year', default_year, type=int)
    
    kpi = CalculatorService.get_monthly_kpi(selected_month, selected_year)
    comments = CommentEngine.generate_comments(selected_month, selected_year, kpi=kpi)
    
    return render_template(
        'dashboard.html',
        months=months,
        selected_month=selected_month,
        selected_year=selected_year,
        kpi=kpi,
        comments=comments
    )

@dashboard_bp.route('/api/dashboard/kpis')
@login_required
def api_kpis():
    month = request.args.get('month', 8, type=int)
    year = request.args.get('year', 2026, type=int)
    kpis = CalculatorService.get_monthly_kpi(month, year)
    return jsonify(kpis)

@dashboard_bp.route('/api/dashboard/trend')
@login_required
def api_trend():
    year = request.args.get('year', 2026, type=int)
    data = CalculatorService.get_year_trend(year)
    return jsonify(data)

@dashboard_bp.route('/api/dashboard/customers')
@login_required
def api_customers():
    month = request.args.get('month', 8, type=int)
    year = request.args.get('year', 2026, type=int)
    customers = CalculatorService.get_customer_breakdown(month, year)
    return jsonify(customers)

