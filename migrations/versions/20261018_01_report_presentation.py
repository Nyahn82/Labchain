"""Freeze PDF v2 presentation metadata for newly generated reports.

Revision ID: 20261018_01
Revises: 20261015_01

Existing rows remain NULL and use the legacy renderer. No stored artifacts,
clinical snapshots, verification hashes or blockchain records are rewritten.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261018_01'
down_revision = '20261015_01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('lab_report', sa.Column('presentation_snapshot', sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError('Downgrade refused: PDF presentation history must be preserved.')
