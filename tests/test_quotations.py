import json
import pytest
from app.models import Quotation, RevenueItem, OperatingCost, Lot
from app.extensions import db
from app.services.quotation_service import (
    get_all_benchmarks,
    get_benchmarks_filtered,
    find_best_benchmark,
    get_quick_options
)

@pytest.fixture
def seed_quotation_data(app):
    with app.app_context():
        lot = Lot(month=8, year=2026, lot_label='Lô 08.2026 Test')
        db.session.add(lot)
        db.session.flush()

        # Add Revenue Items
        r1 = RevenueItem(
            lot_id=lot.id,
            service_description='Hữu Nghị - Phú Thọ',
            weight_class='cont 45',
            buy_price=7400000.0,
            sell_price=8200000.0
        )
        r2 = RevenueItem(
            lot_id=lot.id,
            service_description='Phí cửa khẩu',
            weight_class='8T',
            buy_price=1200000.0,
            sell_price=1500000.0
        )
        r3 = RevenueItem(
            lot_id=lot.id,
            service_description='DVTK HQ',
            weight_class='',
            buy_price=3500000.0,
            sell_price=4500000.0
        )

        # Add Operating Costs
        c1 = OperatingCost(
            lot_id=lot.id,
            cost_type='Kiểm định',
            description='Quatest lấy mẫu sớm VN26040',
            total_amount=1500000.0,
            unit_price=1500000.0,
            sell_price=2000000.0
        )
        c2 = OperatingCost(
            lot_id=lot.id,
            cost_type='Bốc xếp',
            description='Chi phí bốc xếp hàng Keep ở Đồng Đăng',
            total_amount=950000.0,
            unit_price=950000.0,
            sell_price=1200000.0
        )

        db.session.add_all([r1, r2, r3, c1, c2])
        db.session.commit()
        yield lot.id


def test_get_all_benchmarks(app, seed_quotation_data):
    with app.app_context():
        benchmarks = get_all_benchmarks()
        assert isinstance(benchmarks, list)
        assert len(benchmarks) >= 5

        # Check required keys in each benchmark item
        item = benchmarks[0]
        for key in ['category', 'name', 'spec', 'count', 'recommended_price', 'basis_text']:
            assert key in item

        # Verify basis text is informative
        assert 'Dựa trên' in item['basis_text']
        assert item['count'] >= 1
        assert item['recommended_price'] >= 0


def test_find_best_benchmark(app, seed_quotation_data):
    with app.app_context():
        # Test finding existing route
        match = find_best_benchmark('Vận chuyển', 'Hữu Nghị - Phú Thọ', 'cont 45')
        assert match is not None
        assert match['category'] == 'Vận chuyển'
        assert match['recommended_price'] > 0
        assert 'Hữu Nghị' in match['basis_text'] or 'chuyến' in match['basis_text']

        # Test finding inspection / quatest
        match_qt = find_best_benchmark('Kiểm định', 'Quatest')
        assert match_qt is not None
        assert match_qt['category'] == 'Kiểm định'

        # Test fallback for non-existent service in known category
        match_fallback = find_best_benchmark('Cửa khẩu', 'Dịch vụ hoàn toàn mới chưa từng có')
        assert match_fallback is not None
        assert 'cửa khẩu' in match_fallback['basis_text'].lower()


def test_quick_options(app, seed_quotation_data):
    with app.app_context():
        opts = get_quick_options()
        assert 'routes' in opts
        assert 'vehicles' in opts
        assert 'categories_count' in opts
        assert len(opts['routes']) >= 5


def test_quotations_views_and_api(auth_client_manager, app, seed_quotation_data):
    # Test GET index page
    res = auth_client_manager.get('/quotations/')
    assert res.status_code == 200
    assert 'Đề Xuất Báo Giá' in res.data.decode('utf-8')
    assert 'Tra Cứu Giá Lịch Sử' in res.data.decode('utf-8')

    # Test API benchmarks
    res_api = auth_client_manager.get('/quotations/api/benchmarks?category=Vận chuyển')
    assert res_api.status_code == 200
    data = json.loads(res_api.data.decode('utf-8'))
    assert data['success'] is True
    assert len(data['data']) > 0

    # Test API suggest
    res_sug = auth_client_manager.get('/quotations/api/suggest?category=Vận chuyển&name=Hữu Nghị - Phú Thọ&spec=cont 45')
    assert res_sug.status_code == 200
    sug_data = json.loads(res_sug.data.decode('utf-8'))
    assert sug_data['success'] is True
    assert sug_data['recommended_price'] > 0
    assert 'basis_text' in sug_data


def test_create_and_view_quotation(auth_client_manager, app):
    with app.app_context():
        payload = {
            'customer_name': 'Công ty Test Đề Xuất Báo Giá',
            'contact_person': 'Nguyễn Văn Test',
            'phone': '0901234567',
            'valid_days': 20,
            'vat_percent': 10,
            'items': [
                {
                    'category': 'Vận chuyển',
                    'name': 'Hữu Nghị - Phú Thọ',
                    'spec': 'Cont 45',
                    'unit': 'Chuyến',
                    'quantity': 2,
                    'unit_price': 8000000,
                    'basis': 'Dựa trên 85 chuyến thực tế'
                },
                {
                    'category': 'Kiểm định',
                    'name': 'Dịch vụ Quatest',
                    'spec': '',
                    'unit': 'Mẫu',
                    'quantity': 1,
                    'unit_price': 4000000,
                    'basis': 'Dựa trên giá lịch sử'
                }
            ],
            'notes': 'Thanh toán sau 30 ngày'
        }

        res = auth_client_manager.post('/quotations/api/save',
                                      data=json.dumps(payload),
                                      content_type='application/json',
                                      headers={'X-CSRFToken': 'test_csrf_token'})
        assert res.status_code == 200
        res_data = json.loads(res.data.decode('utf-8'))
        assert res_data['success'] is True
        quote_id = res_data['quote_id']
        assert 'quote_code' in res_data
        assert res_data['quote_code'].startswith('BG-')

        # Check in DB
        quote = db.session.get(Quotation, quote_id)
        assert quote is not None
        assert quote.customer_name == 'Công ty Test Đề Xuất Báo Giá'
        assert quote.subtotal == 20000000.0  # 2 * 8tr + 1 * 4tr
        assert quote.vat_amount == 2000000.0 # 10%
        assert quote.total_amount == 22000000.0

        # View quotation page
        res_view = auth_client_manager.get(f'/quotations/{quote_id}')
        assert res_view.status_code == 200
        content = res_view.data.decode('utf-8')
        assert quote.quote_code in content
        assert 'Công ty Test Đề Xuất Báo Giá' in content
        assert 'Hữu Nghị - Phú Thọ' in content

        # Soft delete
        res_del = auth_client_manager.post(f'/quotations/{quote_id}/delete',
                                           headers={'X-CSRFToken': 'test_csrf_token'})
        assert res_del.status_code == 302
        db.session.refresh(quote)
        assert quote.is_deleted is True


def test_detailed_pricing_matrix(app, seed_quotation_data):
    """Kiểm tra chi tiết biểu cước theo xe 5T, 8T, Cont; bốc xếp theo kg, khối CBM; Quatest; Tờ khai A11; Bảo hiểm"""
    with app.app_context():
        benchmarks = get_all_benchmarks()

        # 1. Kiểm tra phân loại xe cho tuyến Vận chuyển
        vc_items = [b for b in benchmarks if b['category'] == 'Vận chuyển']
        vc_specs = {b['spec'] for b in vc_items}
        assert 'Xe 5 Tấn (5T)' in vc_specs
        assert 'Xe 8 Tấn (8T)' in vc_specs
        assert 'Container 45 feet (Cont 45)' in vc_specs

        # 2. Kiểm tra Bốc xếp theo kg và theo CBM khối
        bx_items = [b for b in benchmarks if b['category'] == 'Bốc xếp']
        bx_units = {b['unit'] for b in bx_items}
        assert 'kg' in bx_units
        assert 'CBM (m³)' in bx_units
        assert 'Tấn' in bx_units

        # 3. Kiểm tra Kiểm định Quatest và Kiểm dịch y tế
        kd_items = [b for b in benchmarks if b['category'] == 'Kiểm định']
        kd_names = [b['name'] for b in kd_items]
        assert any('Quatest' in n for n in kd_names)
        assert any('Kiểm dịch' in n for n in kd_names)

        # 4. Kiểm tra Tờ khai theo loại hình A11, A12, E21, H11
        tk_items = [b for b in benchmarks if b['category'] == 'Tờ khai']
        tk_specs = [b['spec'] for b in tk_items]
        assert any('A11' in s for s in tk_specs)
        assert any('A12' in s for s in tk_specs)
        assert any('E21' in s for s in tk_specs)

        # 5. Kiểm tra Bảo hiểm hàng hóa All Risks
        bh_items = [b for b in benchmarks if b['category'] == 'Bảo hiểm']
        assert len(bh_items) >= 2
        assert any('0.08%' in b['spec'] or b['recommended_price'] == 0.08 for b in bh_items)


def test_transport_matrix_data(app):
    """Kiểm tra ma trận cước vận chuyển chuẩn hoá theo tuyến và 12 loại tải trọng xe"""
    from app.services.quotation_service import get_transport_matrix
    matrix = get_transport_matrix()
    assert 'columns' in matrix
    assert 'data' in matrix
    assert 'notes' in matrix
    assert len(matrix['columns']) == 15
    assert len(matrix['data']) >= 10
    assert len(matrix['notes']) >= 5

    # Kiểm tra cột đầu tiên là điểm đi, cột thứ hai là điểm đến
    col_keys = [c[0] for c in matrix['columns']]
    assert 'diem_di' in col_keys
    assert 'diem_den' in col_keys
    assert 'xe_5t' in col_keys
    assert 'cont_40' in col_keys
    assert 'xe_fooc_18m' in col_keys


def test_generate_standard_quotation_excel():
    """Kiểm tra sinh file Excel Báo Giá Chuẩn đầy đủ 5 sheet"""
    from app.services.quotation_excel_generator import generate_standard_quotation_excel
    wb = generate_standard_quotation_excel()
    assert wb is not None
    sheet_names = wb.sheetnames
    assert 'Cước Vận Chuyển' in sheet_names
    assert 'Bốc Xếp & Nâng Hạ' in sheet_names
    assert 'Thủ Tục Hải Quan' in sheet_names
    assert 'Kiểm Định & Quatest' in sheet_names
    assert 'Bến Bãi & Phụ Phí' in sheet_names

    ws_vc = wb['Cước Vận Chuyển']
    assert ws_vc.max_row >= 15
    assert ws_vc.max_column >= 15


def test_download_standard_excel_route(auth_client_manager):
    """Kiểm tra tải file Excel Báo Giá Chuẩn qua endpoint GET /quotations/download-standard-excel"""
    res = auth_client_manager.get('/quotations/download-standard-excel')
    assert res.status_code == 200
    assert 'spreadsheetml' in res.content_type
    assert len(res.data) > 5000  # Valid excel binary content


def test_export_quotation_to_excel_route(app, auth_client_manager, seed_quotation_data):
    """Kiểm tra xuất file Excel cho một bảng báo giá cụ thể"""
    with app.app_context():
        quote = Quotation(
            quote_code='BG-202609-EXCEL',
            customer_name='Công ty TNHH Thử Nghiệm Excel',
            contact_person='Mr. Nam',
            phone='0912345678',
            valid_days=15,
            items_json=json.dumps([
                {
                    'category': 'Vận chuyển',
                    'name': 'Xuân Cương -> Bắc Ninh',
                    'spec': 'Xe 5 Tấn (5.8x2.1x2.1m)',
                    'unit': 'Chuyến',
                    'quantity': 2,
                    'unit_price': 3450000.0,
                    'total': 6900000.0
                }
            ]),
            subtotal=6900000.0,
            vat_percent=10.0,
            vat_amount=690000.0,
            total_amount=7590000.0
        )
        db.session.add(quote)
        db.session.commit()
        qid = quote.id

    res = auth_client_manager.get(f'/quotations/{qid}/export-excel')
    assert res.status_code == 200
    assert 'spreadsheetml' in res.content_type

def test_clean_route_names_and_sample_lots(app, seed_quotation_data):
    """Kiểm tra toàn bộ tuyến đường đã chuẩn hoá Tỉnh - Tỉnh và có link đối chứng lô hàng"""
    with app.app_context():
        benchmarks = get_all_benchmarks()
        vc_items = [b for b in benchmarks if b['category'] == 'Vận chuyển']

        # 1. Tuyến đường không được chứa tiền tố Vận chuyển / Cước vận chuyển
        for it in vc_items:
            name = it['name']
            assert not name.lower().startswith('vận chuyển')
            assert not name.lower().startswith('cước vận chuyển')
            assert not name.lower().startswith('cước vận chuyển')
            assert not name.lower().startswith('vc ')
            assert ' - ' in name or ' -> ' in name or name in ['Nội thành', 'Ngoại thành']

        # 2. Toàn bộ benchmark có sample_lots với cấu trúc id, label
        items_with_lots = [b for b in benchmarks if b.get('sample_lots')]
        assert len(items_with_lots) > 0
        sample_lot = items_with_lots[0]['sample_lots'][0]
        assert 'id' in sample_lot
        assert 'label' in sample_lot


def test_matrix_quotation_view_format(app, auth_client_manager):
    """Kiểm tra giao diện báo giá xuất ra ở định dạng Bảng Ma Trận & Biểu Phí Phụ Trợ (KHÔNG PHẢI HÓA ĐƠN BÁN LẺ)"""
    with app.app_context():
        quote = Quotation(
            quote_code='BG-202609-MATRIX',
            customer_name='Tập đoàn Foxconn Việt Nam',
            contact_person='Trần Văn Long',
            phone='0988776655',
            valid_days=30,
            items_json=json.dumps([
                {
                    'type': 'route_matrix',
                    'category': 'Vận chuyển',
                    'diem_di': 'Hữu Nghị',
                    'diem_den': 'Bắc Ninh',
                    'name': 'Hữu Nghị - Bắc Ninh',
                    'xe_1_9t': 2400000,
                    'xe_5t': 3700000,
                    'xe_8t': 4500000,
                    'cont_45': 6400000,
                    'xe_rao_14m': 8300000,
                    'xe_fooc_18m': 13800000,
                    'thoi_hieu': '16h D+1',
                    'quantity': 1,
                    'unit_price': 6400000
                },
                {
                    'type': 'aux_service',
                    'category': 'Bốc xếp',
                    'name': 'Bốc xếp hàng hóa theo kg',
                    'spec': 'Hàng nặng',
                    'unit': 'kg',
                    'quantity': 1,
                    'unit_price': 180,
                    'notes': 'Dỡ tại kho Lạng Sơn'
                }
            ]),
            subtotal=6400180,
            vat_percent=10,
            vat_amount=640018,
            total_amount=7040198
        )
        db.session.add(quote)
        db.session.commit()
        qid = quote.id

    res = auth_client_manager.get(f'/quotations/{qid}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')

    # Phải có bảng ma trận 12 cột xe
    assert 'Bảng Ma Trận Cước Vận Chuyển Đường Bộ' in html
    assert 'Hữu Nghị' in html
    assert 'Bắc Ninh' in html
    assert '6,400,000' in html or '6.400.000' in html
    assert '3,700,000' in html or '3.700.000' in html

    # Phải có biểu phí phụ trợ
    assert 'Biểu Phí Dịch Vụ Phụ Trợ' in html
    assert 'Bốc xếp hàng hóa theo kg' in html
    assert '180' in html

    # Phải có điều khoản cước & lưu ca bậc thang
    assert 'lưu ca bậc thang' in html.lower()
    assert '1.000.000' in html or '1,000,000' in html

    # KHÔNG được có bảng hóa đơn bán lẻ bán hàng
    assert 'Thành tiền: 5đ' not in html



