import sys
import os
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app import create_app
from app.extensions import db
from app.models import Lot, RevenueItem

def run_surcharge_normalization(commit=True, app=None):
    from flask import has_app_context, current_app
    if app is None:
        if has_app_context():
            app = current_app._get_current_object()
        else:
            app = create_app()

    with app.app_context():
        # Kiểm tra nhanh: nếu không còn item nào có phụ phí chưa tách thì bỏ qua
        needs_work = RevenueItem.query.filter(
            (RevenueItem.infrastructure_fee > 0) |
            (RevenueItem.ticket_fee > 0) |
            (RevenueItem.customs_inspection > 0) |
            (RevenueItem.new_machine_surcharge > 0) |
            (RevenueItem.oversize_surcharge > 0)
        ).first()

        if not needs_work:
            return {
                'parent_updated': 0,
                'split_items': 0,
                'bocxep_updated': 0
            }

        print("🚀 Bắt đầu chuẩn hóa và tách riêng phụ phí theo từng dòng...")
        
        lots = Lot.sales_lots_query().all()
        total_split_items = 0
        total_bocxep_updated = 0
        total_parent_updated = 0

        for lot in lots:
            # 1. Chuẩn hóa dòng bốc xếp độc lập
            bocxep_items = [
                it for it in lot.revenue_items 
                if not it.is_deleted and ('bốc xếp' in (it.service_description or '').lower() or 'boc xep' in (it.service_description or '').lower())
            ]
            for it in bocxep_items:
                # Nếu có loading_fee hoặc sell_price thu khách: giá mua = giá bán = số đó
                target_val = 0.0
                if it.loading_fee and it.loading_fee > 0:
                    target_val = it.loading_fee
                elif it.total_sell_price_excel and it.total_sell_price_excel > 0:
                    target_val = it.total_sell_price_excel
                elif it.sell_price and it.sell_price > 0:
                    target_val = it.sell_price
                
                # Cập nhật Giá mua = Giá bán (LN = 0)
                it.buy_price = target_val
                it.buy_price_loading = 0.0
                it.sell_price = target_val
                it.total_buy_price_excel = target_val
                it.total_sell_price_excel = target_val
                it.loading_fee = 0.0
                total_bocxep_updated += 1

            # 2. Tách phụ phí từ các dòng cước hoặc dòng dịch vụ khác
            items_to_check = [
                it for it in lot.revenue_items 
                if not it.is_deleted and 'bốc xếp' not in (it.service_description or '').lower() and 'boc xep' not in (it.service_description or '').lower()
            ]

            for it in items_to_check:
                surcharges_to_split = []

                if it.infrastructure_fee and it.infrastructure_fee > 0:
                    surcharges_to_split.append(('Phí Cơ sở hạ tầng', it.infrastructure_fee))
                    it.infrastructure_fee = 0.0

                if it.ticket_fee and it.ticket_fee > 0:
                    surcharges_to_split.append(('Vé xe', it.ticket_fee))
                    it.ticket_fee = 0.0

                if it.loading_fee and it.loading_fee > 0:
                    surcharges_to_split.append(('Chi phí dịch vụ bốc xếp', it.loading_fee))
                    it.loading_fee = 0.0

                if it.customs_inspection and it.customs_inspection > 0:
                    surcharges_to_split.append(('Hải quan giám sát', it.customs_inspection))
                    it.customs_inspection = 0.0

                if it.new_machine_surcharge and it.new_machine_surcharge > 0:
                    surcharges_to_split.append(('Phụ thu máy mới', it.new_machine_surcharge))
                    it.new_machine_surcharge = 0.0

                if it.oversize_surcharge and it.oversize_surcharge > 0:
                    surcharges_to_split.append(('Phụ thu hàng quá khổ', it.oversize_surcharge))
                    it.oversize_surcharge = 0.0

                if it.overtime_fee and it.overtime_fee > 0:
                    surcharges_to_split.append(('Phí lưu ca', it.overtime_fee))
                    it.overtime_fee = 0.0

                if it.storage_fee and it.storage_fee > 0:
                    surcharges_to_split.append(('Lưu kho', it.storage_fee))
                    it.storage_fee = 0.0

                tt_fee = (it.tan_thanh_fee or 0.0) + (it.thuan_thanh_fee or 0.0)
                if tt_fee > 0:
                    surcharges_to_split.append(('Phụ phí bến bãi Tân Thanh / Thuận Thành', tt_fee))
                    it.tan_thanh_fee = 0.0
                    it.thuan_thanh_fee = 0.0

                pen_fee = (it.return_dossier_fee or 0.0) + (it.penalty_fee or 0.0) + (it.penalty_dossier_fee or 0.0) + (it.penalty_payment or 0.0)
                if pen_fee > 0:
                    surcharges_to_split.append(('Phí hồ sơ xử phạt', pen_fee))
                    it.return_dossier_fee = 0.0
                    it.penalty_fee = 0.0
                    it.penalty_dossier_fee = 0.0
                    it.penalty_payment = 0.0

                if surcharges_to_split:
                    total_sc = sum(amt for _, amt in surcharges_to_split)
                    # Cập nhật dòng cha về giá cước thuần
                    if it.sell_price and it.sell_price > 0:
                        it.total_sell_price_excel = it.sell_price
                    else:
                        it.total_sell_price_excel = max(0.0, (it.total_sell_price_excel or 0.0) - total_sc)

                    total_parent_updated += 1

                    # Tạo từng dòng phụ phí độc lập
                    for desc, amt in surcharges_to_split:
                        new_item = RevenueItem(
                            lot_id=lot.id,
                            supplier=it.supplier,
                            vehicle_plate_cn=it.vehicle_plate_cn,
                            vehicle_plate_vn=it.vehicle_plate_vn,
                            weight_class=it.weight_class,
                            service_description=desc,
                            quantity=1.0,
                            buy_price=amt,
                            sell_price=amt,
                            total_buy_price_excel=amt,
                            total_sell_price_excel=amt,
                            revenue_month=it.revenue_month,
                            revenue_year=it.revenue_year,
                            revenue_invoice_date=it.revenue_invoice_date,
                            revenue_invoice_number=it.revenue_invoice_number
                        )
                        db.session.add(new_item)
                        total_split_items += 1

        print(f"📊 Kết quả:")
        print(f"   • Số dòng cha được tách phụ phí: {total_parent_updated}")
        print(f"   • Số dòng phụ phí độc lập mới được tạo (Giá mua = Giá bán): {total_split_items}")
        print(f"   • Số dòng bốc xếp được chuẩn hóa (Giá mua = Giá bán): {total_bocxep_updated}")

        if commit:
            db.session.commit()
            print("✅ Đã commit toàn bộ thay đổi vào cơ sở dữ liệu!")
        else:
            db.session.rollback()
            print("ℹ️ Dry-run: Đã rollback, không thay đổi DB.")

        return {
            'parent_updated': total_parent_updated,
            'split_items': total_split_items,
            'bocxep_updated': total_bocxep_updated
        }

if __name__ == '__main__':
    run_surcharge_normalization(commit=True)
