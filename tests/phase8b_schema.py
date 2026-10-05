"""Explicit schema deltas keep historical workbook/migration assertions intact."""
import sqlalchemy as sa
from app.models import Base

EVENT_ADDITIONS = {
    'deduplication_key', 'entity_reference', 'canonical_payload', 'previous_hash',
    'predecessor_event_id', 'occurred_at', 'attempt_count', 'next_attempt_at',
    'processing_started_at', 'lease_token', 'lease_expires_at', 'last_error_code',
    'last_error', 'fabric_transaction_id', 'fabric_block_number',
    'fabric_validation_code', 'confirmed_at', 'updated_at',
}
STATUSES = ['PENDING', 'PROCESSING', 'CONFIRMED', 'FAILED', 'DEAD']
EXTRA_INDEXES = {('event_status', 'next_attempt_at', 'event_id'),
    ('event_status', 'lease_expires_at', 'event_id'), ('entity_type', 'entity_id', 'event_id')}


def before_outbox_metadata():
    """Project current models to pre-8B columns for unchanged historical tests.

    Full post-migration/model equality is separately checked on real MySQL.
    """
    metadata = sa.MetaData(naming_convention=Base.metadata.naming_convention)
    for source in Base.metadata.sorted_tables:
        table = source.to_metadata(metadata)
        removed = EVENT_ADDITIONS if table.name == 'blockchain_event' else {'blockchain_entity_uuid'} if table.name == 'lab_report' else set()
        if table.name == 'user_account':
            removed = {'suspended_at', 'suspended_by_user_id', 'suspension_reason'}
            table.c.account_status.type = sa.Enum('ACTIVE', 'INACTIVE', 'LOCKED', name='account_status')
        for constraint in list(table.constraints):
            if set(constraint.columns.keys()) & removed or (table.name == 'blockchain_event' and isinstance(constraint, sa.CheckConstraint)):
                table.constraints.remove(constraint)
                if isinstance(constraint, sa.ForeignKeyConstraint):
                    table.foreign_keys.difference_update(constraint.elements)
        for index in list(table.indexes):
            if set(index.columns.keys()) & removed or (table.name == 'blockchain_event' and tuple(index.columns.keys()) in EXTRA_INDEXES):
                table.indexes.remove(index)
        for name in removed:
            table._columns.remove(table.c[name])
        if table.name == 'blockchain_event':
            table.c.event_status.type = sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', name='blockchain_event_event_status')
            table.c.event_status.server_default = None
    return metadata
