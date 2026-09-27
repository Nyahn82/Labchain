"""Forward-only report lifecycle outbox; refuse ambiguous historical events.

Revision ID: 20260924_01
Revises: 20260920_01

Run online with application writers quiesced. MySQL DDL is not transactional;
inspect/reconcile partial DDL before retrying a failed deployment. Offline SQL
is deliberately refused because it cannot enforce the mandatory data guard.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '20260924_01'
down_revision = '20260920_01'
branch_labels = None
depends_on = None

NEW_COLUMNS = (
    'deduplication_key', 'entity_reference', 'canonical_payload', 'previous_hash',
    'predecessor_event_id', 'occurred_at', 'attempt_count', 'next_attempt_at',
    'processing_started_at', 'lease_token', 'lease_expires_at', 'last_error_code',
    'last_error', 'fabric_transaction_id', 'fabric_block_number',
    'fabric_validation_code', 'confirmed_at', 'updated_at',
)
CHECKS = {
    'processing_lease_required': "event_status != 'PROCESSING' OR (processing_started_at IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
    'confirmation_required': "event_status != 'CONFIRMED' OR (fabric_transaction_id IS NOT NULL AND confirmed_at IS NOT NULL AND fabric_validation_code IS NOT NULL AND fabric_validation_code = 0)",
    'lifecycle_previous_required': "event_type NOT IN ('REPORT_REVOKED', 'REPORT_SUPERSEDED') OR previous_hash IS NOT NULL",
    'attempt_count_nonnegative': 'attempt_count >= 0',
}
INDEXES = {
    'ix_blockchain_event_eligible': ['event_status', 'next_attempt_at', 'event_id'],
    'ix_blockchain_event_lease': ['event_status', 'lease_expires_at', 'event_id'],
    'ix_blockchain_event_entity': ['entity_type', 'entity_id', 'event_id'],
    'ix_blockchain_event_predecessor_event_id': ['predecessor_event_id'],
}


def require_empty_events():
    if op.get_context().as_sql:
        raise RuntimeError('Phase 8B requires an online empty-table check; offline migration is not supported.')
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT event_id FROM blockchain_event LIMIT 1')).first() is not None:
        raise RuntimeError('Phase 8B migration stopped: blockchain_event contains rows. Manual review is required; do not delete or reinterpret ACCEPTED/REJECTED events.')


def upgrade():
    # This guard precedes ALL DDL, including the report UUID column.
    require_empty_events()
    uuid = sa.CHAR(36).with_variant(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), 'mysql')
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), 'mysql')
    timestamp_default = 'CURRENT_TIMESTAMP' if op.get_bind().dialect.name == 'sqlite' else 'CURRENT_TIMESTAMP(6)'
    with op.batch_alter_table('lab_report') as batch:
        batch.add_column(sa.Column('blockchain_entity_uuid', uuid, nullable=True))
        batch.create_unique_constraint(op.f('uq_lab_report_blockchain_entity_uuid'), ['blockchain_entity_uuid'])
    columns = [
        sa.Column('deduplication_key', sa.String(160), nullable=False),
        sa.Column('entity_reference', uuid, nullable=False),
        sa.Column('canonical_payload', sa.Text(), nullable=False),
        sa.Column('previous_hash', sa.CHAR(64), nullable=True),
        sa.Column('predecessor_event_id', sa.BigInteger(), nullable=True),
        sa.Column('occurred_at', timestamp, nullable=False),
        sa.Column('attempt_count', sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql'), nullable=False, server_default=sa.text('0')),
        sa.Column('next_attempt_at', timestamp, nullable=False),
        sa.Column('processing_started_at', timestamp, nullable=True),
        sa.Column('lease_token', uuid, nullable=True),
        sa.Column('lease_expires_at', timestamp, nullable=True),
        sa.Column('last_error_code', sa.String(64), nullable=True),
        sa.Column('last_error', sa.String(512), nullable=True),
        sa.Column('fabric_transaction_id', sa.CHAR(64), nullable=True),
        sa.Column('fabric_block_number', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
        sa.Column('fabric_validation_code', sa.Integer(), nullable=True),
        sa.Column('confirmed_at', timestamp, nullable=True),
        sa.Column('updated_at', timestamp, nullable=False, server_default=sa.text(timestamp_default)),
    ]
    with op.batch_alter_table('blockchain_event') as batch:
        for column in columns:
            batch.add_column(column)
        batch.alter_column('event_status',
            existing_type=sa.Enum('PENDING', 'ACCEPTED', 'REJECTED'), existing_nullable=False,
            type_=sa.Enum('PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD', name='blockchain_event_event_status'),
            server_default=sa.text("'PENDING'"))
        batch.create_unique_constraint(op.f('uq_blockchain_event_deduplication_key'), ['deduplication_key'])
        for name, columns in INDEXES.items():
            batch.create_index(op.f(name), columns)
        batch.create_foreign_key(op.f('fk_blockchain_event_predecessor_event_id_blockchain_event'),
            'blockchain_event', ['predecessor_event_id'], ['event_id'])
        for name, condition in CHECKS.items():
            batch.create_check_constraint(op.f('ck_blockchain_event_' + name), condition)


def downgrade():
    require_empty_events()
    if op.get_bind().execute(sa.text('SELECT report_id FROM lab_report WHERE blockchain_entity_uuid IS NOT NULL LIMIT 1')).first() is not None:
        raise RuntimeError('Phase 8B downgrade stopped: report blockchain identities exist. Manual preservation/review is required.')
    with op.batch_alter_table('blockchain_event') as batch:
        for name in CHECKS:
            batch.drop_constraint(op.f('ck_blockchain_event_' + name), type_='check')
        batch.drop_constraint(op.f('fk_blockchain_event_predecessor_event_id_blockchain_event'), type_='foreignkey')
        for name in INDEXES:
            batch.drop_index(op.f(name))
        batch.drop_constraint(op.f('uq_blockchain_event_deduplication_key'), type_='unique')
        batch.alter_column('event_status',
            existing_type=sa.Enum('PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD'), existing_nullable=False,
            type_=sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', name='blockchain_event_event_status'), server_default=None)
        for name in reversed(NEW_COLUMNS):
            batch.drop_column(name)
    with op.batch_alter_table('lab_report') as batch:
        batch.drop_constraint(op.f('uq_lab_report_blockchain_entity_uuid'), type_='unique')
        batch.drop_column('blockchain_entity_uuid')
