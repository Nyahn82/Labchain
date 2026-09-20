"""Add encrypted MFA infrastructure and session assurance.

Revision ID: 20260920_01
Revises: 20260916_01
"""
from alembic import op
import sqlalchemy as sa

revision = '20260920_01'
down_revision = '20260916_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_totp_mfa',
        sa.Column('mfa_id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('secret_ciphertext', sa.Text(), nullable=False),
        sa.Column('secret_nonce', sa.LargeBinary(12), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('enabled_at', sa.DateTime(), nullable=True),
        sa.Column('disabled_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_counter', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_user_totp_mfa_user_id_user_account')),
        sa.UniqueConstraint('user_id', name=op.f('uq_user_totp_mfa_user_id')),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('mfa_recovery_code',
        sa.Column('recovery_code_id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('mfa_id', sa.BigInteger(), nullable=False),
        sa.Column('code_hash', sa.CHAR(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['mfa_id'], ['user_totp_mfa.mfa_id'], name=op.f('fk_mfa_recovery_code_mfa_id_user_totp_mfa')),
        sa.UniqueConstraint('code_hash', name=op.f('uq_mfa_recovery_code_code_hash')),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index(op.f('ix_mfa_recovery_code_mfa_id'), 'mfa_recovery_code', ['mfa_id'])
    op.create_table('mfa_challenge',
        sa.Column('challenge_id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.CHAR(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_mfa_challenge_user_id_user_account')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_mfa_challenge_token_hash')),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    for column in ('user_id', 'expires_at'):
        op.create_index(op.f(f'ix_mfa_challenge_{column}'), 'mfa_challenge', [column])
    op.add_column('auth_session', sa.Column('mfa_verified_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('auth_session', 'mfa_verified_at')
    for table in ('mfa_challenge', 'mfa_recovery_code', 'user_totp_mfa'):
        op.drop_table(table)
