"""
Các hằng số và danh mục định nghĩa chuẩn cho hệ thống GIC Logistics
"""

# Danh mục 16 hạng mục chi phí vận hành tiêu chuẩn theo quy trình biên giới / hải quan thực tế
STANDARD_OPERATING_COST_ITEMS = [
    # 1. Phí cửa khẩu (7 mục)
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Mua phí xe Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Biên lai'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Biên phòng xe Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Kiểm dịch y tế Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'HĐ bán hàng'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Bảo hiểm xe Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'HĐ GTGT'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Vé cổng xe Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Vé xe'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Ngủ đêm',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí cửa khẩu',
        'description': 'Tem xe Trung Quốc',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },

    # 2. Phí thông quan (6 mục)
    {
        'category': 'Tờ khai',
        'cost_type': 'Phí thông quan',
        'description': 'Phí Biên Phòng',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Tờ khai',
        'cost_type': 'Phí thông quan',
        'description': 'Trả giấy phí xe',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Tờ khai',
        'cost_type': 'Phí thông quan',
        'description': 'Tách hồ sơ + GS Cơ động',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Kiểm định',
        'cost_type': 'Phí thông quan',
        'description': 'Kiểm dịch y tế',
        'default_vehicle_count': 1.0,
        'invoice_type': 'HĐ bán hàng'
    },
    {
        'category': 'Tờ khai',
        'cost_type': 'Phí thông quan',
        'description': 'Hải quan thủ tục',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },
    {
        'category': 'Tờ khai',
        'cost_type': 'Phí thông quan',
        'description': 'Biên phòng thả xe',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Không HĐ'
    },

    # 3. Phí bến bãi (3 mục)
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí bến bãi',
        'description': 'Phí Cơ sở hạ tầng',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Biên lai'
    },
    {
        'category': 'Cửa khẩu',
        'cost_type': 'Phí bến bãi',
        'description': 'Phí vé xe vào bãi',
        'default_vehicle_count': 1.0,
        'invoice_type': 'Vé xe'
    },
    {
        'category': 'Bốc xếp',
        'cost_type': 'Phí bến bãi',
        'description': 'Phí cơ giới sang hàng (pallet kéo tay)',
        'default_vehicle_count': 1.0,
        'invoice_type': 'HĐ GTGT'
    },
]
