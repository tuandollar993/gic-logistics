"""add cashflow lock, audit logs, and soft deletes

Revision ID: 0002_lock_audit
Revises: 0001_initial
Create Date: 2026-09-11 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0002_lock_audit'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. cash_advance_monthly columns
    if 'cash_advance_monthly' in existing_tables:
        cam_cols = {c['name'] for c in inspector.get_columns('cash_advance_monthly')}
        with op.batch_alter_table('cash_advance_monthly') as batch_op:
            if 'is_locked' not in cam_cols:
                batch_op.add_column(sa.Column('is_locked', sa.Boolean(), nullable=False, server_default='0'))
            if 'locked_at' not in cam_cols:
                batch_op.add_column(sa.Column('locked_at', sa.DateTime(), nullable=True))
            if 'locked_by' not in cam_cols:
                batch_op.add_column(sa.Column('locked_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_cam_locked_by'), nullable=True))

    # 2. cash_advance_transactions columns & indexes
    if 'cash_advance_transactions' in existing_tables:
        cat_cols = {c['name'] for c in inspector.get_columns('cash_advance_transactions')}
        with op.batch_alter_table('cash_advance_transactions') as batch_op:
            if 'external_id' not in cat_cols:
                batch_op.add_column(sa.Column('external_id', sa.String(length=128), nullable=True))
                batch_op.create_unique_constraint('uq_cat_external_id', ['external_id'])
            if 'sync_status' not in cat_cols:
                batch_op.add_column(sa.Column('sync_status', sa.String(length=30), server_default='synced'))
            if 'sync_hash' not in cat_cols:
                batch_op.add_column(sa.Column('sync_hash', sa.String(length=64), nullable=True))
            if 'is_deleted' not in cat_cols:
                batch_op.add_column(sa.Column('is_deleted', sa.Boolean(), server_default='0'))
            if 'deleted_at' not in cat_cols:
                batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_reason' not in cat_cols:
                batch_op.add_column(sa.Column('deleted_reason', sa.Text(), nullable=True))

    # 3. lots soft delete columns
    if 'lots' in existing_tables:
        lot_cols = {c['name'] for c in inspector.get_columns('lots')}
        with op.batch_alter_table('lots') as batch_op:
            if 'is_deleted' not in lot_cols:
                batch_op.add_column(sa.Column('is_deleted', sa.Boolean(), server_default='0'))
            if 'deleted_at' not in lot_cols:
                batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_by' not in lot_cols:
                batch_op.add_column(sa.Column('deleted_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_lots_deleted_by'), nullable=True))

    # 4. operating_costs soft delete columns
    if 'operating_costs' in existing_tables:
        opc_cols = {c['name'] for c in inspector.get_columns('operating_costs')}
        with op.batch_alter_table('operating_costs') as batch_op:
            if 'is_deleted' not in opc_cols:
                batch_op.add_column(sa.Column('is_deleted', sa.Boolean(), server_default='0'))
            if 'deleted_at' not in opc_cols:
                batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
            if 'deleted_by' not in opc_cols:
                batch_op.add_column(sa.Column('deleted_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_operating_costs_deleted_by'), nullable=True))

    # 5. audit_logs table
    if 'audit_logs' not in existing_tables:
        op.create_table('audit_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('actor', sa.String(length=100), nullable=True),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('target_type', sa.String(length=50), nullable=False),
            sa.Column('target_id', sa.String(length=64), nullable=True),
            sa.Column('before_state', sa.Text(), nullable=True),
            sa.Column('after_state', sa.Text(), nullable=True),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('request_id', sa.String(length=64), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
        op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
        op.create_index('ix_audit_logs_target_id', 'audit_logs', ['target_id'], unique=False)
        op.create_index('ix_audit_logs_target_type', 'audit_logs', ['target_type'], unique=False)
        op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'], unique=False)

    # 6. Controlled data migration: ensure initial admin user is active with role admin
    if 'users' in existing_tables:
        bind.execute(sa.text("UPDATE users SET role = 'admin' WHERE username = 'admin' AND role != 'admin'"))

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'audit_logs' in existing_tables:
        op.drop_table('audit_logs')

    if 'operating_costs' in existing_tables:
        with op.batch_alter_table('operating_costs') as batch_op:
            batch_op.drop_column('deleted_by')
            batch_op.drop_column('deleted_at')
            batch_op.drop_column('is_deleted')

    if 'lots' in existing_tables:
        with op.batch_alter_table('lots') as batch_op:
            batch_op.drop_column('deleted_by')
            batch_op.drop_column('deleted_at')
            batch_op.drop_column('is_deleted')

    if 'cash_advance_transactions' in existing_tables:
        with op.batch_alter_table('cash_advance_transactions') as batch_op:
            batch_op.drop_column('deleted_reason')
            batch_op.drop_column('deleted_at')
            batch_op.drop_column('is_deleted')
            batch_op.drop_column('sync_hash')
            batch_op.drop_column('sync_status')
            batch_op.drop_constraint('uq_cat_external_id', type_='unique')
            batch_op.drop_column('external_id')

    if 'cash_advance_monthly' in existing_tables:
        with op.batch_alter_table('cash_advance_monthly') as batch_op:
            batch_op.drop_column('locked_by')
            batch_op.drop_column('locked_at')
            batch_op.drop_column('is_locked')
