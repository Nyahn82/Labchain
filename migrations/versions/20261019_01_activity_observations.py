"""Add bounded authenticated activity and worker observations; no historical inference.

Revision ID: 20261019_01
Revises: 20261018_01
"""
from alembic import op
import sqlalchemy as sa

revision = '20261019_01'
down_revision = '20261018_01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('auth_session', sa.Column('last_activity_at', sa.DateTime(), nullable=True))
    op.create_index('ix_auth_session_last_activity_at', 'auth_session', ['last_activity_at'])
    op.create_table('service_observation',
        sa.Column('service', sa.String(40), primary_key=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')


def downgrade():
    raise RuntimeError('Downgrade refused: retain activity observations; use a reviewed recovery plan.')
