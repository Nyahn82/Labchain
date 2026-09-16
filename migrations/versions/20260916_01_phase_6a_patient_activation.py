"""Add one-time patient activation infrastructure.

Revision ID: 20260916_01
Revises: 20260915_01
"""
from alembic import op
import sqlalchemy as sa

revision = '20260916_01'
down_revision = '20260915_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'patient_activation_token',
        sa.Column('activation_token_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('patient_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.CHAR(64), nullable=False),
        sa.Column('issued_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'],
            name=op.f('fk_patient_activation_token_patient_id_patient')),
        sa.ForeignKeyConstraint(['issued_by_user_id'], ['user_account.user_id'],
            name=op.f('fk_patient_activation_token_issued_by_user_id_user_account')),
        sa.PrimaryKeyConstraint('activation_token_id', name=op.f('pk_patient_activation_token')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_patient_activation_token_token_hash')),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    for column in ('patient_id', 'issued_by_user_id', 'expires_at'):
        op.create_index(op.f(f'ix_patient_activation_token_{column}'), 'patient_activation_token', [column], unique=False)


def downgrade() -> None:
    op.drop_table('patient_activation_token')
