"""add customer extended fields

Revision ID: 0005_customer_extended_fields
Revises: 0004_rev_soft_delete_source
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_customer_extended_fields'
down_revision = '0004_rev_soft_delete_source'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'customers' in tables:
        cols = {c['name'] for c in inspector.get_columns('customers')}
        with op.batch_alter_table('customers') as batch:
            if 'contact_person' not in cols:
                batch.add_column(sa.Column('contact_person', sa.String(length=100), nullable=True))
            if 'phone' not in cols:
                batch.add_column(sa.Column('phone', sa.String(length=50), nullable=True))
            if 'email' not in cols:
                batch.add_column(sa.Column('email', sa.String(length=100), nullable=True))
            if 'address' not in cols:
                batch.add_column(sa.Column('address', sa.Text(), nullable=True))
            if 'tax_code' not in cols:
                batch.add_column(sa.Column('tax_code', sa.String(length=50), nullable=True))
            if 'notes' not in cols:
                batch.add_column(sa.Column('notes', sa.Text(), nullable=True))
            if 'is_active' not in cols:
                batch.add_column(sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()))
            if 'created_at' not in cols:
                batch.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('customers') as batch:
        batch.drop_column('created_at')
        batch.drop_column('is_active')
        batch.drop_column('notes')
        batch.drop_column('tax_code')
        batch.drop_column('address')
        batch.drop_column('email')
        batch.drop_column('phone')
        batch.drop_column('contact_person')
