"""
Service xử lý logic chốt kế toán hàng tháng.

Luồng nghiệp vụ:
1. Phân loại giao dịch: Có HĐ / Không HĐ (tự động + sửa tay)
2. Set deadline hoàn ứng = ngày cuối tháng
3. NV hoàn chứng từ → mark settled
4. Khoản Không HĐ → yêu cầu loại trừ → duyệt/từ chối
5. Tổng hợp chốt kỳ → tính số tiền gửi về KT
"""
import calendar
from datetime import date, datetime
from app.extensions import db
from app.models import CashAdvanceTransaction, MonthlySettlement


def _get_expense_amount(t):
    """Lấy số tiền chi phí thực tế của giao dịch (giá trị tuyệt đối)."""
    amt = abs(t.tuan_chi or 0)
    if amt == 0:
        amt = abs(t.partner_amount or 0)
    if amt == 0:
        amt = abs(t.luong_chi or 0)
    return amt


def _last_day_of_month(year, month):
    """Trả về ngày cuối cùng của tháng."""
    return date(year, month, calendar.monthrange(year, month)[1])


def auto_classify_transactions(month, year):
    """
    Tự động phân loại invoice_category cho tất cả giao dịch trong tháng.
    Logic: Nếu có partner_invoice hoặc bill_link → has_invoice, ngược lại → no_invoice.
    Chỉ phân loại các giao dịch chi (có tuan_chi hoặc partner_amount).
    Trả về số lượng đã phân loại.
    """
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).all()

    count = 0
    for t in transactions:
        # Chỉ phân loại giao dịch chi tiền
        if not (_get_expense_amount(t) > 0):
            continue

        # Nếu đã phân loại rồi (không phải unknown) thì bỏ qua
        if t.invoice_category and t.invoice_category != 'unknown':
            continue

        has_doc = bool(
            (t.partner_invoice and t.partner_invoice.strip()) or
            (t.bill_link and t.bill_link.strip())
        )
        t.invoice_category = 'has_invoice' if has_doc else 'no_invoice'
        count += 1

    db.session.commit()
    return count


def set_refund_deadlines(month, year):
    """
    Set refund_deadline = ngày cuối tháng cho tất cả giao dịch chi trong tháng
    mà chưa có deadline.
    """
    deadline = _last_day_of_month(year, month)
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).filter(
        CashAdvanceTransaction.refund_deadline.is_(None)
    ).all()

    count = 0
    for t in transactions:
        if _get_expense_amount(t) > 0:
            t.refund_deadline = deadline
            count += 1

    db.session.commit()
    return count


def classify_single_transaction(trans_id, category):
    """Phân loại thủ công 1 giao dịch theo xác nhận trực tiếp của nhân sự. category: 'has_invoice' hoặc 'no_invoice'."""
    if category not in ('has_invoice', 'no_invoice', 'unknown'):
        return None, "Loại hóa đơn không hợp lệ"

    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"

    t.invoice_category = category
    if category == 'has_invoice':
        t.refund_deadline = _last_day_of_month(t.year, t.month)
    elif category == 'no_invoice':
        t.refund_deadline = None
    db.session.commit()
    return t, None


def mark_settled(trans_id):
    """Đánh dấu giao dịch đã hoàn ứng chứng từ."""
    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"

    t.refund_status = 'settled'
    t.refund_settled_at = datetime.utcnow()
    t.advance_refund = 'Đã hoàn ứng'
    db.session.commit()
    return t, None


def mark_submitted(trans_id):
    """Đánh dấu NV đã nộp chứng từ (chờ xác nhận)."""
    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"

    t.refund_status = 'submitted'
    t.advance_refund = 'Đã nộp CT'
    db.session.commit()
    return t, None


def request_exclusion(trans_id, note=''):
    """KT tạo yêu cầu loại trừ khoản Không HĐ."""
    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"

    t.exclusion_status = 'pending_approval'
    t.exclusion_requested_at = datetime.utcnow()
    t.exclusion_note = note
    t.refund_status = 'pending'  # Giữ pending cho đến khi duyệt
    db.session.commit()
    return t, None


def approve_exclusion(trans_id, approved_by_user_id):
    """Sếp duyệt loại trừ khoản Không HĐ."""
    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"
    if t.exclusion_status != 'pending_approval':
        return None, "Giao dịch không ở trạng thái chờ duyệt"

    t.exclusion_status = 'approved'
    t.exclusion_approved_at = datetime.utcnow()
    t.exclusion_approved_by = approved_by_user_id
    t.refund_status = 'excluded'
    t.advance_refund = 'Loại trừ (đã duyệt)'
    db.session.commit()
    return t, None


def reject_exclusion(trans_id):
    """Sếp từ chối loại trừ — khoản này phải tìm HĐ bổ sung."""
    t = db.session.get(CashAdvanceTransaction, trans_id)
    if not t or t.is_deleted:
        return None, "Không tìm thấy giao dịch"
    if t.exclusion_status != 'pending_approval':
        return None, "Giao dịch không ở trạng thái chờ duyệt"

    t.exclusion_status = 'rejected'
    t.refund_status = 'pending'
    t.advance_refund = 'Loại trừ bị từ chối'
    db.session.commit()
    return t, None


def check_overdue_transactions(month, year):
    """
    Rà soát giao dịch quá hạn hoàn ứng. Gọi hàng ngày sau ngày cuối tháng.
    Trả về danh sách giao dịch quá hạn.
    """
    today = date.today()
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).filter(
        CashAdvanceTransaction.refund_status.in_(['pending', 'submitted']),
        CashAdvanceTransaction.refund_deadline.isnot(None),
        CashAdvanceTransaction.refund_deadline < today
    ).all()

    overdue = []
    for t in transactions:
        if _get_expense_amount(t) > 0:
            t.refund_status = 'overdue'
            overdue.append(t)

    if overdue:
        db.session.commit()
    return overdue


def calculate_settlement_summary(month, year):
    """
    Tính toán bảng tổng hợp chốt kỳ cho tháng/năm.
    Trả về dict với tất cả metrics và upsert vào MonthlySettlement.
    """
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).all()

    # Chỉ lấy giao dịch chi tiền
    expense_txns = [t for t in transactions if _get_expense_amount(t) > 0]

    total_expenses = sum(_get_expense_amount(t) for t in expense_txns)
    with_invoice = [t for t in expense_txns if t.invoice_category == 'has_invoice']
    no_invoice = [t for t in expense_txns if t.invoice_category == 'no_invoice']
    settled = [t for t in expense_txns if t.refund_status == 'settled']
    excluded = [t for t in expense_txns if t.refund_status == 'excluded']
    overdue = [t for t in expense_txns if t.refund_status == 'overdue']
    pending = [t for t in expense_txns if t.refund_status in ('pending', 'submitted')]

    total_with_invoice = sum(_get_expense_amount(t) for t in with_invoice)
    total_no_invoice = sum(_get_expense_amount(t) for t in no_invoice)
    total_settled = sum(_get_expense_amount(t) for t in settled)
    total_excluded = sum(_get_expense_amount(t) for t in excluded)
    total_overdue = sum(_get_expense_amount(t) for t in overdue)

    # Số tiền phải gửi về KT = Tổng chi - Loại trừ đã duyệt
    total_to_remit = total_expenses - total_excluded

    summary = {
        'total_expenses': total_expenses,
        'total_with_invoice': total_with_invoice,
        'total_no_invoice': total_no_invoice,
        'total_settled': total_settled,
        'total_excluded': total_excluded,
        'total_overdue': total_overdue,
        'total_to_remit': total_to_remit,
        'count_total': len(expense_txns),
        'count_with_invoice': len(with_invoice),
        'count_no_invoice': len(no_invoice),
        'count_settled': len(settled),
        'count_excluded': len(excluded),
        'count_overdue': len(overdue),
        'count_pending': len(pending),
    }

    # Upsert vào MonthlySettlement
    settlement = MonthlySettlement.query.filter_by(month=month, year=year).first()
    if not settlement:
        settlement = MonthlySettlement(month=month, year=year)
        db.session.add(settlement)

    for key, val in summary.items():
        setattr(settlement, key, val)

    settlement.updated_at = datetime.utcnow()
    db.session.commit()

    summary['settlement'] = settlement.to_dict()
    return summary


def close_month(month, year, closed_by_user_id):
    """Chốt sổ tháng — snapshot cuối cùng và khóa."""
    # Tính lại summary trước khi chốt
    summary = calculate_settlement_summary(month, year)

    settlement = MonthlySettlement.query.filter_by(month=month, year=year).first()
    if not settlement:
        return None, "Không tìm thấy bảng chốt kỳ"

    settlement.status = 'closed'
    settlement.closed_at = datetime.utcnow()
    settlement.closed_by = closed_by_user_id
    db.session.commit()

    return settlement, None


def reopen_month(month, year):
    """Mở lại tháng đã chốt (chỉ Admin)."""
    settlement = MonthlySettlement.query.filter_by(month=month, year=year).first()
    if not settlement:
        return None, "Không tìm thấy bảng chốt kỳ"

    settlement.status = 'open'
    settlement.closed_at = None
    settlement.closed_by = None
    db.session.commit()

    return settlement, None


def get_unsettled_transactions(month, year):
    """Lấy danh sách giao dịch chưa hoàn ứng (để nhắc nhở)."""
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).filter(
        CashAdvanceTransaction.refund_status.in_(['pending', 'submitted', 'overdue'])
    ).all()

    return [t for t in transactions if _get_expense_amount(t) > 0]


def get_pending_exclusions():
    """Lấy danh sách giao dịch đang chờ duyệt loại trừ (hiển thị cho Manager)."""
    return CashAdvanceTransaction.query.filter_by(
        is_deleted=False, exclusion_status='pending_approval'
    ).all()


def preview_lot_reconciliation(month, year):
    """
    Tự động đối chiếu chi phí Lô hàng (OperatingCost) sang Bảng dòng tiền tạm ứng (CashAdvanceTransaction).
    Tìm các cặp tương đồng về số tiền và nội dung để gợi ý phân loại Có HĐ / Không HĐ,
    giúp nhân viên và kế toán không phải bấm tay nhiều lần.
    """
    from app.models import Lot, OperatingCost

    txs = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).all()

    lots = Lot.query.filter_by(month=month, year=year, is_deleted=False).all()
    lot_ids = [l.id for l in lots]
    costs = OperatingCost.query.filter(
        OperatingCost.lot_id.in_(lot_ids),
        OperatingCost.is_deleted == False
    ).all() if lot_ids else []

    matches = []
    for t in txs:
        amt = _get_expense_amount(t)
        if amt <= 0:
            continue

        c_lower = (t.content or '').lower()
        best_cost = None
        best_score = 0

        for c in costs:
            score = 0
            if abs(c.total_amount - amt) < 1.0:
                score += 50
            desc = (c.description or '').lower()
            words = [w for w in desc.split() if len(w) > 3]
            if any(w in c_lower for w in words):
                score += 30
            if c.vehicle_plate and c.vehicle_plate.lower() in c_lower:
                score += 40
            if c.lot and c.lot.lot_label and c.lot.lot_label.lower() in c_lower:
                score += 30

            if score > best_score and score >= 50:
                best_score = score
                best_cost = c

        if best_cost:
            inv_type_raw = (best_cost.invoice_type or '').lower()
            if 'không' in inv_type_raw:
                proposed_cat = 'no_invoice'
            elif 'hóa đơn' in inv_type_raw or 'gtgt' in inv_type_raw or 'vé' in inv_type_raw:
                proposed_cat = 'has_invoice'
            else:
                proposed_cat = 'no_invoice' if 'không' in (best_cost.note or '').lower() else 'has_invoice'

            matches.append({
                'trans_id': t.id,
                'trans_date': t.trans_date or '',
                'trans_content': t.content or '',
                'trans_amount': amt,
                'current_category': t.invoice_category or 'unknown',
                'cost_id': best_cost.id,
                'cost_desc': best_cost.description or '',
                'cost_amount': best_cost.total_amount,
                'cost_invoice_type': best_cost.invoice_type or 'Chưa rõ',
                'lot_id': best_cost.lot_id,
                'lot_label': best_cost.lot.lot_label if best_cost.lot else f"Lô #{best_cost.lot_id}",
                'lot_customer': best_cost.lot.display_customer_name if best_cost.lot else '',
                'proposed_category': proposed_cat,
                'score': best_score,
            })

    return matches


def apply_lot_reconciliation(month, year, selected_trans_ids=None):
    """
    Áp dụng kết quả đối chiếu chi phí Lô hàng sang các giao dịch dòng tiền tạm ứng.
    Tự động cập nhật invoice_category và refund_deadline.
    """
    matches = preview_lot_reconciliation(month, year)
    applied_count = 0

    target_ids = set(selected_trans_ids) if selected_trans_ids else None

    for m in matches:
        t_id = m['trans_id']
        if target_ids and t_id not in target_ids:
            continue

        t = db.session.get(CashAdvanceTransaction, t_id)
        if not t or t.is_deleted:
            continue

        prop_cat = m['proposed_category']
        t.invoice_category = prop_cat

        if prop_cat == 'has_invoice':
            t.refund_deadline = _last_day_of_month(t.year, t.month)
        elif prop_cat == 'no_invoice':
            t.refund_deadline = None
            if not t.exclusion_note:
                t.exclusion_note = f"Chi phí Lô {m['lot_label']} ({m['cost_desc']}) không có HĐ"

        applied_count += 1

    if applied_count > 0:
        db.session.commit()

    return applied_count


def export_no_invoice_excel(month, year):
    """
    Xuất bảng kê các khoản chi phí KHÔNG CÓ HÓA ĐƠN GTGT ra file Excel chuyên nghiệp
    để kế toán đính kèm email xin Sếp Tổng phê duyệt loại trừ khỏi hoàn ứng.
    """
    import os
    import tempfile
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # Query all no-invoice or pending/approved exclusion transactions in month
    transactions = CashAdvanceTransaction.query.filter_by(
        month=month, year=year, is_deleted=False
    ).filter(
        (CashAdvanceTransaction.invoice_category == 'no_invoice') |
        (CashAdvanceTransaction.exclusion_status.in_(['pending_approval', 'approved']))
    ).order_by(CashAdvanceTransaction.row_index).all()

    # Filter only genuine expense transactions
    tx_list = [t for t in transactions if _get_expense_amount(t) > 0]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Khong_HD_T{month:02d}_{year}"

    # Setup styles
    font_company = Font(name="Arial", size=9, bold=True, color="1E3A8A")
    font_title = Font(name="Arial", size=13, bold=True, color="0F172A")
    font_sub = Font(name="Arial", size=9, italic=True, color="475569")
    font_header = Font(name="Arial", size=9, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=9)
    font_data_bold = Font(name="Arial", size=9, bold=True)
    font_total = Font(name="Arial", size=10, bold=True, color="991B1B")

    fill_header = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_total = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    fill_even = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color="CBD5E1"),
        right=Side(style='thin', color="CBD5E1"),
        top=Side(style='thin', color="CBD5E1"),
        bottom=Side(style='thin', color="CBD5E1")
    )
    total_border = Border(
        top=Side(style='thin', color="0F172A"),
        bottom=Side(style='double', color="0F172A"),
        left=Side(style='thin', color="CBD5E1"),
        right=Side(style='thin', color="CBD5E1")
    )

    # Header info
    ws["A1"] = "CÔNG TY TNHH GIC LOGISTICS"
    ws["A1"].font = font_company
    ws["A2"] = "BỘ PHẬN TÀI CHÍNH - KẾ TOÁN"
    ws["A2"].font = font_company

    ws.merge_cells("A4:H4")
    ws["A4"] = f"BẢNG KÊ CÁC KHOẢN CHI PHÍ KHÔNG CÓ HÓA ĐƠN GTGT - THÁNG {month:02d}/{year}"
    ws["A4"].font = font_title
    ws["A4"].alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("A5:H5")
    ws["A5"] = "(Kính trình Ban Giám Đốc / Sếp Tổng xem xét phê duyệt loại trừ hoàn ứng)"
    ws["A5"].font = font_sub
    ws["A5"].alignment = Alignment(horizontal="center", vertical="center")

    # Table columns
    headers = [
        ("STT", 6, "center"),
        ("Ngày chi", 13, "center"),
        ("Nội dung chi tiết", 38, "left"),
        ("Số tiền (VNĐ)", 17, "right"),
        ("Đối tác / Người nhận", 22, "left"),
        ("Lý do không HĐ / Ghi chú", 32, "left"),
        ("Trạng thái phê duyệt", 18, "center"),
        ("Ý kiến Sếp Tổng phê duyệt", 25, "center")
    ]

    header_row = 7
    for col_idx, (h_title, col_width, align) in enumerate(headers, start=1):
        col_letter = get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = col_width
        cell = ws.cell(row=header_row, column=col_idx, value=h_title)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    current_row = header_row + 1
    total_amount = 0.0

    for idx, t in enumerate(tx_list, start=1):
        amt = _get_expense_amount(t)
        total_amount += amt

        status_str = "Đã duyệt loại trừ" if t.exclusion_status == 'approved' else "Chờ Sếp duyệt"

        ws.cell(row=current_row, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=current_row, column=2, value=t.trans_date or "").alignment = Alignment(horizontal="center")
        ws.cell(row=current_row, column=3, value=t.content or "").alignment = Alignment(horizontal="left", wrap_text=True)
        
        amt_cell = ws.cell(row=current_row, column=4, value=amt)
        amt_cell.number_format = '#,##0'
        amt_cell.alignment = Alignment(horizontal="right")
        amt_cell.font = font_data_bold

        ws.cell(row=current_row, column=5, value=t.partner_invoice or "").alignment = Alignment(horizontal="left")
        ws.cell(row=current_row, column=6, value=t.exclusion_note or "Chi tiền mặt trực tiếp không có hóa đơn").alignment = Alignment(horizontal="left", wrap_text=True)
        ws.cell(row=current_row, column=7, value=status_str).alignment = Alignment(horizontal="center")
        ws.cell(row=current_row, column=8, value="Đồng ý duyệt" if t.exclusion_status == 'approved' else "").alignment = Alignment(horizontal="center")

        fill_to_apply = fill_even if idx % 2 == 0 else PatternFill(fill_type=None)
        for c in range(1, 9):
            c_cell = ws.cell(row=current_row, column=c)
            if fill_to_apply.fill_type:
                c_cell.fill = fill_to_apply
            c_cell.border = thin_border
            if c != 4:
                c_cell.font = font_data

        current_row += 1

    # Total Row
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
    total_label = ws.cell(row=current_row, column=1, value=f"TỔNG CỘNG ({len(tx_list)} khoản đề xuất loại trừ):")
    total_label.font = font_total
    total_label.alignment = Alignment(horizontal="right", vertical="center")

    total_val = ws.cell(row=current_row, column=4, value=total_amount)
    total_val.font = font_total
    total_val.number_format = '#,##0 "₫"'
    total_val.alignment = Alignment(horizontal="right", vertical="center")

    for c in range(1, 9):
        cell = ws.cell(row=current_row, column=c)
        cell.fill = fill_total
        cell.border = total_border

    current_row += 2

    # Signatures
    ws.cell(row=current_row, column=6, value=f"Hà Nội, ngày ... tháng {month:02d} năm {year}").font = font_sub
    current_row += 1

    sig_row = current_row
    ws.cell(row=sig_row, column=2, value="NGƯỜI LẬP BIỂU").font = font_company
    ws.cell(row=sig_row, column=2).alignment = Alignment(horizontal="center")
    ws.cell(row=sig_row + 1, column=2, value="(Kế toán thanh toán)").font = font_sub
    ws.cell(row=sig_row + 1, column=2).alignment = Alignment(horizontal="center")

    ws.cell(row=sig_row, column=5, value="PHỤ TRÁCH DÒNG TIỀN").font = font_company
    ws.cell(row=sig_row, column=5).alignment = Alignment(horizontal="center")
    ws.cell(row=sig_row + 1, column=5, value="(Ký, ghi rõ họ tên)").font = font_sub
    ws.cell(row=sig_row + 1, column=5).alignment = Alignment(horizontal="center")

    ws.cell(row=sig_row, column=8, value="TỔNG GIÁM ĐỐC PHÊ DUYỆT").font = font_company
    ws.cell(row=sig_row, column=8).alignment = Alignment(horizontal="center")
    ws.cell(row=sig_row + 1, column=8, value="(Ký và phê duyệt)").font = font_sub
    ws.cell(row=sig_row + 1, column=8).alignment = Alignment(horizontal="center")

    # Save to temp file
    filename = f"Bang_ke_chi_phi_khong_HD_T{month:02d}_{year}.xlsx"
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, filename)
    wb.save(file_path)

    return file_path, filename, len(tx_list), total_amount
