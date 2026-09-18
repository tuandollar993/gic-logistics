"""add parent_cost_id and parent_revenue_item_id to operating_costs

Revision ID: 0007_cost_parent_sub_items
Revises: 0006_settlement_tracking
Create Date: 2026-09-18 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0007_cost_parent_sub_items'
down_revision = '0006_settlement_tracking'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'operating_costs' in existing_tables:
        cols = {c['name'] for c in inspector.get_columns('operating_costs')}
        with op.batch_alter_table('operating_costs') as batch_op:
            if 'parent_cost_id' not in cols:
                batch_op.add_column(
                    sa.Column(
                        'parent_cost_id',
                        sa.Integer(),
                        sa.ForeignKey('operating_costs.id', name='fk_op_costs_parent_cost_id', ondelete='CASCADE'),
                        nullable=True
                    )
                )
                batch_op.create_index('ix_operating_costs_parent_cost_id', ['parent_cost_id'], unique=False)
            if 'parent_revenue_item_id' not in cols:
                batch_op.add_column(
                    sa.Column(
                        'parent_revenue_item_id',
                        sa.Integer(),
                        sa.ForeignKey('revenue_items.id', name='fk_op_costs_parent_rev_item_id', ondelete='CASCADE'),
                        nullable=True
                    )
                )
                batch_op.create_index('ix_operating_costs_parent_revenue_item_id', ['parent_revenue_item_id'], unique=False)

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'operating_costs' in existing_tables:
        with op.batch_alter_table('operating_costs') as batch_op:
            batch_op.drop_index('ix_operating_costs_parent_revenue_item_id')
            batch_op.drop_column('parent_revenue_item_id')
            batch_op.drop_index('ix_operating_costs_parent_cost_id')
            batch_op.drop_column('parent_cost_id')
