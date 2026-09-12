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
