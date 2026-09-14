"""
CLI Script: Safe Historical CPVH Reconciliation
Mục đích: Đối soát an toàn các nhóm chi phí vận hành (source_type='cpvh') trong cơ sở dữ liệu.
Hỗ trợ chế độ dry-run mặc định và cờ --apply để ghi DB an toàn trong transaction.

Cách dùng:
  python -X utf8 scripts/reconcile_cpvh.py                       # Dry-run toàn bộ các kỳ
  python -X utf8 scripts/reconcile_cpvh.py --month 8 --year 2026 # Dry-run tháng 8/2026
  python -X utf8 scripts/reconcile_cpvh.py --apply              # Áp dụng đối soát vào DB
"""

import sys
import os
import argparse
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import Lot, OperatingCost, CashAdvanceBillMedia
from app.services.cpvh_matcher import CPVHMatcher
from app.services.calculator import CalculatorService
from app.security import log_audit


def run_reconciliation(target_month=None, target_year=None, apply=False):
    app = create_app()
    with app.app_context():
        # Query active unresolved CPVH groups
        q = Lot.unresolved_cpvh_query()
        if target_month:
            q = q.filter_by(month=target_month)
        if target_year:
            q = q.filter_by(year=target_year)

        unresolved_lots = q.order_by(Lot.year.asc(), Lot.month.asc(), Lot.id.asc()).all()

        print("=" * 115)
        mode_str = "[GHI DỮ LIỆU --APPLY]" if apply else "[XEM THỬ DRY-RUN]"
        print(f"BÁO CÁO ĐỐI SOÁT CHI PHÍ VẬN HÀNH (CPVH) - CHẾ ĐỘ: {mode_str}")
        print("=" * 115)
        print(f"{'Kỳ':<10} | {'Nhóm CPVH':<16} | {'Khách hàng':<18} | {'Số TKHQ':<16} | {'Khoản':<5} | {'Số tiền (VNĐ)':<14} | {'Kết quả':<10} | {'Lô đích':<12}")
        print("-" * 115)

        matched_count = 0
        ambiguous_count = 0
        conflict_count = 0
        unresolved_count = 0
        total_moved_costs = 0
        total_matched_amount = 0.0

        for u in unresolved_lots:
            period_str = f"T{u.month:02d}/{u.year}" if u.month and u.year else "N/A"
            sales_lots = Lot.sales_lots_query().filter_by(month=u.month, year=u.year).all()

            # Inspect costs under this unresolved lot
            costs = [c for c in u.operating_costs if not c.is_deleted]
            total_amt = sum(c.total_amount or 0.0 for c in costs)
            item_count = len(costs)

            # Match group
            match_res = CPVHMatcher.match_group(
                source_customer=u.company,
                source_decl=u.customs_declaration,
                sales_lots=sales_lots,
                period_month=u.month,
                period_year=u.year
            )

            status_upper = match_res.status.upper()
            target_label = match_res.matched_lot_label or "-"

            cust_display = (u.company or "-")[:18]
            decl_display = (u.customs_declaration or "-")[:16]
            print(f"{period_str:<10} | {u.lot_label:<16} | {cust_display:<18} | {decl_display:<16} | {item_count:<5} | {total_amt:>14,.0f} | {status_upper:<10} | {target_label:<12}")

            if match_res.status == 'matched':
                matched_count += 1
                total_matched_amount += total_amt

                if apply:
                    # Move operating costs
                    c_cnt = OperatingCost.query.filter_by(lot_id=u.id).update(
                        {OperatingCost.lot_id: match_res.matched_lot_id}, synchronize_session=False
                    )
                    # Move bill media
                    CashAdvanceBillMedia.query.filter_by(lot_id=u.id).update(
                        {CashAdvanceBillMedia.lot_id: match_res.matched_lot_id}, synchronize_session=False
                    )
                    # Soft delete placeholder
                    now_utc = datetime.now(timezone.utc)
                    u.is_deleted = True
                    u.deleted_at = now_utc

                    total_moved_costs += c_cnt
                    log_audit('cli_reconcile_cpvh', 'lot', match_res.matched_lot_id,
                              f"[CLI Reconcile] Đã gộp nhóm {u.lot_label} (ID: {u.id}) vào {match_res.matched_lot_label} (ID: {match_res.matched_lot_id}) - {c_cnt} CPVH.",
                              before_state={'unresolved_lot_id': u.id, 'target_lot_id': match_res.matched_lot_id})
            elif match_res.status == 'ambiguous':
                ambiguous_count += 1
            elif match_res.status == 'conflict':
                conflict_count += 1
            else:
                unresolved_count += 1

        print("-" * 115)
        print(f"Tổng số nhóm kiểm tra: {len(unresolved_lots)}")
        print(f"  - MATCHED (khớp chắc chắn):   {matched_count} nhóm ({total_matched_amount:,.0f} VNĐ)")
        print(f"  - AMBIGUOUS (nhiều ứng viên): {ambiguous_count} nhóm")
        print(f"  - CONFLICT (mâu thuẫn):       {conflict_count} nhóm")
        print(f"  - UNRESOLVED (chưa rõ):       {unresolved_count} nhóm")

        if apply:
            try:
                db.session.commit()
                CalculatorService.invalidate_cache()
                print("=" * 115)
                print(f"✅ GHI DỮ LIỆU THÀNH CÔNG: Đã ghép {matched_count} nhóm ({total_moved_costs} khoản CPVH) vào các Sales Lot tương ứng.")
                print("=" * 115)
            except Exception as e:
                db.session.rollback()
                print("=" * 115)
                print(f"❌ LỖI KHI GHI DATABASE: {e}. Đã rollback toàn bộ transaction.")
                print("=" * 115)
                sys.exit(1)
        else:
            print("=" * 115)
            print("ℹ️ Chế độ Dry-run: Cơ sở dữ liệu KHÔNG bị thay đổi. Chạy lại với cờ `--apply` để áp dụng ghi DB.")
            print("=" * 115)


def main():
    parser = argparse.ArgumentParser(description="CLI Safe Historical CPVH Reconciliation")
    parser.add_argument('--month', type=int, default=None, help="Tháng cần đối soát (1-12)")
    parser.add_argument('--year', type=int, default=None, help="Năm cần đối soát (VD: 2026)")
    parser.add_argument('--apply', action='store_true', default=False, help="Áp dụng thay đổi vào cơ sở dữ liệu")
    args = parser.parse_args()

    run_reconciliation(target_month=args.month, target_year=args.year, apply=args.apply)


if __name__ == '__main__':
    main()

