"""add revenue soft delete and operating-cost source traceability

Revision ID: 0004_rev_soft_delete_source
Revises: 0003_bill_foreign_keys
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_rev_soft_delete_source'
down_revision = '0003_bill_foreign_keys'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'revenue_items' in tables:
        cols = {c['name'] for c in inspector.get_columns('revenue_items')}
        with op.batch_alter_table('revenue_items') as batch:
            if 'is_deleted' not in cols:
                batch.add_column(sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()))
                batch.create_index('ix_revenue_items_is_deleted', ['is_deleted'], unique=False)
            if 'deleted_at' not in cols:
                batch.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_by' not in cols:
                batch.add_column(sa.Column('deleted_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_revenue_items_deleted_by'), nullable=True))
    if 'operating_costs' in tables:
        cols = {c['name'] for c in inspector.get_columns('operating_costs')}
        with op.batch_alter_table('operating_costs') as batch:
            if 'source_sheet' not in cols:
                batch.add_column(sa.Column('source_sheet', sa.String(length=50), nullable=True))
                batch.create_index('ix_operating_costs_source_sheet', ['source_sheet'], unique=False)
            if 'source_row' not in cols:
                batch.add_column(sa.Column('source_row', sa.Integer(), nullable=True))
            if 'source_payload' not in cols:
                batch.add_column(sa.Column('source_payload', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('operating_costs') as batch:
        batch.drop_column('source_payload')
        batch.drop_column('source_row')
        batch.drop_index('ix_operating_costs_source_sheet')
        batch.drop_column('source_sheet')
    with op.batch_alter_table('revenue_items') as batch:
        batch.drop_constraint('fk_revenue_items_deleted_by', type_='foreignkey')
        batch.drop_column('deleted_by')
        batch.drop_column('deleted_at')
        batch.drop_index('ix_revenue_items_is_deleted')
        batch.drop_column('is_deleted')
