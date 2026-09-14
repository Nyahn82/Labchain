"""Create the nine Phase 2C laboratory workflow tables.

Revision ID: 20260914_03
Revises: 20260914_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_03"
down_revision = "20260914_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('lab_order',
        sa.Column('order_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_code', sa.String(length=30), nullable=False),
        sa.Column('patient_id', sa.BigInteger(), nullable=False),
        sa.Column('physician_id', sa.BigInteger(), nullable=True),
        sa.Column('ordered_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('order_date', sa.DateTime(), nullable=False),
        sa.Column('priority', sa.Enum('ROUTINE', 'STAT', 'URGENT', name='order_priority'), nullable=False),
        sa.Column('request_reason', sa.String(length=150), nullable=True),
        sa.Column('clinical_notes', sa.Text(), nullable=True),
        sa.Column('diagnosis', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='lab_order_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ordered_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_order_ordered_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'], name=op.f('fk_lab_order_patient_id_patient')),
        sa.ForeignKeyConstraint(['physician_id'], ['requesting_physician.physician_id'], name=op.f('fk_lab_order_physician_id_requesting_physician')),
        sa.PrimaryKeyConstraint('order_id', name=op.f('pk_lab_order')),
        sa.UniqueConstraint('order_code', name=op.f('uq_lab_order_order_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_lab_order_ordered_by_user_id'), 'lab_order', ['ordered_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_order_patient_id'), 'lab_order', ['patient_id'], unique=False)
    op.create_index(op.f('ix_lab_order_physician_id'), 'lab_order', ['physician_id'], unique=False)
    op.create_table('order_panel',
        sa.Column('order_panel_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('panel_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='order_panel_status'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_order_panel_order_id_lab_order')),
        sa.ForeignKeyConstraint(['panel_id'], ['test_panel.panel_id'], name=op.f('fk_order_panel_panel_id_test_panel')),
        sa.PrimaryKeyConstraint('order_panel_id', name=op.f('pk_order_panel')),
        sa.UniqueConstraint('order_id', 'panel_id', name=op.f('uq_order_panel_order_id_panel_id')),
        sa.UniqueConstraint('order_panel_id', 'order_id', name=op.f('uq_order_panel_order_panel_id_order_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_order_panel_panel_id'), 'order_panel', ['panel_id'], unique=False)
    op.create_table('lab_order_item',
        sa.Column('order_item_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('test_id', sa.BigInteger(), nullable=False),
        sa.Column('order_panel_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Enum('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='lab_order_item_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_lab_order_item_order_id_lab_order')),
        sa.ForeignKeyConstraint(['order_panel_id', 'order_id'], ['order_panel.order_panel_id', 'order_panel.order_id'], name='fk_lab_order_item_order_panel_id_order_id_order_panel'),
        sa.ForeignKeyConstraint(['order_panel_id'], ['order_panel.order_panel_id'], name=op.f('fk_lab_order_item_order_panel_id_order_panel')),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.test_id'], name=op.f('fk_lab_order_item_test_id_test_catalog')),
        sa.PrimaryKeyConstraint('order_item_id', name=op.f('pk_lab_order_item')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_lab_order_item_order_id'), 'lab_order_item', ['order_id'], unique=False)
    op.create_index('ix_lab_order_item_order_panel_id_order_id', 'lab_order_item', ['order_panel_id', 'order_id'], unique=False)
    op.create_index(op.f('ix_lab_order_item_test_id'), 'lab_order_item', ['test_id'], unique=False)
    op.create_table('lab_payment',
        sa.Column('payment_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('payment_status', sa.Enum('PENDING', 'PAID', 'FREE', 'WAIVED', 'SUBSIDIZED', name='payment_status'), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('reference_number', sa.String(length=80), nullable=True),
        sa.Column('recorded_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_lab_payment_order_id_lab_order')),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_payment_recorded_by_user_id_user_account')),
        sa.PrimaryKeyConstraint('payment_id', name=op.f('pk_lab_payment')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_lab_payment_order_id'), 'lab_payment', ['order_id'], unique=False)
    op.create_index(op.f('ix_lab_payment_recorded_by_user_id'), 'lab_payment', ['recorded_by_user_id'], unique=False)
    op.create_table('specimen',
        sa.Column('specimen_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('specimen_code', sa.String(length=30), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('sample_type_id', sa.BigInteger(), nullable=False),
        sa.Column('collected_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('received_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('specimen_status', sa.Enum('PENDING', 'COLLECTED', 'RECEIVED', 'REJECTED', 'PROCESSED', name='specimen_status'), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['collected_by_user_id'], ['user_account.user_id'], name=op.f('fk_specimen_collected_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_specimen_order_id_lab_order')),
        sa.ForeignKeyConstraint(['received_by_user_id'], ['user_account.user_id'], name=op.f('fk_specimen_received_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['sample_type_id'], ['sample_type.sample_type_id'], name=op.f('fk_specimen_sample_type_id_sample_type')),
        sa.PrimaryKeyConstraint('specimen_id', name=op.f('pk_specimen')),
        sa.UniqueConstraint('specimen_code', name=op.f('uq_specimen_specimen_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_specimen_collected_by_user_id'), 'specimen', ['collected_by_user_id'], unique=False)
    op.create_index(op.f('ix_specimen_order_id'), 'specimen', ['order_id'], unique=False)
    op.create_index(op.f('ix_specimen_received_by_user_id'), 'specimen', ['received_by_user_id'], unique=False)
    op.create_index(op.f('ix_specimen_sample_type_id'), 'specimen', ['sample_type_id'], unique=False)
    op.create_table('specimen_order_item',
        sa.Column('specimen_order_item_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('specimen_id', sa.BigInteger(), nullable=False),
        sa.Column('order_item_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['order_item_id'], ['lab_order_item.order_item_id'], name=op.f('fk_specimen_order_item_order_item_id_lab_order_item')),
        sa.ForeignKeyConstraint(['specimen_id'], ['specimen.specimen_id'], name=op.f('fk_specimen_order_item_specimen_id_specimen')),
        sa.PrimaryKeyConstraint('specimen_order_item_id', name=op.f('pk_specimen_order_item')),
        sa.UniqueConstraint('specimen_id', 'order_item_id', name=op.f('uq_specimen_order_item_specimen_id_order_item_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_specimen_order_item_order_item_id'), 'specimen_order_item', ['order_item_id'], unique=False)
    op.create_table('rejection_reason',
        sa.Column('rejection_reason_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('reason_code', sa.String(length=40), nullable=False),
        sa.Column('reason_name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.PrimaryKeyConstraint('rejection_reason_id', name=op.f('pk_rejection_reason')),
        sa.UniqueConstraint('reason_code', name=op.f('uq_rejection_reason_reason_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('specimen_rejection',
        sa.Column('specimen_rejection_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('specimen_id', sa.BigInteger(), nullable=False),
        sa.Column('rejection_reason_id', sa.BigInteger(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('rejected_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('rejected_at', sa.DateTime(), nullable=False),
        sa.Column('recollection_required', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['rejected_by_user_id'], ['user_account.user_id'], name=op.f('fk_specimen_rejection_rejected_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['rejection_reason_id'], ['rejection_reason.rejection_reason_id'], name=op.f('fk_specimen_rejection_rejection_reason_id_rejection_reason')),
        sa.ForeignKeyConstraint(['specimen_id'], ['specimen.specimen_id'], name=op.f('fk_specimen_rejection_specimen_id_specimen')),
        sa.PrimaryKeyConstraint('specimen_rejection_id', name=op.f('pk_specimen_rejection')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_specimen_rejection_rejected_by_user_id'), 'specimen_rejection', ['rejected_by_user_id'], unique=False)
    op.create_index(op.f('ix_specimen_rejection_rejection_reason_id'), 'specimen_rejection', ['rejection_reason_id'], unique=False)
    op.create_index(op.f('ix_specimen_rejection_specimen_id'), 'specimen_rejection', ['specimen_id'], unique=False)
    op.create_table('lab_result_item',
        sa.Column('result_item_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_item_id', sa.BigInteger(), nullable=False),
        sa.Column('specimen_id', sa.BigInteger(), nullable=True),
        sa.Column('reference_range_id', sa.BigInteger(), nullable=True),
        sa.Column('result_value', sa.String(length=100), nullable=False),
        sa.Column('numeric_value', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('flag', sa.Enum('NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL', name='result_flag'), nullable=True),
        sa.Column('status', sa.Enum('DRAFT', 'REVIEWED', 'VERIFIED', name='result_status'), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('encoded_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('encoded_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('verified_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['encoded_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_result_item_encoded_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['order_item_id'], ['lab_order_item.order_item_id'], name=op.f('fk_lab_result_item_order_item_id_lab_order_item')),
        sa.ForeignKeyConstraint(['reference_range_id'], ['reference_range.range_id'], name=op.f('fk_lab_result_item_reference_range_id_reference_range')),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_result_item_reviewed_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['specimen_id'], ['specimen.specimen_id'], name=op.f('fk_lab_result_item_specimen_id_specimen')),
        sa.ForeignKeyConstraint(['verified_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_result_item_verified_by_user_id_user_account')),
        sa.PrimaryKeyConstraint('result_item_id', name=op.f('pk_lab_result_item')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_lab_result_item_encoded_by_user_id'), 'lab_result_item', ['encoded_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_result_item_order_item_id'), 'lab_result_item', ['order_item_id'], unique=False)
    op.create_index(op.f('ix_lab_result_item_reference_range_id'), 'lab_result_item', ['reference_range_id'], unique=False)
    op.create_index(op.f('ix_lab_result_item_reviewed_by_user_id'), 'lab_result_item', ['reviewed_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_result_item_specimen_id'), 'lab_result_item', ['specimen_id'], unique=False)
    op.create_index(op.f('ix_lab_result_item_verified_by_user_id'), 'lab_result_item', ['verified_by_user_id'], unique=False)


def downgrade() -> None:
    # Drop dependent tables first, removing their FK-supporting indexes together.
    op.drop_table('lab_result_item')
    op.drop_table('specimen_rejection')
    op.drop_table('rejection_reason')
    op.drop_table('specimen_order_item')
    op.drop_table('specimen')
    op.drop_table('lab_payment')
    op.drop_table('lab_order_item')
    op.drop_table('order_panel')
    op.drop_table('lab_order')
