import sys
sys.stdout.reconfigure(encoding='utf-8')
from app import create_app
from app.services.calculator import CalculatorService
from app.services.comment_engine import CommentEngine
from app.services.excel_exporter import ExcelExporterService
from app.models import User

app = create_app()

with app.app_context():
    print("========================================")
    print("1. KIỂM TRA KPI THÁNG KHÔNG CÓ TARGET (11/2025)")
    print("========================================")
    kpi_11 = CalculatorService.get_monthly_kpi(11, 2025)
    print(f"Target Label: {kpi_11['target_label']}")
    print(f"Has Target: {kpi_11['has_target']}")
    print(f"Achievement Pct: {kpi_11['achievement_pct']}")
    print(f"Revenue Growth: {kpi_11['rev_growth']}")
    print(f"Sales Lot Count: {kpi_11['lot_count']}")
    print(f"Cost status - None: {kpi_11['lots_none']}, Partial: {kpi_11['lots_partial']}, Completed: {kpi_11['lots_completed']}")
    print(f"Cost completion %: {kpi_11['cost_completion_pct']}%")
    assert kpi_11['has_target'] is False, "Month 11/2025 should have no target!"
    assert kpi_11['achievement_pct'] is None, "Achievement pct should be None!"
    
    print("\n========================================")
    print("2. KIỂM TRA KPI THÁNG ĐẦU TIÊN (09/2025 - KHÔNG CÓ DỮ LIỆU THÁNG TRƯỚC)")
    print("========================================")
    kpi_09 = CalculatorService.get_monthly_kpi(9, 2025)
    print(f"Prev Revenue: {kpi_09['prev_revenue']}")
    print(f"Has Prev Data: {kpi_09['has_prev_data']}")
    print(f"Rev Growth: {kpi_09['rev_growth']}")
    assert kpi_09['has_prev_data'] is False, "Month 09/2025 should have no prev data!"
    assert kpi_09['rev_growth'] is None, "Rev growth should be None for 09/2025!"

    print("\n========================================")
    print("3. KIỂM TRA KPI THÁNG CÓ TARGET (08/2026)")
    print("========================================")
    kpi_08 = CalculatorService.get_monthly_kpi(8, 2026)
    print(f"Target Label: {kpi_08['target_label']}")
    print(f"Has Target: {kpi_08['has_target']}")
    print(f"Target Value: {kpi_08['target']:,.0f} đ")
    print(f"Achievement Pct: {kpi_08['achievement_pct']}%")
    print(f"Sales Lot Count: {kpi_08['lot_count']}")
    print(f"Cost status - None: {kpi_08['lots_none']}, Partial: {kpi_08['lots_partial']}, Completed: {kpi_08['lots_completed']}")
    print(f"Cost completion %: {kpi_08['cost_completion_pct']}%")
    assert kpi_08['has_target'] is True, "Month 08/2026 must have a target!"

    print("\n========================================")
    print("4. KIỂM TRA CƠ CẤU KHÁCH HÀNG (TOP 5 + KHÁC = 100%)")
    print("========================================")
    custs = CalculatorService.get_customer_breakdown(8, 2026)
    total_share = 0.0
    for idx, c in enumerate(custs, 1):
        print(f"  {idx}. {c['name']:30} | {c['revenue']:14,.0f} đ | {c['share']:5.1f}%")
        total_share += c['share']
    print(f"Tổng tỷ trọng: {total_share:.1f}%")
    assert abs(total_share - 100.0) < 0.5, f"Total share should be ~100%, got {total_share}%"

    print("\n========================================")
    print("5. KIỂM TRA EXCEL EXPORTER CHO CẢ 2 THÁNG")
    print("========================================")
    bio_11 = ExcelExporterService.export_monthly_report(11, 2025)
    print(f"Export 11/2025 successful, bytes: {len(bio_11.getvalue())}")
    bio_08 = ExcelExporterService.export_monthly_report(8, 2026)
    print(f"Export 08/2026 successful, bytes: {len(bio_08.getvalue())}")

    print("\n========================================")
    print("6. KIỂM TRA FLASK ENDPOINTS VỚI TEST CLIENT")
    print("========================================")
    admin = User.query.filter_by(username='admin').first()
    with app.test_client() as client:
        # Authenticate admin
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        # Test index route
        r_index = client.get('/?month=8&year=2026')
        print(f"GET /?month=8&year=2026: Status {r_index.status_code}")
        assert r_index.status_code == 200

        # Test index route for 11/2025 (Chưa có target & N/A)
        r_index_11 = client.get('/?month=11&year=2025')
        print(f"GET /?month=11&year=2025: Status {r_index_11.status_code}")
        assert r_index_11.status_code == 200
        html_11 = r_index_11.data.decode('utf-8')
        assert "Chưa có target" in html_11, "'Chưa có target' should be rendered in 11/2025!"

        # Test api_kpis
        r_kpis = client.get('/api/dashboard/kpis?month=8&year=2026')
        print(f"GET /api/dashboard/kpis?month=8&year=2026: Status {r_kpis.status_code}")
        assert r_kpis.status_code == 200
        json_kpi = r_kpis.get_json()
        assert json_kpi['revenue'] == 230328694.0

        # Test api_customers
        r_cust = client.get('/api/dashboard/customers?month=8&year=2026')
        print(f"GET /api/dashboard/customers?month=8&year=2026: Status {r_cust.status_code}")
        assert r_cust.status_code == 200
        json_cust = r_cust.get_json()
        assert len(json_cust) > 0

    print("\nALL VERIFICATION CHECKS PASSED!")
