from datetime import date
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.models import CostEntryTask, Lot
from app.security import manager_required
from app.services.calculator import CalculatorService
from app.services.comment_engine import CommentEngine

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
@manager_required
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
    customers = CalculatorService.get_customer_breakdown(selected_month, selected_year)
    comments = CommentEngine.generate_comments(selected_month, selected_year, kpi=kpi, customers=customers)
    trend = CalculatorService.get_year_trend(selected_year)
    
    overdue_count = CostEntryTask.query.join(Lot).filter(
        Lot.month == selected_month,
        Lot.year == selected_year,
        Lot.is_deleted == False,
        CostEntryTask.status != 'completed',
        CostEntryTask.deadline < date.today()
    ).count()

    return render_template(
        'dashboard.html',
        months=months,
        selected_month=selected_month,
        selected_year=selected_year,
        kpi=kpi,
        comments=comments,
        customers=customers,
        trend=trend,
        overdue_count=overdue_count
    )

@dashboard_bp.route('/api/dashboard/kpis')
@login_required
@manager_required
def api_kpis():
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    kpis = CalculatorService.get_monthly_kpi(month, year)
    return jsonify(kpis)

@dashboard_bp.route('/api/dashboard/trend')
@login_required
@manager_required
def api_trend():
    year = request.args.get('year', date.today().year, type=int)
    data = CalculatorService.get_year_trend(year)
    return jsonify(data)

@dashboard_bp.route('/api/dashboard/customers')
@login_required
@manager_required
def api_customers():
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    customers = CalculatorService.get_customer_breakdown(month, year)
    return jsonify(customers)
