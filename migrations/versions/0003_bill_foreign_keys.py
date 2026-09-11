"""add foreign keys to cash_advance_bill_media

Revision ID: 0003_bill_foreign_keys
Revises: 0002_lock_audit
Create Date: 2026-09-11 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0003_bill_foreign_keys'
down_revision = '0002_lock_audit'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'cash_advance_bill_media' in existing_tables:
        cols = {c['name'] for c in inspector.get_columns('cash_advance_bill_media')}
        with op.batch_alter_table('cash_advance_bill_media') as batch_op:
            if 'transaction_id' not in cols:
                batch_op.add_column(sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('cash_advance_transactions.id', name='fk_cabm_transaction_id'), nullable=True))
                batch_op.create_index('ix_cabm_transaction_id', ['transaction_id'], unique=False)
            if 'operating_cost_id' not in cols:
                batch_op.add_column(sa.Column('operating_cost_id', sa.Integer(), sa.ForeignKey('operating_costs.id', name='fk_cabm_operating_cost_id'), nullable=True))
                batch_op.create_index('ix_cabm_operating_cost_id', ['operating_cost_id'], unique=False)
            if 'lot_id' not in cols:
                batch_op.add_column(sa.Column('lot_id', sa.Integer(), sa.ForeignKey('lots.id', name='fk_cabm_lot_id'), nullable=True))
                batch_op.create_index('ix_cabm_lot_id', ['lot_id'], unique=False)
            if 'uploaded_by' not in cols:
                batch_op.add_column(sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_cabm_uploaded_by'), nullable=True))
                batch_op.create_index('ix_cabm_uploaded_by', ['uploaded_by'], unique=False)

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'cash_advance_bill_media' in existing_tables:
        with op.batch_alter_table('cash_advance_bill_media') as batch_op:
            batch_op.drop_index('ix_cabm_uploaded_by')
            batch_op.drop_column('uploaded_by')
            batch_op.drop_index('ix_cabm_lot_id')
            batch_op.drop_column('lot_id')
            batch_op.drop_index('ix_cabm_operating_cost_id')
            batch_op.drop_column('operating_cost_id')
            batch_op.drop_index('ix_cabm_transaction_id')
            batch_op.drop_column('transaction_id')
