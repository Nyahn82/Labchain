"""Add opaque browser session infrastructure.

Revision ID: 20260915_01
Revises: 20260914_04
"""

from alembic import op
import sqlalchemy as sa

revision = "20260915_01"
down_revision = "20260914_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_session",
        sa.Column("session_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("csrf_token_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.user_id"],
            name=op.f("fk_auth_session_user_id_user_account"),
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_auth_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_session_token_hash")),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    for column in ("user_id", "expires_at", "revoked_at"):
        op.create_index(op.f(f"ix_auth_session_{column}"), "auth_session", [column], unique=False)


def downgrade() -> None:
    # Keep the FK-supporting index until the table itself is dropped.
    op.drop_table("auth_session")
