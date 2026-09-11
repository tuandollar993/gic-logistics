from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Lot, OperatingCost, CostEntryTask, Supplier

costs_bp = Blueprint('costs', __name__)

@costs_bp.route('/entry/<int:lot_id>')
@login_required
def entry(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    # Check permissions
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn chỉ có quyền điền chi phí cho các lô hàng được phân công.', 'danger')
        return redirect(url_for('tasks.my_tasks'))
        
    task = CostEntryTask.query.filter_by(lot_id=lot.id).first()
    suppliers = Supplier.query.order_by(Supplier.name).all()
    
    return render_template(
        'cost_entry.html',
        lot=lot,
        task=task,
        suppliers=suppliers
    )

@costs_bp.route('/api/add/<int:lot_id>', methods=['POST'])
@login_required
def add_cost_item(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        return jsonify({'success': False, 'message': 'Không có quyền thao tác'}), 403
        
    data = request.get_json() or request.form
    
    desc = data.get('description', '').strip()
    if not desc:
        return jsonify({'success': False, 'message': 'Nội dung chi tiết là bắt buộc'}), 400
        
    unit_p = float(data.get('unit_price', 0) or 0)
    veh_cnt = float(data.get('vehicle_count', 1) or 1)
    tot_amt = float(data.get('total_amount', 0) or 0)
    if tot_amt == 0 and unit_p > 0:
        tot_amt = unit_p * veh_cnt
        
    doc_date = None
    doc_date_str = data.get('document_date')
    if doc_date_str:
        try:
            doc_date = datetime.strptime(doc_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
            
    cost = OperatingCost(
        lot_id=lot.id,
        cost_type=data.get('cost_type', '').strip(),
        description=desc,
        vehicle_plate=data.get('vehicle_plate', '').strip(),
        vehicle_count=veh_cnt,
        unit_price=unit_p,
        total_amount=tot_amt,
        invoice_type=data.get('invoice_type', '').strip(),
        invoice_symbol=data.get('invoice_symbol', '').strip(),
        invoice_number=data.get('invoice_number', '').strip(),
        document_date=doc_date,
        supplier_tax_code=data.get('supplier_tax_code', '').strip(),
        supplier_name=data.get('supplier_name', '').strip(),
        note=data.get('note', '').strip(),
        pic=data.get('pic', '').strip() or current_user.full_name,
        cost_amount=float(data.get('cost_amount', 0) or 0),
        vat_amount=float(data.get('vat_amount', 0) or 0),
        payment_method=data.get('payment_method', 'Tiền mặt'),
        filled_by=current_user.id
    )
    db.session.add(cost)
    
    if lot.status == 'assigned':
        lot.status = 'in_progress'
        
    db.session.commit()
    return jsonify({'success': True, 'cost': cost.to_dict(), 'message': 'Đã thêm khoản chi phí thành công'})

@costs_bp.route('/api/delete/<int:cost_id>', methods=['POST', 'DELETE'])
@login_required
def delete_cost_item(cost_id):
    cost = OperatingCost.query.get_or_404(cost_id)
    lot = cost.lot
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        return jsonify({'success': False, 'message': 'Không có quyền thao tác'}), 403
        
    db.session.delete(cost)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Đã xóa khoản chi phí'})

@costs_bp.route('/complete/<int:lot_id>', methods=['POST'])
@login_required
def complete_lot(lot_id):
    """
    STRICT VALIDATION: Ép nhân viên phải điền đủ mọi chi phí và chứng từ theo quy định!
    """
    lot = Lot.query.get_or_404(lot_id)
    if not current_user.is_manager and lot.assigned_to != current_user.id:
        flash('Bạn không có quyền xác nhận lô này.', 'danger')
        return redirect(url_for('tasks.my_tasks'))
        
    costs = lot.operating_costs
    if not costs or len(costs) == 0:
        flash('LỖI: Lô hàng chưa có khoản chi phí vận hành nào! Không thể hoàn thành.', 'danger')
        return redirect(url_for('costs.entry', lot_id=lot.id))
        
    errors = []
    for idx, c in enumerate(costs, start=1):
        missing = []
        if not c.description:
            missing.append('Nội dung chi tiết')
        if not c.unit_price or c.unit_price <= 0:
            missing.append('Đơn giá (> 0)')
        if not c.total_amount or c.total_amount <= 0:
            missing.append('Tổng tiền (> 0)')
        if not c.invoice_type and not c.invoice_number:
            missing.append('Loại hóa đơn/chứng từ hoặc Số HĐ')
        if not c.supplier_name and not c.supplier_tax_code:
            missing.append('Tên nhà cung cấp hoặc MST')
            
        if missing:
            errors.append(f"Dòng {idx} ({c.description or 'Chưa có tên'}): Thiếu {', '.join(missing)}")
            
    if errors:
        error_msg = "Chưa thể hoàn thành vì thiếu thông tin bắt buộc:\n• " + "\n• ".join(errors)
        flash(error_msg, 'danger')
        return redirect(url_for('costs.entry', lot_id=lot.id))
        
    # Mark completed
    lot.status = 'completed'
    lot.completed_at = datetime.utcnow()
    
    task = CostEntryTask.query.filter_by(lot_id=lot.id).first()
    if task:
        task.status = 'completed'
        task.completed_at = datetime.utcnow()
        
    db.session.commit()
    flash(f'Chúc mừng! {lot.lot_label} đã được xác nhận HOÀN THÀNH đầy đủ chi phí vận hành!', 'success')
    
    if current_user.is_manager:
        return redirect(url_for('lots.detail', lot_id=lot.id))
    return redirect(url_for('tasks.my_tasks'))
