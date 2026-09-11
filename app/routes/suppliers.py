from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Supplier, OperatingCost
from app.routes.auth import manager_required

suppliers_bp = Blueprint('suppliers', __name__)

@suppliers_bp.route('/')
@login_required
def index():
    query = request.args.get('q', '').strip()
    suppliers_query = Supplier.query
    
    if query:
        suppliers_query = suppliers_query.filter(
            (Supplier.tax_code.ilike(f"%{query}%")) |
            (Supplier.supplier_code.ilike(f"%{query}%")) |
            (Supplier.name.ilike(f"%{query}%")) |
            (Supplier.address.ilike(f"%{query}%"))
        )
        
    suppliers = suppliers_query.order_by(Supplier.id.asc()).all()
    
    total_count = Supplier.query.count()
    has_tax_count = Supplier.query.filter(Supplier.tax_code.isnot(None), Supplier.tax_code != '').count()
    has_code_count = Supplier.query.filter(Supplier.supplier_code.isnot(None), Supplier.supplier_code != '').count()
    
    return render_template(
        'suppliers.html',
        suppliers=suppliers,
        query=query,
        total_count=total_count,
        has_tax_count=has_tax_count,
        has_code_count=has_code_count
    )

@suppliers_bp.route('/new', methods=['POST'])
@login_required
@manager_required
def new_supplier():
    tax_code = request.form.get('tax_code', '').strip()
    supplier_code = request.form.get('supplier_code', '').strip()
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    
    if not name:
        flash('Vui lòng nhập Tên nhà cung cấp.', 'danger')
        return redirect(url_for('suppliers.index'))
        
    # Check if existing by tax code
    if tax_code:
        existing = Supplier.query.filter_by(tax_code=tax_code).first()
        if existing:
            flash(f'Mã số thuế/CCCD "{tax_code}" đã tồn tại cho NCC "{existing.name}".', 'warning')
            return redirect(url_for('suppliers.index'))
            
    supplier = Supplier(
        tax_code=tax_code,
        supplier_code=supplier_code,
        name=name,
        address=address
    )
    db.session.add(supplier)
    db.session.commit()
    flash(f'Đã thêm mới nhà cung cấp "{name}" thành công!', 'success')
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/<int:supplier_id>/edit', methods=['POST'])
@login_required
@manager_required
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    tax_code = request.form.get('tax_code', '').strip()
    supplier_code = request.form.get('supplier_code', '').strip()
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    
    if not name:
        flash('Tên nhà cung cấp không được để trống.', 'danger')
        return redirect(url_for('suppliers.index'))
        
    supplier.tax_code = tax_code
    supplier.supplier_code = supplier_code
    supplier.name = name
    supplier.address = address
    db.session.commit()
    flash(f'Đã cập nhật thông tin nhà cung cấp "{name}"!', 'success')
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/<int:supplier_id>/delete', methods=['POST'])
@login_required
@manager_required
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    
    # Check if used in operating costs
    used = OperatingCost.query.filter(
        (OperatingCost.supplier_name == supplier.name) |
        (OperatingCost.supplier_tax_code == supplier.tax_code)
    ).first()
    
    if used:
        flash(f'Không thể xóa nhà cung cấp "{supplier.name}" vì đang có khoản chi phí vận hành gắn liền.', 'warning')
        return redirect(url_for('suppliers.index'))
        
    db.session.delete(supplier)
    db.session.commit()
    flash(f'Đã xóa nhà cung cấp "{supplier.name}" khỏi danh bạ!', 'success')
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])
        
    suppliers = Supplier.query.filter(
        (Supplier.tax_code.ilike(f"%{q}%")) |
        (Supplier.name.ilike(f"%{q}%")) |
        (Supplier.supplier_code.ilike(f"%{q}%"))
    ).limit(15).all()
    
    return jsonify([s.to_dict() for s in suppliers])

