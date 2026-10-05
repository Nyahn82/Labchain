"""Add suspension states/metadata without rewriting legacy INACTIVE records.

Downgrade refuses new states or populated metadata before any DDL. MySQL DDL
is not transactional; quiesce writers and back up before applying later.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261005_01'
down_revision = '20260924_01'
branch_labels = None
depends_on = None
OLD = ('ACTIVE', 'INACTIVE', 'LOCKED')
NEW = (*OLD, 'SUSPENDED', 'DISABLED')


def upgrade():
    with op.batch_alter_table('user_account') as batch:
        batch.alter_column('account_status', existing_type=sa.Enum(*OLD, name='account_status'),
                           type_=sa.Enum(*NEW, name='account_status'), existing_nullable=False)
        batch.add_column(sa.Column('suspended_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('suspended_by_user_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('suspension_reason', sa.String(500), nullable=True))
        batch.create_foreign_key(op.f('fk_user_account_suspended_by_user_id_user_account'),
                                 'user_account', ['suspended_by_user_id'], ['user_id'], ondelete='SET NULL')
        batch.create_index(op.f('ix_user_account_suspended_by_user_id'), ['suspended_by_user_id'])


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError('Phase 10 downgrade requires an online data preservation check.')
    table = sa.table('user_account', sa.column('account_status'), sa.column('suspended_at'),
                     sa.column('suspended_by_user_id'), sa.column('suspension_reason'))
    if op.get_bind().execute(sa.select(table.c.account_status).where(sa.or_(
        table.c.account_status.in_(['SUSPENDED', 'DISABLED']), table.c.suspended_at.is_not(None),
        table.c.suspended_by_user_id.is_not(None), table.c.suspension_reason.is_not(None))).limit(1)).first():
        raise RuntimeError('Phase 10 downgrade refused: new account states or suspension metadata exist.')
    with op.batch_alter_table('user_account') as batch:
        batch.drop_constraint(op.f('fk_user_account_suspended_by_user_id_user_account'), type_='foreignkey')
        batch.drop_index(op.f('ix_user_account_suspended_by_user_id'))
        for name in ('suspension_reason', 'suspended_by_user_id', 'suspended_at'):
            batch.drop_column(name)
        batch.alter_column('account_status', existing_type=sa.Enum(*NEW, name='account_status'),
                           type_=sa.Enum(*OLD, name='account_status'), existing_nullable=False)
