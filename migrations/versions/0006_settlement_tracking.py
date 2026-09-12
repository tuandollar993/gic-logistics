"""add settlement tracking fields and monthly_settlements table

Revision ID: 0006_settlement_tracking
Revises: 0005_customer_extended_fields
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_settlement_tracking'
down_revision = '0005_customer_extended_fields'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # --- Add columns to cash_advance_transactions ---
    if 'cash_advance_transactions' in tables:
        cols = {c['name'] for c in inspector.get_columns('cash_advance_transactions')}

        new_cols = [
            ('invoice_category', sa.String(20), 'unknown'),
            ('refund_status', sa.String(20), 'pending'),
            ('refund_deadline', sa.Date, None),
            ('refund_settled_at', sa.DateTime, None),
            ('exclusion_status', sa.String(20), None),
            ('exclusion_requested_at', sa.DateTime, None),
            ('exclusion_approved_at', sa.DateTime, None),
            ('exclusion_approved_by', sa.Integer, None),
            ('exclusion_note', sa.Text, None),
        ]

        for col_name, col_type, default in new_cols:
            if col_name not in cols:
                col = sa.Column(col_name, col_type, nullable=True, server_default=str(default) if default else None)
                op.add_column('cash_advance_transactions', col)

    # --- Create monthly_settlements table ---
    if 'monthly_settlements' not in tables:
        op.create_table(
            'monthly_settlements',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('month', sa.Integer, nullable=False, index=True),
            sa.Column('year', sa.Integer, nullable=False, index=True),
            sa.Column('total_expenses', sa.Float, server_default='0'),
            sa.Column('total_with_invoice', sa.Float, server_default='0'),
            sa.Column('total_no_invoice', sa.Float, server_default='0'),
            sa.Column('total_settled', sa.Float, server_default='0'),
            sa.Column('total_excluded', sa.Float, server_default='0'),
            sa.Column('total_overdue', sa.Float, server_default='0'),
            sa.Column('total_to_remit', sa.Float, server_default='0'),
            sa.Column('count_total', sa.Integer, server_default='0'),
            sa.Column('count_with_invoice', sa.Integer, server_default='0'),
            sa.Column('count_no_invoice', sa.Integer, server_default='0'),
            sa.Column('count_settled', sa.Integer, server_default='0'),
            sa.Column('count_excluded', sa.Integer, server_default='0'),
            sa.Column('count_overdue', sa.Integer, server_default='0'),
            sa.Column('count_pending', sa.Integer, server_default='0'),
            sa.Column('status', sa.String(20), server_default='open'),
            sa.Column('closed_at', sa.DateTime, nullable=True),
            sa.Column('closed_by', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
            sa.UniqueConstraint('year', 'month', name='uq_settlement_year_month'),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'monthly_settlements' in tables:
        op.drop_table('monthly_settlements')

    if 'cash_advance_transactions' in tables:
        cols = {c['name'] for c in inspector.get_columns('cash_advance_transactions')}
        for col_name in [
            'invoice_category', 'refund_status', 'refund_deadline',
            'refund_settled_at', 'exclusion_status', 'exclusion_requested_at',
            'exclusion_approved_at', 'exclusion_approved_by', 'exclusion_note',
        ]:
            if col_name in cols:
                op.drop_column('cash_advance_transactions', col_name)
