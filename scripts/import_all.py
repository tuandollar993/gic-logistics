import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app import create_app
from app.extensions import db
from app.services.excel_parser import ExcelParserService

def run_import():
    app = create_app()
    with app.app_context():
        db.create_all()
        
        sales_file = BASE_DIR / 'Báo cáo bán hàng.xlsx'
        cost_file = BASE_DIR / 'BẢNG TỔNG HỢP CHI PHÍ VẬN HÀNH 2026.xlsx'
        
        print("=" * 70)
        print("BẮT ĐẦU IMPORT DỮ LIỆU TỪ 2 FILE EXCEL GIC...")
        print(f"1. File bán hàng: {sales_file}")
        print(f"2. File chi phí:   {cost_file}")
        print("=" * 70)
        
        if not sales_file.exists():
            print(f"❌ Không tìm thấy file: {sales_file}")
            return
            
        if not cost_file.exists():
            print(f"❌ Không tìm thấy file: {cost_file}")
            return
            
        results = ExcelParserService.import_all(str(sales_file), str(cost_file))
        
        print("\n" + "=" * 70)
        print("KẾT QUẢ IMPORT:")
        print("=" * 70)
        print(f"• Số chỉ tiêu Target nhập:        {results['targets']} tháng")
        print(f"• Số nhà cung cấp (NCC):           {results['suppliers']} NCC")
        print(f"• Số lô hàng (Lots):               {results['lots']} lô")
        print(f"• Số mục doanh thu & chuyến:       {results['revenue_items']} mục")
        print(f"• Số mục chi phí vận hành (CPVH):  {results['operating_costs']} mục")
        
        if results['errors']:
            print("\n⚠️ Cảnh báo trong quá trình xử lý:")
            for err in results['errors']:
                print(f"  - {err}")
        else:
            print("\n✅ Toàn bộ dữ liệu lịch sử từ T9/2025 đến T9/2026 đã được import thành công!")

if __name__ == '__main__':
    run_import()
