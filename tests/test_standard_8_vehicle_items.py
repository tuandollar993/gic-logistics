import pytest
from app.extensions import db
from app.models import Lot, RevenueItem, OperatingCost, classify_standard_vehicle_slot

def test_classify_standard_vehicle_slot():
    """Kiểm tra độ chính xác của hàm phân loại 8 slot chuẩn."""
    assert classify_standard_vehicle_slot('Cước vận chuyển Lạng Sơn - TP. Hồ Chí Minh', 'Vận chuyển') == 1
    assert classify_standard_vehicle_slot('Chi phí dịch vụ bốc xếp', 'Bốc xếp') == 2
    assert classify_standard_vehicle_slot('Dịch vụ Quatest', 'Kiểm định') == 3
    assert classify_standard_vehicle_slot('Phí cửa khẩu', 'Cửa khẩu') == 4
    assert classify_standard_vehicle_slot('Dịch vụ tờ khai Hải quan', 'Tờ khai') == 5
    assert classify_standard_vehicle_slot('DVTK HQ', 'Tờ khai') == 5
    assert classify_standard_vehicle_slot('Phí Cơ sở hạ tầng', 'Cửa khẩu') == 6
    assert classify_standard_vehicle_slot('Phí CSHT', 'Cửa khẩu') == 6
    assert classify_standard_vehicle_slot('Vé xe', 'Cửa khẩu') == 7
    assert classify_standard_vehicle_slot('Chi phí lưu kho HTT (1 cont TQ = 2 cont VN)', 'Phụ phí') == 8
    assert classify_standard_vehicle_slot('Lưu kho', 'Phụ phí') == 8

def test_ensure_standard_vehicle_items_single_vehicle(app):
    """Kiểm tra xe có 1 mục cước ban đầu được tự động bổ sung đủ 8 mục với giá trị 0 đ."""
    with app.app_context():
        lot = Lot(month=9, year=2026, lot_label='Lô Test 8 Mục')
        db.session.add(lot)
        db.session.flush()

        # Xe 1 chỉ có Cước vận chuyển: mua 30,000,000, bán 40,000,000
        ri1 = RevenueItem(
            lot_id=lot.id,
            vehicle_plate_vn='51C-999.88',
            weight_class='Cont (1)',
            service_description='Cước vận chuyển Lạng Sơn - TP. HCM',
            buy_price=30000000.0,
            sell_price=40000000.0,
            total_buy_price_excel=30000000.0,
            total_sell_price_excel=40000000.0
        )
        db.session.add(ri1)
        db.session.commit()

        initial_buy = lot.total_buy_cost
        initial_sell = lot.total_sell_revenue
        initial_profit = lot.net_profit

        # Chạy ensure
        added = lot.ensure_standard_vehicle_items()
        assert added == 7  # 7 mục còn lại (từ slot 2 đến 8)
        db.session.commit()

        # Kiểm tra tính lũy tiến/idempotent: chạy lần 2 không sinh thêm
        assert lot.ensure_standard_vehicle_items() == 0

        # Kiểm tra tài chính không bị biến động
        assert lot.total_buy_cost == initial_buy
        assert lot.total_sell_revenue == initial_sell
        assert lot.net_profit == initial_profit

        # Kiểm tra breakdown của xe
        breakdown = lot.vehicles_breakdown
        assert len(breakdown) == 1
        v1 = breakdown[0]
        assert v1['plate'] == '51C-999.88'
        assert len(v1['items']) == 8

        # Kiểm tra đúng thứ tự slot từ 1 đến 8
        slots = [it['slot'] for it in v1['items']]
        assert slots == [1, 2, 3, 4, 5, 6, 7, 8]

        # Kiểm tra các mục bổ sung có giá mua/bán = 0
        for it in v1['items'][1:]:  # Từ slot 2 đến 8
            obj = it['obj']
            assert obj.effective_total_buy_price == 0.0
            assert obj.effective_total_sell_price == 0.0

def test_detail_view_auto_ensures_and_renders(auth_client_manager, app):
    """Kiểm tra khi truy cập route detail(lot_id), hệ thống tự động điền 8 mục và hiển thị đầy đủ trên HTML."""
    with app.app_context():
        lot = Lot(month=9, year=2026, lot_label='Lô Test Route Detail')
        db.session.add(lot)
        db.session.flush()

        ri = RevenueItem(
            lot_id=lot.id,
            vehicle_plate_vn='60B-123.45',
            weight_class='Xe 8T',
            service_description='Cước vận chuyển tuyến Bắc Nam',
            buy_price=20000000.0,
            sell_price=25000000.0,
            total_buy_price_excel=20000000.0,
            total_sell_price_excel=25000000.0
        )
        db.session.add(ri)
        db.session.commit()
        lot_id = lot.id

    res = auth_client_manager.get(f'/lots/{lot_id}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')

    # Đảm bảo có đầy đủ 8 tên mục trên giao diện
    assert 'Cước vận chuyển' in html
    assert 'Chi phí dịch vụ bốc xếp' in html
    assert 'Dịch vụ Quatest' in html
    assert 'Phí cửa khẩu' in html
    assert 'Dịch vụ tờ khai Hải quan' in html
    assert 'Phí Cơ sở hạ tầng' in html
    assert 'Vé xe' in html
    assert 'Chi phí lưu kho HTT' in html