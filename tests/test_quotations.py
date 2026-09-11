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
        assert match_fallback['category'] == 'Cửa khẩu'
        assert 'Cửa khẩu' in match_fallback['basis_text']


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
