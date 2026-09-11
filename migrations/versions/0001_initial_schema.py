"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-09-11 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'users' not in existing_tables:
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(length=50), nullable=False),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('full_name', sa.String(length=100), nullable=False),
            sa.Column('role', sa.String(length=20), nullable=False),
            sa.Column('telegram_chat_id', sa.String(length=50), nullable=True),
            sa.Column('email', sa.String(length=100), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username')
        )

    if 'customers' not in existing_tables:
        op.create_table('customers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('code', sa.String(length=50), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )

    if 'suppliers' not in existing_tables:
        op.create_table('suppliers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('tax_code', sa.String(length=50), nullable=True),
            sa.Column('supplier_code', sa.String(length=50), nullable=True),
            sa.Column('name', sa.String(length=300), nullable=False),
            sa.Column('address', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    if 'targets' not in existing_tables:
        op.create_table('targets',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('target_amount', sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('year', 'month', name='uq_target_year_month')
        )

    if 'lots' not in existing_tables:
        op.create_table('lots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('lot_label', sa.String(length=50), nullable=True),
            sa.Column('customer_id', sa.Integer(), nullable=True),
            sa.Column('company', sa.String(length=200), nullable=True),
            sa.Column('customs_declaration', sa.String(length=150), nullable=True),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('start_date', sa.Date(), nullable=True),
            sa.Column('end_date', sa.Date(), nullable=True),
            sa.Column('source_sheet', sa.String(length=50), nullable=True),
            sa.Column('source_type', sa.String(length=20), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('assigned_to', sa.Integer(), nullable=True),
            sa.Column('cost_deadline', sa.Date(), nullable=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
            sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'revenue_items' not in existing_tables:
        op.create_table('revenue_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('lot_id', sa.Integer(), nullable=False),
            sa.Column('supplier', sa.String(length=200), nullable=True),
            sa.Column('vehicle_plate_cn', sa.String(length=50), nullable=True),
            sa.Column('vehicle_plate_vn', sa.String(length=50), nullable=True),
            sa.Column('weight_class', sa.String(length=50), nullable=True),
            sa.Column('service_description', sa.Text(), nullable=True),
            sa.Column('quantity', sa.Float(), nullable=True),
            sa.Column('buy_price', sa.Float(), nullable=True),
            sa.Column('buy_price_loading', sa.Float(), nullable=True),
            sa.Column('sell_price', sa.Float(), nullable=True),
            sa.Column('overtime_count', sa.Float(), nullable=True),
            sa.Column('overtime_fee', sa.Float(), nullable=True),
            sa.Column('customs_inspection', sa.Float(), nullable=True),
            sa.Column('infrastructure_fee', sa.Float(), nullable=True),
            sa.Column('ticket_fee', sa.Float(), nullable=True),
            sa.Column('new_machine_surcharge', sa.Float(), nullable=True),
            sa.Column('oversize_surcharge', sa.Float(), nullable=True),
            sa.Column('loading_fee', sa.Float(), nullable=True),
            sa.Column('penalty_fee', sa.Float(), nullable=True),
            sa.Column('tan_thanh_fee', sa.Float(), nullable=True),
            sa.Column('thuan_thanh_fee', sa.Float(), nullable=True),
            sa.Column('return_dossier_fee', sa.Float(), nullable=True),
            sa.Column('storage_fee', sa.Float(), nullable=True),
            sa.Column('penalty_dossier_fee', sa.Float(), nullable=True),
            sa.Column('penalty_payment', sa.Float(), nullable=True),
            sa.Column('other_surcharge', sa.Float(), nullable=True),
            sa.Column('route', sa.String(length=200), nullable=True),
            sa.Column('inspection_point', sa.Float(), nullable=True),
            sa.Column('inspection_fee', sa.Float(), nullable=True),
            sa.Column('routing_fee', sa.Float(), nullable=True),
            sa.Column('empty_container', sa.Float(), nullable=True),
            sa.Column('total_buy_price_excel', sa.Float(), nullable=True),
            sa.Column('total_sell_price_excel', sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

    if 'operating_costs' not in existing_tables:
        op.create_table('operating_costs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('lot_id', sa.Integer(), nullable=False),
            sa.Column('cost_type', sa.String(length=100), nullable=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('vehicle_plate', sa.String(length=50), nullable=True),
            sa.Column('vehicle_count', sa.Float(), nullable=True),
            sa.Column('unit_price', sa.Float(), nullable=True),
            sa.Column('total_amount', sa.Float(), nullable=True),
            sa.Column('sell_price', sa.Float(), nullable=True),
            sa.Column('invoice_type', sa.String(length=50), nullable=True),
            sa.Column('invoice_symbol', sa.String(length=50), nullable=True),
            sa.Column('invoice_number', sa.String(length=100), nullable=True),
            sa.Column('document_date', sa.Date(), nullable=True),
            sa.Column('supplier_tax_code', sa.String(length=50), nullable=True),
            sa.Column('supplier_name', sa.String(length=200), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('pic', sa.String(length=100), nullable=True),
            sa.Column('cost_amount', sa.Float(), nullable=True),
            sa.Column('vat_amount', sa.Float(), nullable=True),
            sa.Column('payment_method', sa.String(length=50), nullable=True),
            sa.Column('filled_by', sa.Integer(), nullable=True),
            sa.Column('filled_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['filled_by'], ['users.id'], ),
            sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

    if 'cost_entry_tasks' not in existing_tables:
        op.create_table('cost_entry_tasks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('lot_id', sa.Integer(), nullable=False),
            sa.Column('assigned_to', sa.Integer(), nullable=False),
            sa.Column('deadline', sa.Date(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('reminder_count', sa.Integer(), nullable=True),
            sa.Column('last_reminded_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
            sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

    if 'reminder_log' not in existing_tables:
        op.create_table('reminder_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('task_id', sa.Integer(), nullable=False),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.Column('channel', sa.String(length=20), nullable=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.ForeignKeyConstraint(['task_id'], ['cost_entry_tasks.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'cash_advance_monthly' not in existing_tables:
        op.create_table('cash_advance_monthly',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('sheet_name', sa.String(length=100), nullable=True),
            sa.Column('sheet_gid', sa.String(length=50), nullable=True),
            sa.Column('opening_balance', sa.Float(), nullable=True),
            sa.Column('total_company_receipts', sa.Float(), nullable=True),
            sa.Column('total_haiban_receipts', sa.Float(), nullable=True),
            sa.Column('total_other_receipts', sa.Float(), nullable=True),
            sa.Column('total_haiban_to_company', sa.Float(), nullable=True),
            sa.Column('total_advances_spent', sa.Float(), nullable=True),
            sa.Column('total_xuyen', sa.Float(), nullable=True),
            sa.Column('total_luong_thu', sa.Float(), nullable=True),
            sa.Column('total_luong_chi', sa.Float(), nullable=True),
            sa.Column('total_truong', sa.Float(), nullable=True),
            sa.Column('total_partner', sa.Float(), nullable=True),
            sa.Column('closing_balance', sa.Float(), nullable=True),
            sa.Column('creator_name', sa.String(length=100), nullable=True),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('year', 'month', name='uq_cash_advance_month_year')
        )

    if 'cash_advance_transactions' not in existing_tables:
        op.create_table('cash_advance_transactions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('monthly_id', sa.Integer(), nullable=True),
            sa.Column('month', sa.Integer(), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('row_index', sa.Integer(), nullable=True),
            sa.Column('trans_date', sa.String(length=50), nullable=True),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('tuan_ton', sa.Float(), nullable=True),
            sa.Column('tuan_thu_cty', sa.Float(), nullable=True),
            sa.Column('tuan_thu_haiban', sa.Float(), nullable=True),
            sa.Column('tuan_thu_khac', sa.Float(), nullable=True),
            sa.Column('tuan_chi_haiban_cty', sa.Float(), nullable=True),
            sa.Column('tuan_chi', sa.Float(), nullable=True),
            sa.Column('xuyen_amount', sa.Float(), nullable=True),
            sa.Column('luong_thu', sa.Float(), nullable=True),
            sa.Column('luong_chi', sa.Float(), nullable=True),
            sa.Column('truong_amount', sa.Float(), nullable=True),
            sa.Column('partner_amount', sa.Float(), nullable=True),
            sa.Column('partner_invoice', sa.String(length=500), nullable=True),
            sa.Column('bill_link', sa.String(length=500), nullable=True),
            sa.Column('advance_refund', sa.String(length=100), nullable=True),
            sa.Column('accounting_status', sa.String(length=100), nullable=True),
            sa.Column('is_manual', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['monthly_id'], ['cash_advance_monthly.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'cash_advance_bill_media' not in existing_tables:
        op.create_table('cash_advance_bill_media',
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('file_id', sa.Text(), nullable=True),
            sa.Column('filename', sa.String(length=255), nullable=True),
            sa.Column('mime_type', sa.String(length=100), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('data_base64', sa.Text(), nullable=True),
            sa.Column('storage_url', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

def downgrade():
    pass
