"""Create sixteen Phase 2D reporting, audit and blockchain support tables.

Revision ID: 20260914_04
Revises: 20260914_03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_04"
down_revision = "20260914_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('report_template',
        sa.Column('template_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('template_code', sa.String(length=40), nullable=False),
        sa.Column('template_name', sa.String(length=100), nullable=False),
        sa.Column('panel_id', sa.BigInteger(), nullable=True),
        sa.Column('header_title', sa.String(length=150), nullable=True),
        sa.Column('section_title', sa.String(length=150), nullable=True),
        sa.Column('clinical_note', sa.Text(), nullable=True),
        sa.Column('footer_note', sa.Text(), nullable=True),
        sa.Column('medico_legal_note', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['panel_id'], ['test_panel.panel_id'], name=op.f('fk_report_template_panel_id_test_panel')),
        sa.PrimaryKeyConstraint('template_id', name=op.f('pk_report_template')),
        sa.UniqueConstraint('template_code', name=op.f('uq_report_template_template_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_report_template_panel_id'), 'report_template', ['panel_id'], unique=False)
    op.create_table('lab_report',
        sa.Column('report_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_code', sa.String(length=30), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('facility_id', sa.BigInteger(), nullable=False),
        sa.Column('template_id', sa.BigInteger(), nullable=True),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('supersedes_report_id', sa.BigInteger(), nullable=True),
        sa.Column('report_status', sa.Enum('GENERATED', 'APPROVED', 'RELEASED', 'REVOKED', name='lab_report_report_status'), nullable=False),
        sa.Column('generated_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('released_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),
        sa.Column('pdf_path', sa.String(length=255), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_report_approved_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['facility_id'], ['facility_profile.facility_id'], name=op.f('fk_lab_report_facility_id_facility_profile')),
        sa.ForeignKeyConstraint(['generated_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_report_generated_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_lab_report_order_id_lab_order')),
        sa.ForeignKeyConstraint(['released_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_report_released_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['revoked_by_user_id'], ['user_account.user_id'], name=op.f('fk_lab_report_revoked_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['supersedes_report_id'], ['lab_report.report_id'], name=op.f('fk_lab_report_supersedes_report_id_lab_report')),
        sa.ForeignKeyConstraint(['template_id'], ['report_template.template_id'], name=op.f('fk_lab_report_template_id_report_template')),
        sa.PrimaryKeyConstraint('report_id', name=op.f('pk_lab_report')),
        sa.UniqueConstraint('report_code', name=op.f('uq_lab_report_report_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_lab_report_approved_by_user_id'), 'lab_report', ['approved_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_report_facility_id'), 'lab_report', ['facility_id'], unique=False)
    op.create_index(op.f('ix_lab_report_generated_by_user_id'), 'lab_report', ['generated_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_report_order_id'), 'lab_report', ['order_id'], unique=False)
    op.create_index(op.f('ix_lab_report_released_by_user_id'), 'lab_report', ['released_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_report_revoked_by_user_id'), 'lab_report', ['revoked_by_user_id'], unique=False)
    op.create_index(op.f('ix_lab_report_supersedes_report_id'), 'lab_report', ['supersedes_report_id'], unique=False)
    op.create_index(op.f('ix_lab_report_template_id'), 'lab_report', ['template_id'], unique=False)
    op.create_table('report_result_item',
        sa.Column('report_result_item_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('result_item_id', sa.BigInteger(), nullable=False),
        sa.Column('panel_id_snapshot', sa.BigInteger(), nullable=True),
        sa.Column('section_name_snapshot', sa.String(length=120), nullable=True),
        sa.Column('test_name_snapshot', sa.String(length=150), nullable=False),
        sa.Column('result_value_snapshot', sa.String(length=100), nullable=False),
        sa.Column('unit_snapshot', sa.String(length=50), nullable=True),
        sa.Column('reference_range_snapshot', sa.String(length=120), nullable=True),
        sa.Column('flag_snapshot', sa.String(length=40), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['panel_id_snapshot'], ['test_panel.panel_id'], name=op.f('fk_report_result_item_panel_id_snapshot_test_panel')),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_report_result_item_report_id_lab_report')),
        sa.ForeignKeyConstraint(['result_item_id'], ['lab_result_item.result_item_id'], name=op.f('fk_report_result_item_result_item_id_lab_result_item')),
        sa.PrimaryKeyConstraint('report_result_item_id', name=op.f('pk_report_result_item')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_report_result_item_panel_id_snapshot'), 'report_result_item', ['panel_id_snapshot'], unique=False)
    op.create_index(op.f('ix_report_result_item_report_id'), 'report_result_item', ['report_id'], unique=False)
    op.create_index(op.f('ix_report_result_item_result_item_id'), 'report_result_item', ['result_item_id'], unique=False)
    op.create_table('report_patient_snapshot',
        sa.Column('report_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('patient_code', sa.String(length=20), nullable=False),
        sa.Column('patient_name', sa.String(length=220), nullable=False),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('age_at_report', sa.Integer(), nullable=True),
        sa.Column('sex', sa.String(length=20), nullable=True),
        sa.Column('physician_name', sa.String(length=220), nullable=True),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_report_patient_snapshot_report_id_lab_report')),
        sa.PrimaryKeyConstraint('report_id', name=op.f('pk_report_patient_snapshot')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('signatory',
        sa.Column('signatory_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('staff_id', sa.BigInteger(), nullable=False),
        sa.Column('signature_image_path', sa.String(length=255), nullable=True),
        sa.Column('license_number_snapshot', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.staff_id'], name=op.f('fk_signatory_staff_id_staff')),
        sa.PrimaryKeyConstraint('signatory_id', name=op.f('pk_signatory')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_signatory_staff_id'), 'signatory', ['staff_id'], unique=False)
    op.create_table('report_signatory',
        sa.Column('report_signatory_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('signatory_id', sa.BigInteger(), nullable=False),
        sa.Column('signatory_type', sa.Enum('LAB_IN_CHARGE', 'MEDICAL_TECHNOLOGIST', 'PATHOLOGIST', name='report_signatory_signatory_type'), nullable=False),
        sa.Column('signed_at', sa.DateTime(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_report_signatory_report_id_lab_report')),
        sa.ForeignKeyConstraint(['signatory_id'], ['signatory.signatory_id'], name=op.f('fk_report_signatory_signatory_id_signatory')),
        sa.PrimaryKeyConstraint('report_signatory_id', name=op.f('pk_report_signatory')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_report_signatory_report_id'), 'report_signatory', ['report_id'], unique=False)
    op.create_index(op.f('ix_report_signatory_signatory_id'), 'report_signatory', ['signatory_id'], unique=False)
    op.create_table('report_verification',
        sa.Column('verification_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('verification_token', sa.String(length=120), nullable=False),
        sa.Column('report_hash', sa.CHAR(length=64), nullable=False),
        sa.Column('verification_status', sa.Enum('AUTHENTIC', 'REVOKED', name='report_verification_verification_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_report_verification_report_id_lab_report')),
        sa.PrimaryKeyConstraint('verification_id', name=op.f('pk_report_verification')),
        sa.UniqueConstraint('verification_token', name=op.f('uq_report_verification_verification_token')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_report_verification_report_id'), 'report_verification', ['report_id'], unique=False)
    op.create_table('email_log',
        sa.Column('email_log_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=True),
        sa.Column('patient_id', sa.BigInteger(), nullable=True),
        sa.Column('recipient_email', sa.String(length=254), nullable=False),
        sa.Column('subject', sa.String(length=180), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'SENT', 'FAILED', name='email_log_status'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'], name=op.f('fk_email_log_patient_id_patient')),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_email_log_report_id_lab_report')),
        sa.PrimaryKeyConstraint('email_log_id', name=op.f('pk_email_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_email_log_patient_id'), 'email_log', ['patient_id'], unique=False)
    op.create_index(op.f('ix_email_log_report_id'), 'email_log', ['report_id'], unique=False)
    op.create_table('print_log',
        sa.Column('print_log_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('printed_by_user_id', sa.BigInteger(), nullable=False),
        sa.Column('printed_at', sa.DateTime(), nullable=False),
        sa.Column('copies', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['printed_by_user_id'], ['user_account.user_id'], name=op.f('fk_print_log_printed_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_print_log_report_id_lab_report')),
        sa.PrimaryKeyConstraint('print_log_id', name=op.f('pk_print_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_print_log_printed_by_user_id'), 'print_log', ['printed_by_user_id'], unique=False)
    op.create_index(op.f('ix_print_log_report_id'), 'print_log', ['report_id'], unique=False)
    op.create_table('audit_log',
        sa.Column('audit_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('record_id', sa.BigInteger(), nullable=True),
        sa.Column('old_value', sa.JSON(none_as_null=True), nullable=True),
        sa.Column('new_value', sa.JSON(none_as_null=True), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_audit_log_user_id_user_account')),
        sa.PrimaryKeyConstraint('audit_id', name=op.f('pk_audit_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'], unique=False)
    op.create_table('login_log',
        sa.Column('login_log_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('username_attempted', sa.String(length=60), nullable=True),
        sa.Column('login_time', sa.DateTime(), nullable=False),
        sa.Column('logout_time', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('status', sa.Enum('SUCCESS', 'FAILED', name='login_log_status'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_login_log_user_id_user_account')),
        sa.PrimaryKeyConstraint('login_log_id', name=op.f('pk_login_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_login_log_user_id'), 'login_log', ['user_id'], unique=False)
    op.create_table('attachment',
        sa.Column('attachment_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=True),
        sa.Column('report_id', sa.BigInteger(), nullable=True),
        sa.Column('file_name', sa.String(length=180), nullable=False),
        sa.Column('file_path', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.String(length=80), nullable=True),
        sa.Column('uploaded_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('order_id IS NOT NULL OR report_id IS NOT NULL', name=op.f('ck_attachment_parent_required')),
        sa.ForeignKeyConstraint(['order_id'], ['lab_order.order_id'], name=op.f('fk_attachment_order_id_lab_order')),
        sa.ForeignKeyConstraint(['report_id'], ['lab_report.report_id'], name=op.f('fk_attachment_report_id_lab_report')),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['user_account.user_id'], name=op.f('fk_attachment_uploaded_by_user_id_user_account')),
        sa.PrimaryKeyConstraint('attachment_id', name=op.f('pk_attachment')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_attachment_order_id'), 'attachment', ['order_id'], unique=False)
    op.create_index(op.f('ix_attachment_report_id'), 'attachment', ['report_id'], unique=False)
    op.create_index(op.f('ix_attachment_uploaded_by_user_id'), 'attachment', ['uploaded_by_user_id'], unique=False)
    op.create_table('blockchain_node',
        sa.Column('node_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('node_code', sa.String(length=30), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('node_role', sa.String(length=120), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.PrimaryKeyConstraint('node_id', name=op.f('pk_blockchain_node')),
        sa.UniqueConstraint('node_code', name=op.f('uq_blockchain_node_node_code')),
        sa.UniqueConstraint('port', name=op.f('uq_blockchain_node_port')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('blockchain_event',
        sa.Column('event_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_uuid', sa.CHAR(length=36), nullable=False),
        sa.Column('origin_node_id', sa.BigInteger(), nullable=False),
        sa.Column('entity_type', sa.String(length=80), nullable=False),
        sa.Column('entity_id', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('record_hash', sa.CHAR(length=64), nullable=False),
        sa.Column('event_status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', name='blockchain_event_event_status'), nullable=False),
        sa.Column('created_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user_account.user_id'], name=op.f('fk_blockchain_event_created_by_user_id_user_account')),
        sa.ForeignKeyConstraint(['origin_node_id'], ['blockchain_node.node_id'], name=op.f('fk_blockchain_event_origin_node_id_blockchain_node')),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_blockchain_event')),
        sa.UniqueConstraint('event_uuid', name=op.f('uq_blockchain_event_event_uuid')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_blockchain_event_created_by_user_id'), 'blockchain_event', ['created_by_user_id'], unique=False)
    op.create_index(op.f('ix_blockchain_event_origin_node_id'), 'blockchain_event', ['origin_node_id'], unique=False)
    op.create_table('blockchain_verification_log',
        sa.Column('verification_log_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('node_id', sa.BigInteger(), nullable=False),
        sa.Column('database_hash', sa.CHAR(length=64), nullable=False),
        sa.Column('chain_hash', sa.CHAR(length=64), nullable=False),
        sa.Column('verification_status', sa.Enum('MATCH', 'MISMATCH', 'NOT_FOUND', name='blockchain_verification_log_verification_status'), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['blockchain_event.event_id'], name=op.f('fk_blockchain_verification_log_event_id_blockchain_event')),
        sa.ForeignKeyConstraint(['node_id'], ['blockchain_node.node_id'], name=op.f('fk_blockchain_verification_log_node_id_blockchain_node')),
        sa.PrimaryKeyConstraint('verification_log_id', name=op.f('pk_blockchain_verification_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_blockchain_verification_log_event_id'), 'blockchain_verification_log', ['event_id'], unique=False)
    op.create_index(op.f('ix_blockchain_verification_log_node_id'), 'blockchain_verification_log', ['node_id'], unique=False)
    op.create_table('blockchain_sync_log',
        sa.Column('sync_log_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source_node_id', sa.BigInteger(), nullable=False),
        sa.Column('target_node_id', sa.BigInteger(), nullable=False),
        sa.Column('block_height', sa.BigInteger(), nullable=True),
        sa.Column('sync_status', sa.Enum('SUCCESS', 'FAILED', 'CONFLICT', name='blockchain_sync_log_sync_status'), nullable=False),
        sa.Column('synced_at', sa.DateTime(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['source_node_id'], ['blockchain_node.node_id'], name=op.f('fk_blockchain_sync_log_source_node_id_blockchain_node')),
        sa.ForeignKeyConstraint(['target_node_id'], ['blockchain_node.node_id'], name=op.f('fk_blockchain_sync_log_target_node_id_blockchain_node')),
        sa.PrimaryKeyConstraint('sync_log_id', name=op.f('pk_blockchain_sync_log')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_blockchain_sync_log_source_node_id'), 'blockchain_sync_log', ['source_node_id'], unique=False)
    op.create_index(op.f('ix_blockchain_sync_log_target_node_id'), 'blockchain_sync_log', ['target_node_id'], unique=False)


def downgrade() -> None:
    # Table drops remove their constraints and FK-supporting indexes together.
    op.drop_table('blockchain_sync_log')
    op.drop_table('blockchain_verification_log')
    op.drop_table('blockchain_event')
    op.drop_table('blockchain_node')
    op.drop_table('attachment')
    op.drop_table('login_log')
    op.drop_table('audit_log')
    op.drop_table('print_log')
    op.drop_table('email_log')
    op.drop_table('report_verification')
    op.drop_table('report_signatory')
    op.drop_table('signatory')
    op.drop_table('report_patient_snapshot')
    op.drop_table('report_result_item')
    op.drop_table('lab_report')
    op.drop_table('report_template')
