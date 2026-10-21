"""Add catalog approval, structured results and order-time definitions.

Additive only: no existing row, automatic code or PDF is rewritten.
"""
from alembic import op
import sqlalchemy as sa
revision = '20261021_01'
down_revision = '20261019_01'
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in {
        'sample_type': [('specimen_code', sa.String(40)), ('collection_guidance', sa.JSON())],
        'test_catalog': [('aliases', sa.Text()), ('catalog_metadata', sa.JSON()), ('result_schema', sa.JSON()),
                         ('facility_status', sa.String(24)), ('approval_note', sa.Text())],
        'test_panel': [('facility_status', sa.String(24)), ('approval_note', sa.Text()), ('catalog_metadata', sa.JSON())],
        'order_panel': [('definition_snapshot', sa.JSON())],
        'lab_order_item': [('definition_snapshot', sa.JSON())],
        'lab_result_item': [('structured_values', sa.JSON())],
    }.items():
        for name, datatype in columns:
            op.add_column(table, sa.Column(name, datatype, nullable=True))
    op.create_index('uq_sample_type_specimen_code', 'sample_type', ['specimen_code'], unique=True)
    op.create_index('ix_test_catalog_facility_status', 'test_catalog', ['facility_status'])


def downgrade():
    raise RuntimeError('Destructive downgrade refused: preserve order snapshots and results; use coordinated recovery.')
