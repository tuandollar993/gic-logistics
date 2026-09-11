"""
Routes cho tính năng AI Báo Cáo Hoạt Động Hàng Tháng.
Blueprint: reports_bp, prefix: /reports
"""

from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required
from app.security import manager_required
from app.services.calculator import CalculatorService
from app.services.report_service import ReportDataCollector, GeminiReportWriter, WordExporter

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/')
@login_required
@manager_required
def index():
    """Trang chính của AI Báo Cáo — hiển thị form chọn kỳ và preview."""
    months = CalculatorService.get_available_months()

    default_year = 2026
    default_month = 8
    if months:
        default_year, default_month = months[0]

    selected_month = request.args.get('month', default_month, type=int)
    selected_year = request.args.get('year', default_year, type=int)

    return render_template(
        'reports.html',
        months=months,
        selected_month=selected_month,
        selected_year=selected_year
    )


@reports_bp.route('/generate', methods=['POST'])
@login_required
@manager_required
def generate():
    """
    Gọi AI generate báo cáo tháng.
    Request JSON: { month, year, report_type: 'kqkd' | 'cross_border' }
    Response JSON: { status, type, month, year, sections, data, generated_at }
    """
    payload = request.get_json(silent=True) or {}
    month = payload.get('month', 8)
    year = payload.get('year', 2026)
    report_type = payload.get('report_type', 'kqkd')

    try:
        # 1. Thu thập dữ liệu từ DB
        data = ReportDataCollector.collect(month, year)

        # 2. Gọi Gemini AI sinh nội dung
        report = GeminiReportWriter.generate_report(data, report_type=report_type)

        safe_data = {
            'kpi': report['data']['kpi'],
            'topline_table': report['data'].get('topline_table', {}),
            'monthly_cont_stats': report['data'].get('monthly_cont_stats', []),
            'total_period_declarations': report['data'].get('total_period_declarations', 0),
            'total_period_containers': report['data'].get('total_period_containers', 0),
            'storage_ratio_text': report['data'].get('storage_ratio_text', ''),
            'storage_pct': report['data'].get('storage_pct', 0.0),
            'customer_monthly_tables': report['data'].get('customer_monthly_tables', []),
            'potential_customers': report['data'].get('potential_customers', []),
            'staff_plan': report['data'].get('staff_plan', []),
            'proposals': report['data'].get('proposals', []),
            'charts_b64': report['data'].get('charts_b64', {})
        }

        return jsonify({
            'success': True,
            'status': report['status'],
            'type': report['type'],
            'month': report['month'],
            'year': report['year'],
            'sections': report['sections'],
            'data': safe_data,
            'generated_at': report['generated_at']
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi khi tạo báo cáo: {str(e)}'
        }), 500


@reports_bp.route('/download', methods=['POST'])
@login_required
@manager_required
def download():
    """
    Tải xuống báo cáo dạng Word .docx.
    Request JSON: { month, year, report_type, sections (edited by user) }
    """
    payload = request.get_json(silent=True) or {}
    month = payload.get('month', 8)
    year = payload.get('year', 2026)
    report_type = payload.get('report_type', 'kqkd')
    edited_sections = payload.get('sections', {})

    try:
        # Thu thập dữ liệu từ DB
        data = ReportDataCollector.collect(month, year)

        # Nếu user đã chỉnh sửa sections, dùng bản chỉnh sửa
        # Nếu không, generate mới
        if edited_sections:
            report_data = {
                'type': report_type,
                'month': month,
                'year': year,
                'sections': edited_sections,
                'data': data
            }
        else:
            report_data = GeminiReportWriter.generate_report(data, report_type=report_type)

        # Xuất Word
        if report_type == 'cross_border':
            buffer = WordExporter.export_cross_border(report_data)
            filename = f'Bao_cao_Cross_Border_T{month:02d}_{year}.docx'
        else:
            buffer = WordExporter.export_kqkd(report_data)
            filename = f'Bao_cao_KQKD_T{month:02d}_{year}.docx'

        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi khi xuất Word: {str(e)}'
        }), 500
